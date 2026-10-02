"""Shared test harness for git_safe_mirror.sh.

Provides:
  - a locally generated CA + leaf certificate (SANs for the mocked hosts)
  - a mock HTTPS server that serves both the GitHub REST API and git smart
    HTTP (via git http-backend) for api.github.com / github.com /
    gitlab.com / git.example.net
  - a CONNECT proxy that tunnels every connection straight to the mock HTTPS
    server, so curl/git perform real TLS verification against the test CA
  - MirrorTestCase, a unittest base class with helpers to create upstream
    repos, run the script, and inspect the resulting mirrors
"""

import datetime
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(REPO_ROOT, "git_safe_mirror.sh")

MOCK_HOSTS = ["api.github.com", "github.com", "gitlab.com", "git.example.net"]

GIT_HTTP_BACKEND = os.path.join(
    subprocess.check_output(["git", "--exec-path"], text=True).strip(),
    "git-http-backend",
)

PROXY_VARS = [
    "http_proxy", "https_proxy", "all_proxy", "no_proxy", "ftp_proxy",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "FTP_PROXY",
]


def repo_json(owner, name, host="github.com"):
    return {
        "name": name,
        "clone_url": "https://%s/%s/%s.git" % (host, owner, name),
        "ssh_url": "git@%s:%s/%s.git" % (host, owner, name),
        "html_url": "https://%s/%s/%s" % (host, owner, name),
        "git_url": "git://%s/%s/%s.git" % (host, owner, name),
    }


