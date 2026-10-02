# Git Safe Mirror

[![Tests](https://github.com/akostadinov/git_safe_mirror/actions/workflows/tests.yml/badge.svg)](https://github.com/akostadinov/git_safe_mirror/actions/workflows/tests.yml)
[![Container build](https://github.com/akostadinov/git_safe_mirror/actions/workflows/container.yml/badge.svg)](https://github.com/akostadinov/git_safe_mirror/actions/workflows/container.yml)

A tool for maintaining local bare Git repository mirrors.

The mirror job clones repositories as bare repositories, updates existing mirrors without pruning deleted upstream branches, snapshots pre-rewrite branch tips, supports explicit HTTPS and SSH URLs, and can discover public repositories in GitHub organizations. It can be run directly from any directory, or deployed as a scheduled container via Podman Quadlet for users who want stronger isolation.

## Quick start

Run the script directly from a working directory. It defaults to storing everything in the current folder:

```text
~/mirrors/                  ← working directory
├── git_safe_mirror.sh
├── orgs.txt                ← GitHub organizations to discover
├── repos.txt               ← explicit repository URLs
└── mirrors/                ← bare mirror repositories created here
```

Prerequisites:

- Bash, Git, curl, jq
- Optionally: GitHub CLI (`gh`) for faster, authenticated API discovery

Create the config files and run:

```bash
cat >orgs.txt <<'EOF'
# One public GitHub organization per line.
systemd
containers
EOF

cat >repos.txt <<'EOF'
# One remote URL per line.
https://github.com/torvalds/linux.git
git@gitlab.com:group/subgroup/project.git
ssh://git@git.example.net:2222/group/subgroup/project.git
EOF

./git_safe_mirror.sh
```

Each subsequent run only fetches updates — already-cloned mirrors are not recloned.

All paths can be overridden via environment variables:

| Variable    | Default          | Purpose                       |
|-------------|------------------|-------------------------------|
| `BASE_DIR`  | `$PWD/mirrors`   | Mirror storage directory      |
| `ORGS_FILE` | `$PWD/orgs.txt`  | GitHub organization list      |
| `REPOS_FILE`| `$PWD/repos.txt` | Explicit repository URL list  |
| `GH_TOKEN`  |                  | GitHub API discovery only     |

## Configuration

### GitHub organizations

List one public GitHub organization per line in `orgs.txt`:

```text
# One public GitHub organization per line.
systemd
containers
```

The script prefers `gh api --paginate` when `gh` is installed and authenticated. Otherwise it uses GitHub's API with curl and jq. `per_page=100` is only an API page size: all pages are requested until an empty response page is returned.

### Explicit repositories

List one remote URL per line in `repos.txt`:

```text
# One remote URL per line.
https://github.com/torvalds/linux.git
git@gitlab.com:group/subgroup/project.git
ssh://git@git.example.net:2222/group/subgroup/project.git
```

The script accepts explicit HTTPS, SCP-style SSH, and `ssh://` URLs. It rejects local paths and `file://` remotes.

### Mirror layout

The remote host and the entire remote path are retained. GitLab subgroup paths are preserved:

```text
https://github.com/owner/repo.git
→ mirrors/github.com/owner/repo.git

git@gitlab.com:group/subgroup/project.git
→ mirrors/gitlab.com/group/subgroup/project.git
```

For `ssh://` URLs, the destination deliberately omits the port. If you use multiple independent Git servers on the same hostname and different ports with identical paths, change the path-normalization logic to include a sanitized port.

## Authentication

Public HTTPS mirrors need no special setup.

For GitHub API discovery rate limits, optionally set `GH_TOKEN`:

```bash
export GH_TOKEN=your_token_here
```

`GH_TOKEN` affects GitHub API discovery only. It is not Git HTTPS authentication for private repositories.

For SSH mirrors, ensure your SSH key and `known_hosts` are available in the normal locations. To use a dedicated key, set `GIT_SSH_COMMAND`:

```bash
export GIT_SSH_COMMAND="ssh -i /path/to/key -o UserKnownHostsFile=/path/to/known_hosts"

## Mirror semantics

New repositories are created with `git clone --bare` and are not fetched a second time.

For an existing repository, remote branch heads are fetched into an internal staging namespace. The script compares those staged refs with `refs/heads/*`; for any non-fast-forward update it creates a backup branch named like:

```text
refs/heads/main-20261001T202200Z
```

Backup creation, live-branch promotion, and staging-ref deletion happen in one local Git ref transaction. Therefore an interruption before commit leaves live branches unchanged; after commit, backups and corresponding branch changes exist together.

The script does not prune removed upstream branches or tags. Moved tags are updated but are not backed up.

There is no shutdown/sleep inhibitor. During an orderly stop, an interrupted staging fetch may leave staging refs, but the next run refreshes them. Independent backups remain necessary for valuable mirrors and for power-loss recovery.

## Running tests

Tests use `unittest` and require Python 3 plus the `cryptography` package. They start a local mock HTTPS server (with a CA and leaf cert), so no real network is needed.

```bash
pip install --user cryptography
python3 -m unittest discover -s tests -v
```

## Container deployment (Podman + Quadlet)

For users who want stronger isolation, the script can be run inside a rootless Podman container managed by Quadlet. This is an advanced deployment option; most users should run the script directly as described above.

### Requirements

- Fedora or another Linux distribution with recent systemd, rootless Podman, and Quadlet.
- A normal, non-root user with rootless Podman working.
- SELinux enforcing is supported and recommended.

### Installation layout

The example units expect this location:

```text
~/.local/share/git-mirror/
├── config/
│   ├── orgs.txt
│   └── repos.txt
├── mirrors/
└── state/
```

Create it:

```bash
install -d -m 0700 \
  ~/.local/share/git-mirror/{config,mirrors,state} \
  ~/.config/containers/systemd \
  ~/.config/systemd/user
```

Install the repository files:

```bash
install -m 0600 config-examples/orgs.txt \
  ~/.local/share/git-mirror/config/orgs.txt
install -m 0600 config-examples/repos.txt \
  ~/.local/share/git-mirror/config/repos.txt

install -m 0644 contrib/git-mirror.container \
  ~/.config/containers/systemd/git-mirror.container
install -m 0644 contrib/git-mirror.timer \
  ~/.config/systemd/user/git-mirror.timer

systemctl --user daemon-reload
```

Inspect the generated Quadlet service before starting it:

```bash
systemctl --user cat git-mirror.service
```

### Container authentication

For GitHub API discovery rate limits inside the container, create a rootless Podman secret and enable the commented `Secret=` line in the Quadlet:

```bash
printf '%s' 'YOUR_GITHUB_TOKEN' | podman secret create git-mirror-gh-token -
```

SSH URLs are accepted, but the default Quadlet does not mount private keys, `known_hosts`, or an SSH agent. If needed, mount a dedicated restricted directory read-only and configure `GIT_SSH_COMMAND`; do not mount your whole `~/.ssh` by default.

### Image policy

The container references `ghcr.io/akostadinov/git_safe_mirror:latest`, which is built and published automatically by the project's CI on every push to `main` and weekly.

The container unit sets `Pull=always`, so Podman re-pulls the image on each service start. Combined with the daily timer, this ensures the latest image is fetched automatically.

### Local image build (optional)

Alternatively, you can build the image locally and have the container use the local image instead of pulling from the registry. This is useful if you want to run a custom or unreleased version.

To use a local image, change the `Image=` line in `git-mirror.container` to `localhost/git-mirror:current` and install the local build service:

```text
~/.local/share/git-mirror/
├── image/
│   ├── Dockerfile
│   ├── .dockerignore
│   └── git_safe_mirror.sh
├── bin/
│   └── ensure-image.sh
```

```bash
install -d -m 0700 ~/.local/share/git-mirror/{image,bin}

install -m 0644 Dockerfile \
  ~/.local/share/git-mirror/image/Dockerfile
install -m 0644 .dockerignore \
  ~/.local/share/git-mirror/image/.dockerignore
install -m 0644 git_safe_mirror.sh \
  ~/.local/share/git-mirror/image/git_safe_mirror.sh

install -m 0700 contrib/ensure-image.sh \
  ~/.local/share/git-mirror/bin/ensure-image.sh

install -m 0644 contrib/git-mirror-image.service \
  ~/.config/systemd/user/git-mirror-image.service

systemctl --user daemon-reload
```

`ensure-image.sh` maintains `localhost/git-mirror:current`. It rebuilds if the image is missing, source files changed, the tag changed, the record is invalid, or the last successful build is at least 14 days old. You can trigger a manual rebuild:

```bash
~/.local/share/git-mirror/bin/ensure-image.sh
```

The local build service is independent — the container does not depend on it. You can run `ensure-image.sh` manually or via a timer of your choice.

### Test and schedule

Reload units and run one job manually:

```bash
systemctl --user daemon-reload
systemctl --user start git-mirror.service
journalctl --user -u git-mirror.service -b
```

After a successful test, enable the daily timer:

```bash
systemctl --user enable --now git-mirror.timer
systemctl --user list-timers git-mirror.timer
```

For the user timer to run after logout or boot, enable lingering:

```bash
sudo loginctl enable-linger "$USER"
```

### Security model

The intended Quadlet configuration uses rootless Podman, a read-only container filesystem, dropped capabilities, no-new-privileges, an ephemeral restricted `/tmp`, a read-only config mount, and one dedicated writable mirror mount labeled with `:Z` for SELinux.

It does not use privileged mode, host networking, published ports, the Podman socket, or broad host directory mounts. These controls reduce exposure but do not protect the mirror data from a compromised process that has write access to the mirror mount. Keep separate backups.

### Troubleshooting

Generated service missing:

```bash
systemctl --user daemon-reload
systemctl --user cat git-mirror.service
```

Test image build alone (local build only):

```bash
~/.local/share/git-mirror/bin/ensure-image.sh
podman image inspect localhost/git-mirror:current
```

Check service output:

```bash
journalctl --user -fu git-mirror.service
```

Check SELinux AVCs:

```bash
ausearch -m AVC,USER_AVC -ts recent
```

Do not work around SELinux denials by disabling labels. Verify the expected rootless bind mounts carry `:Z` instead.
