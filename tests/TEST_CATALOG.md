# Test catalog for git_safe_mirror.sh

Conventions: log `<ISO8601-UTC> | <msg>` on stderr; prefixes `CLONE  `, `UPDATE `, `ORG    `, `WARN: `, `FORCE PUSH on <branch>: staging backup <ref>`, `DONE: <N> repos, <F> failures`. Exit 0 iff FAILS==0. Mirror layout `BASE_DIR/host/<full-path>.git`. Backup refs `refs/heads/<branch>-<14-digit UTC TS>`. Dumb HTTP: git requests are GETs only (no POST upload-pack). Failure injection via `fail_nth_info_refs(host, path_prefix, n, status)`.

## CLONE (test_clone.py)
- CLONE-01 https clone: exit 0, `CLONE  <url>`, `DONE: 1 repos, 0 failures`, mirror at mirror_dir, bare, refs/heads/main == upstream tip, remote.origin.url == url, one info/refs GET captured.
- CLONE-02 scp-style `git@gitlab.com:group/subgroup/project.git`: mirror at BASE_DIR/gitlab.com/group/subgroup/project.git (FULL path), remote.origin.url == scp-style URL.
- CLONE-03 `ssh://git@git.example.net:2222/group/project.git`: mirror at BASE_DIR/git.example.net/group/project.git (port omitted), remote.origin.url keeps port.
- CLONE-04 `.git` suffix + trailing slash: `owner/repo.git` and `owner/repo2/` → repo.git and repo2.git.
- CLONE-05 host collision: same owner/repo on github.com and git.example.net → two distinct mirrors with differing content.
- CLONE-06 clone failure (mock 404 on info/refs): exit 1, `CLONE  <url>`, `DONE: 1 repos, 1 failures`, NO WARN for clone.
- CLONE-07 empty dir (no objects/) at mirror path → treated as clone, succeeds.
- CLONE-08 clone path does not run pack-refs/tag sync: no staging refs after clone.

## UPDATE (test_update.py)
- UPDATE-01 fast-forward: run1 clone main@A, upstream append → main@C, run2. exit 0, `UPDATE <url>`, no FORCE PUSH, main==C, no backup ref, no staging refs.
- UPDATE-02 new upstream branch: run1 clone main, upstream add feature@F, run2. feature==F, main unchanged, no backup for feature.
- UPDATE-03 force-push/non-ff: run1 clone main@A, upstream rewrite main to B (non-descendant), run2. exit 0, `FORCE PUSH on main: staging backup refs/heads/main-[0-9]{14}`, backup ref == A, main == B, no staging refs.
- UPDATE-04 transaction: force-push main + fast-forward dev in one run → backup exists, main==B, dev==new, no staging refs.
- UPDATE-06 no-prune: run1 clone main+feature, upstream delete feature, run2. feature still exists, main updated.
- UPDATE-07 staging fetch failure (fail_nth_info_refs n=1 status=500): exit 1, `WARN: branch staging fetch failed: <url>`, main unchanged, no backup, no staging refs.
- UPDATE-08 set-url on update: run1 clone https URL, repos.txt changed to scp-style (same host/owner/name), upstream new commit, run2. `UPDATE <scp-url>`, remote.origin.url == scp-style, branch advanced.
- UPDATE-09 multi-repo: one good (new commit) + one bad (fetch 500). exit 1, good updated, bad `WARN: branch staging fetch failed`, `DONE: 2 repos, 1 failures`.

## TAGS (test_tags.py)
- TAG-01 new lightweight tag synced: run1 no tags, upstream add v2, run2. refs/tags/v2 exists.
- TAG-02 tags not pruned: run1 tag v1, upstream delete v1, run2. v1 still exists.
- TAG-03 moved tag updated, no backup: run1 v1@A, upstream `git tag -f v1 B`, run2. v1==B, no v1-* ref, no FORCE PUSH.
- TAG-04 annotated tag: upstream add annotated release-1, run2. `git cat-file -t refs/tags/release-1` == tag, dereferenced ^{commit} == expected.
- TAG-05 tag fetch failure (fail_nth_info_refs n=2 status=500): run1 OK, upstream new commit, run2. exit 1, `WARN: tag fetch failed: <url>`, live branch STILL updated.