def _generate_certificates(cert_dir):
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "git-safe-mirror-test-ca")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, MOCK_HOSTS[0])]))
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(h) for h in MOCK_HOSTS]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    ca_path = os.path.join(cert_dir, "ca.pem")
    leaf_path = os.path.join(cert_dir, "leaf.pem")
    leaf_key_path = os.path.join(cert_dir, "leaf.key")
    with open(ca_path, "wb") as f:
        f.write(ca_cert.public_bytes(serialization.Encoding.PEM))
    with open(leaf_path, "wb") as f:
        f.write(leaf_cert.public_bytes(serialization.Encoding.PEM))
    with open(leaf_key_path, "wb") as f:
        f.write(leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    return ca_path, leaf_path, leaf_key_path


def _split_git_path(repo):
    """Split a git URL path into (repo_name_ending_in_.git, rest).

    repo is like 'owner/repo.git/info/refs' or 'owner/repo/info/refs'
    (the .git suffix is optional in the URL).
    """
    if ".git/" in repo:
        idx = repo.index(".git/")
        return repo[:idx + 4], repo[idx + 4:]
    if repo.endswith(".git"):
        return repo, ""
    for marker in ("/info/refs", "/objects/"):
        if marker in repo:
            idx = repo.index(marker)
            return repo[:idx] + ".git", repo[idx:]
    return repo + ".git", ""


class _MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _record(self):
        runtime().record_request(
            self.command,
            self.headers.get("Host", ""),
            self.path,
            dict(self.headers),
        )

    def _send(self, status, body=b"", content_type="text/plain"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        self._record()
        rt = runtime()
        path, _, query = self.path.partition("?")
        if path.startswith("/orgs/") and path.endswith("/repos"):
            host = self.headers.get("Host", "").split(":")[0]
            self._api_response(rt, host, path[len("/orgs/"):-len("/repos")], query)
            return
        m = re.match(r"^/(?P<host>[^/]+)/(?P<repo>.+)$", path)
        if m:
            repo_name, rest = _split_git_path(m.group("repo"))
            fail_status = rt.match_fail_info(m.group("host"), path)
            if fail_status is not None:
                self._send(fail_status, b"injected info/refs failure")
                return
            self._git_serve_file(rt, m.group("host"), repo_name, rest)
            return
        self._send(404, b"not found")

    def do_POST(self):
        self._record()
        self._send(404, b"not found")

    def _api_response(self, rt, host, org, query):
        spec = rt.api_specs.get((host, org))
        if spec is None:
            self._send(404, b'{"message":"Not Found"}', "application/json")
            return
        if spec.get("status"):
            self._send(spec["status"], spec.get("body") or b"boom", "application/json")
            return
        pages = spec.get("pages") or []
        page = 1
        for part in query.split("&"):
            if part.startswith("page="):
                try:
                    page = int(part.split("=", 1)[1])
                except ValueError:
                    page = 1
        if 1 <= page <= len(pages):
            body = json.dumps(pages[page - 1]).encode()
        else:
            body = b"[]"
        self._send(200, body, "application/json")

    def _git_serve_file(self, rt, host, repo, rest):
        """Serve a git repo over dumb HTTP: static files from the bare repo.

        git's dumb client fetches info/refs (plain text) and objects/...
        directly, so no smart-HTTP protocol is involved.
        """
        repo_dir = os.path.join(rt.upstream_root, host, repo)
        if not os.path.isdir(repo_dir):
            repo_dir = rt.fallback_repo()
        file_path = os.path.join(repo_dir, rest.lstrip("/"))
        if os.path.isfile(file_path):
            with open(file_path, "rb") as f:
                body = f.read()
            ctype = "application/octet-stream" if rest.startswith("/objects/") else "text/plain"
            self._send(200, body, ctype)
        else:
            self._send(404, b"not found")


class _ConnectProxy:
    """Dumb CONNECT proxy: tunnels every connection to the mock HTTPS server."""

    def __init__(self, target_port):
        self._target = target_port
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(128)
        self.port = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        upstream = None
        try:
            conn.settimeout(60)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    conn.close()
                    return
                data += chunk
            if not data.split(b"\r\n", 1)[0].startswith(b"CONNECT"):
                conn.close()
                return
            upstream = socket.create_connection(("127.0.0.1", self._target), timeout=60)
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self._pump(conn, upstream)
        except Exception:
            for s in (conn, upstream):
                if s is not None:
                    try:
                        s.close()
                    except Exception:
                        pass

    @staticmethod
    def _pump(a, b):
        def copy(src, dst, done):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except Exception:
                    pass
                done.set()

        done_a = threading.Event()
        done_b = threading.Event()
        ta = threading.Thread(target=copy, args=(a, b, done_a), daemon=True)
        tb = threading.Thread(target=copy, args=(b, a, done_b), daemon=True)
        ta.start()
        tb.start()
        done_a.wait(timeout=120)
        done_b.wait(timeout=120)
        for s in (a, b):
            try:
                s.close()
            except Exception:
                pass


class MockRuntime:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="gsm-runtime-")
        self.cert_dir = os.path.join(self.tmpdir, "certs")
        os.makedirs(self.cert_dir)
        self.ca_cert_path, self.leaf_cert_path, self.leaf_key_path = _generate_certificates(self.cert_dir)
        self.upstream_root = os.path.join(self.tmpdir, "upstreams")
        os.makedirs(self.upstream_root)
        self.capture = []
        self._capture_lock = threading.Lock()
        self.api_specs = {}
        self._fail_info = []
        self._upload_counter = {}
        self._fallback = None
        self._fallback_lock = threading.Lock()
        self.http_port = None
        self._start_servers()

    def _start_servers(self):
        # HTTPS server: curl reaches it through the CONNECT proxy.
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.leaf_cert_path, self.leaf_key_path)
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
        self._httpd.daemon_threads = True
        self._httpd.socket = ctx.wrap_socket(self._httpd.socket, server_side=True)
        self.mock_port = self._httpd.server_address[1]
        self._http_thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._http_thread.start()
        self._proxy = _ConnectProxy(self.mock_port)
        self.proxy_url = "http://127.0.0.1:%d" % self._proxy.port

        # Plain HTTP server: git connects here directly (no proxy), which
        # avoids a smart-HTTP-detection failure observed when git tunnels
        # through the CONNECT proxy.
        self._http_plain = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
        self._http_plain.daemon_threads = True
        self.http_port = self._http_plain.server_address[1]
        self._http_plain_thread = threading.Thread(
            target=self._http_plain.serve_forever, daemon=True)
        self._http_plain_thread.start()

    def shutdown(self):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def record_request(self, method, host, path, headers):
        with self._capture_lock:
            self.capture.append({
                "method": method,
                "host": host.split(":")[0],
                "path": path,
                "query": path.partition("?")[2] if "?" in path else "",
                "headers": headers,
            })

    def requests(self):
        with self._capture_lock:
            return list(self.capture)

    def clear_requests(self):
        with self._capture_lock:
            self.capture.clear()

    def configure_api(self, org, host="github.com", pages=None, status=None, body=None):
        if status is None and body is not None:
            status = 200
        self.api_specs[(host, org)] = {"pages": pages, "status": status, "body": body}

    def fail_nth_info_refs(self, host, path_prefix, n, status):
        """Fail the nth (1-based) matching info/refs GET with `status`."""
        self._fail_info.append((host, path_prefix, n, status))

    def match_fail_info(self, host, path):
        """Return the injected failure status for the nth matching info/refs
        GET, or None if the request should proceed normally."""
        for rule_host, prefix, n, status in self._fail_info:
            if rule_host == host and path.startswith(prefix):
                key = (rule_host, prefix, n)
                count = self._upload_counter.get(key, 0) + 1
                self._upload_counter[key] = count
                if count == n:
                    return status
        return None

    def clear_failures(self):
        self._fail_info.clear()
        self._upload_counter.clear()

    def fallback_repo(self):
        with self._fallback_lock:
            if self._fallback is None:
                d = os.path.join(self.upstream_root, "__fallback__.git")
                if not os.path.isdir(d):
                    subprocess.run(
                        ["git", "init", "--bare", "--quiet", d],
                        check=True, capture_output=True, env=UpstreamRepo.git_env(),
                    )
                    w = os.path.join(self.tmpdir, "fallback-work")
                    subprocess.run(
                        ["git", "init", "-b", "main", "--quiet", w],
                        check=True, capture_output=True, env=UpstreamRepo.git_env(),
                    )
                    subprocess.run(
                        ["git", "-C", w, "-c", "user.name=Test", "-c", "user.email=test@example.com",
                         "commit", "--allow-empty", "--quiet", "-m", "fallback"],
                        check=True, capture_output=True, env=UpstreamRepo.git_env(),
                    )
                    subprocess.run(
                        ["git", "-C", w, "push", "--quiet", d, "main"],
                        check=True, capture_output=True, env=UpstreamRepo.git_env(),
                    )
                    shutil.rmtree(w, ignore_errors=True)
                    subprocess.run(
                        ["git", "--git-dir", d, "update-server-info"],
                        check=True, capture_output=True, env=UpstreamRepo.git_env(),
                    )
                self._fallback = d
            return self._fallback