## ORG DISCOVERY (test_org_discovery.py) — curl+jq path, no gh
- ORG-01 pagination: pages of 100,100,5 then []. All cloned, `DONE: 205 repos, 0 failures`, 4 API GETs with page=1..4, Accept: application/vnd.github+json.
- ORG-02 empty org ([]): exit 0, no CLONE, `DONE: 0 repos, 0 failures`, 1 API request.
- ORG-03 non-array ({"message":"Not Found"}): exit 1, `WARN: listing failed for org <org>`, `DONE: 0 repos, 1 failures`.
- ORG-04 transport failure (500): exit 1, `WARN: listing failed for org <org>`.
- ORG-05 GH_TOKEN → `Authorization: Bearer <token>` header captured.
- ORG-06 no GH_TOKEN → no Authorization header.
- ORG-07 clone_url extraction: repo objects with distinct clone_url/ssh_url/html_url/git_url → cloned URL == clone_url.
- ORG-08 invalid org name (`bad_org!`): exit 1, `WARN: listing failed for org bad_org!`, ZERO API requests.
- ORG-09 org listing failure does not block explicit repos: broken org + good repo → exit 1, good cloned, `DONE: 1 repos, 1 failures`.

## URL VALIDATION (test_url_validation.py)
Common: exit 1, `WARN: rejected repository URL: <url>`, `DONE: 1 repos, 1 failures`, no mirror dir.
- URL-01 file:///etc/passwd
- URL-02 /srv/git/repo.git
- URL-03 ./repo.git
- URL-04 ../repo.git
- URL-05 ~/repo.git
- URL-06 empty URL (extract validate_url via sed from the script, source in bash, assert rejects "")
- URL-07 plain github.com:owner/repo (no scheme)
- URL-08 accepted forms matrix: https, scp-style, ssh:// → no `WARN: rejected repository URL`.

## CONFIG (test_config.py)
- CFG-01 comments (# lines) ignored.
- CFG-02 blank/whitespace-only lines ignored.
- CFG-03 CRLF stripped: orgs.txt with \r\n → `ORG    <org>` (no \r), API path has no %0D.

## DEDUP (test_dedup.py)
- DEDUP-01 same URL in repos.txt and from org → synced once (one CLONE, `DONE: 1 repos, 0 failures`).
- DEDUP-02 duplicate URL within repos.txt → synced once.
- DEDUP-03 exact-string key: `owner/repo.git` and `owner/repo` → two entries; observe actual outcome (both map to same dir; second clone into non-empty dir fails) and document.

## LAYOUT (test_layout.py)
- LAYOUT-01 BASE_DIR/host/owner/name.git correctness, bare, HEAD symref.
- LAYOUT-02 subgroup FULL path preserved: git@gitlab.com:group/subgroup/project.git → BASE_DIR/gitlab.com/group/subgroup/project.git.
- LAYOUT-03 ssh:// port omitted from path, kept in remote URL.
- LAYOUT-04 ./ and .. components rejected: `WARN: rejected repository destination: <url>`.

## FAILURES (test_failures.py)
- FAIL-01 clone failure → exit 1, `DONE: 1 repos, 1 failures`, no WARN.
- FAIL-02 update fetch failure → exit 1, `DONE: 1 repos, 1 failures`, live refs unchanged.
- FAIL-03 summary format: mixed run → `DONE: 4 repos, 3 failures`, exit 1.
- FAIL-04 all-green → exit 0, `DONE: N repos, 0 failures`.
- FAIL-05 rejected destination: `https://github.com/repo` (single path component) → `WARN: rejected repository destination: https://github.com/repo`, exit 1.

## IDEMPOTENCY (test_idempotency.py)
- IDEM-01 second run no upstream change: `UPDATE <url>` (not CLONE), refs identical, no new refs, no staging refs.
- IDEM-02 CLONE appears once across two runs.

## PACK (test_pack.py)
- PACK-01 packed-refs written after update: packed-refs exists, contains refs/heads/main and the backup ref.