def runtime():
    if MockRuntime._instance is None:
        with MockRuntime._lock:
            if MockRuntime._instance is None:
                MockRuntime._instance = MockRuntime()
    return MockRuntime._instance


class UpstreamRepo:
    """A test upstream repo: a bare repo served by the mock, plus a local
    non-bare working clone used to mutate it between script runs."""

    def __init__(self, host, path):
        self.host = host
        self.path = path
        rt = runtime()
        self.bare_dir = os.path.join(rt.upstream_root, host, path + ".git")
        self.work_dir = os.path.join(rt.tmpdir, "work", host, path)
        for d in (self.bare_dir, self.work_dir):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(os.path.dirname(self.work_dir), exist_ok=True)
        env = self.git_env()
        subprocess.run(["git", "init", "-b", "main", "--quiet", self.work_dir],
                       check=True, capture_output=True, env=env)
        self.commit("initial %s/%s" % (host, path))
        subprocess.run(["git", "init", "--bare", "--quiet", self.bare_dir],
                       check=True, capture_output=True, env=env)
        self.push("main")
        self._update_server_info()

    @staticmethod
    def git_env():
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        env["GIT_CONFIG_SYSTEM"] = "/dev/null"
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "init.defaultBranch"
        env["GIT_CONFIG_VALUE_0"] = "main"
        for k in list(env):
            if "proxy" in k.lower():
                del env[k]
        return env

    def _git(self, *args, check=True):
        return subprocess.run(
            ["git", "-C", self.work_dir, "-c", "user.name=Test",
             "-c", "user.email=test@example.com", *args],
            check=check, capture_output=True, text=True, env=self.git_env(),
        )

    def commit(self, message="commit", branch=None):
        if branch:
            self._git("checkout", "--quiet", branch)
        self._git("commit", "--allow-empty", "--quiet", "-m", message)
        oid = self._git("rev-parse", "HEAD").stdout.strip()
        if os.path.isdir(self.bare_dir):
            self.push("HEAD")
        return oid

    def branch(self, name, start=None):
        args = ["branch", name]
        if start:
            args.append(start)
        self._git(*args)
        self.push(name)

    def tip(self, branch="main"):
        return self._git("rev-parse", branch).stdout.strip()

    def push(self, *specs, force=False):
        args = ["push"]
        if force:
            args.append("--force")
        args.append(self.bare_dir)
        args.extend(specs)
        self._git(*args)
        self._update_server_info()

    def _update_server_info(self):
        subprocess.run(
            ["git", "--git-dir", self.bare_dir, "update-server-info"],
            check=True, capture_output=True, env=self.git_env(),
        )

    def reset_to(self, branch, oid):
        self._git("checkout", "--quiet", branch)
        self._git("reset", "--hard", oid)
        self.push(branch, force=True)

    def rewrite_main(self, new_message="rewrite"):
        self._git("checkout", "--quiet", "--orphan", "__rewrite__")
        self._git("commit", "--allow-empty", "--quiet", "-m", new_message)
        oid = self._git("rev-parse", "HEAD").stdout.strip()
        self._git("checkout", "--quiet", "main")
        self._git("reset", "--hard", oid)
        self.push("main", force=True)
        return oid

    def delete_branch(self, name):
        self._git("push", self.bare_dir, "--delete", name)
        self._update_server_info()

    def tag(self, name, target=None, annotated=False):
        args = ["tag"]
        if annotated:
            args += ["-a", "-m", "tag %s" % name]
        args.append(name)
        if target:
            args.append(target)
        self._git(*args)
        self.push("refs/tags/%s" % name)

    def move_tag(self, name, target):
        self._git("tag", "-f", name, target)
        self.push("refs/tags/%s" % name, force=True)

    def delete_tag(self, name):
        self._git("push", self.bare_dir, "--delete", "tags/%s" % name)


class MirrorTestCase(unittest.TestCase):
    """Base class: per-test scratch dirs + helpers to run the script."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="gsm-test-")
        self.base_dir = os.path.join(self.tmpdir, "mirrors")
        os.makedirs(self.base_dir)
        self.config_dir = os.path.join(self.tmpdir, "config")
        os.makedirs(self.config_dir)
        self.home_dir = os.path.join(self.tmpdir, "home")
        os.makedirs(self.home_dir)
        self.runtime = runtime()
        self.runtime.clear_failures()
        self.runtime.clear_requests()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.runtime.clear_failures()
        self.runtime.clear_requests()

    def run_script(self, orgs=(), repos=(), token=None, orgs_raw=None, repos_raw=None):
        orgs_file = os.path.join(self.config_dir, "orgs.txt")
        repos_file = os.path.join(self.config_dir, "repos.txt")
        if orgs_raw is not None:
            with open(orgs_file, "w", newline="") as f:
                f.write(orgs_raw)
        else:
            with open(orgs_file, "w") as f:
                for line in orgs:
                    f.write(line + "\n")
        if repos_raw is not None:
            with open(repos_file, "w", newline="") as f:
                f.write(repos_raw)
        else:
            with open(repos_file, "w") as f:
                for line in repos:
                    f.write(line + "\n")

        gitconfig = os.path.join(self.tmpdir, "gitconfig")
        with open(gitconfig, "w") as f:
            port = self.runtime.http_port
            f.write('[url "http://127.0.0.1:%d/github.com/"]\n'
                    "\tinsteadOf = https://github.com/\n"
                    "\tinsteadOf = git@github.com:\n"
                    "\tinsteadOf = ssh://git@github.com:22/\n" % port)
            f.write('[url "http://127.0.0.1:%d/gitlab.com/"]\n'
                    "\tinsteadOf = https://gitlab.com/\n"
                    "\tinsteadOf = git@gitlab.com:\n" % port)
            f.write('[url "http://127.0.0.1:%d/git.example.net/"]\n'
                    "\tinsteadOf = https://git.example.net/\n"
                    "\tinsteadOf = ssh://git@git.example.net:2222/\n" % port)

        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.home_dir,
            "BASE_DIR": self.base_dir,
            "ORGS_FILE": orgs_file,
            "REPOS_FILE": repos_file,
            "https_proxy": self.runtime.proxy_url,
            "CURL_CA_BUNDLE": self.runtime.ca_cert_path,
            "GIT_CONFIG_GLOBAL": gitconfig,
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "no_proxy": "127.0.0.1,github.com,gitlab.com,git.example.net",
            "NO_PROXY": "127.0.0.1,github.com,gitlab.com,git.example.net",
            "TMPDIR": self.tmpdir,
        }
        if token is not None:
            env["GH_TOKEN"] = token
        for k in list(env):
            if k in PROXY_VARS and k != "https_proxy":
                del env[k]

        return subprocess.run(
            ["bash", SCRIPT_PATH],
            env=env,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def make_upstream(self, host, path):
        return UpstreamRepo(host, path)

    def mirror_dir(self, url):
        """Expected mirror path, mirroring the script's repo_dir_for_url:
        BASE_DIR/host/<full-path>.git (port stripped, all components kept)."""
        if url.startswith("https://"):
            rest = url[len("https://"):]
            host, _, path = rest.partition("/")
        elif url.startswith("ssh://"):
            rest = url[len("ssh://"):]
            if "@" in rest:
                rest = rest.split("@", 1)[1]
            hostport, _, path = rest.partition("/")
            host = hostport.split(":")[0]
        else:
            hostpart, _, path = url.partition(":")
            host = hostpart.split("@")[-1]
        path = path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            return None
        return os.path.join(self.base_dir, host, *parts) + ".git"

    def refs(self, url):
        out = subprocess.run(
            ["git", "--git-dir", self.mirror_dir(url), "for-each-ref",
             "--format=%(refname) %(objectname)"],
            capture_output=True, text=True, check=True,
        ).stdout
        result = {}
        for line in out.splitlines():
            ref, _, oid = line.partition(" ")
            result[ref] = oid
        return result

    def ref_exists(self, url, ref):
        return ref in self.refs(url)

    def captured(self):
        return self.runtime.requests()

    def api_captured(self):
        return [r for r in self.captured() if r["path"].startswith("/orgs/")]

    def git_captured(self, url):
        prefix = self.mirror_dir(url)
        if prefix is None:
            return []
        rel = os.path.relpath(prefix, self.base_dir)
        repo_prefix = "/" + rel
        return [r for r in self.captured() if r["path"].startswith(repo_prefix)]
