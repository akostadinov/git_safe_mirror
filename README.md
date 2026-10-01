# Git Safe Mirror

A rootless Podman + Quadlet setup for maintaining local bare Git repository mirrors.

The mirror job clones repositories as bare repositories, updates existing mirrors without pruning deleted upstream branches, snapshots pre-rewrite branch tips, supports explicit HTTPS and SSH URLs, and can discover public repositories in GitHub organizations. It is intended for rootless Podman on Fedora with SELinux enabled.

## Requirements

- Fedora or another Linux distribution with recent systemd, rootless Podman, and Quadlet.
- A normal, non-root user with rootless Podman working.
- SELinux enforcing is supported and recommended.
- Network access to configured Git servers.
- The generated image supplies Bash, Git, curl, jq, GitHub CLI, and CA certificates.

No host home directory, Podman socket, host `/etc`, or SSH credentials are mounted by default.

## Suggested installation layout

The example units expect this location:

```text
~/.local/share/git-mirror/
├── image/
│   ├── Dockerfile
│   ├── .dockerignore
│   └── git_safe_mirror.sh
├── config/
│   ├── orgs.txt
│   └── repos.txt
├── mirrors/
├── bin/
│   └── ensure-image.sh
└── state/
```

Create it:

```bash
install -d -m 0700 \
  ~/.local/share/git-mirror/{image,config,mirrors,bin,state} \
  ~/.config/containers/systemd \
  ~/.config/systemd/user
```

Install the repository files:

```bash
install -m 0644 Dockerfile \
  ~/.local/share/git-mirror/image/Dockerfile
install -m 0644 .dockerignore \
  ~/.local/share/git-mirror/image/.dockerignore
install -m 0644 git_safe_mirror.sh \
  ~/.local/share/git-mirror/image/git_safe_mirror.sh

install -m 0600 config-examples/orgs.txt \
  ~/.local/share/git-mirror/config/orgs.txt
install -m 0600 config-examples/repos.txt \
  ~/.local/share/git-mirror/config/repos.txt

install -m 0700 contrib/ensure-image.sh \
  ~/.local/share/git-mirror/bin/ensure-image.sh

install -m 0644 contrib/git-mirror.container \
  ~/.config/containers/systemd/git-mirror.container
install -m 0644 contrib/git-mirror-image.service \
  ~/.config/systemd/user/git-mirror-image.service
install -m 0644 contrib/git-mirror.timer \
  ~/.config/systemd/user/git-mirror.timer

systemctl --user daemon-reload
```

Inspect the generated Quadlet service before starting it:

```bash
systemctl --user cat git-mirror.service
```

## Configuration

### GitHub organizations

Edit `~/.local/share/git-mirror/config/orgs.txt`:

```text
# One public GitHub organization per line.
systemd
containers
```

The script prefers `gh api --paginate` when `gh` is installed and authenticated. Otherwise it uses GitHub's API with curl and jq. `per_page=100` is only an API page size: all pages are requested until an empty response page is returned.

### Explicit repositories

Edit `~/.local/share/git-mirror/config/repos.txt`:

```text
# One remote URL per line.
https://github.com/torvalds/linux.git
git@gitlab.com:group/subgroup/project.git
ssh://git@git.example.net:2222/group/subgroup/project.git
```

The script accepts explicit HTTPS, SCP-style SSH, and `ssh://` URLs. It rejects local paths and `file://` remotes so the container cannot treat its own mounted filesystem as an input Git source.

### Mirror layout

The remote host and the entire remote path are retained. GitLab subgroup paths are preserved:

```text
https://github.com/owner/repo.git
→ ~/.local/share/git-mirror/mirrors/github.com/owner/repo.git

git@gitlab.com:group/subgroup/project.git
→ ~/.local/share/git-mirror/mirrors/gitlab.com/group/subgroup/project.git
```

For `ssh://` URLs, the destination deliberately omits the port. If you use multiple independent Git servers on the same hostname and different ports with identical paths, change the path-normalization logic to include a sanitized port.

## Authentication

Public HTTPS mirrors need no special setup.

For GitHub API discovery rate limits, optionally create a rootless Podman secret and enable the commented `Secret=` line in the Quadlet:

```bash
printf '%s' 'YOUR_GITHUB_TOKEN' | podman secret create git-mirror-gh-token -
```

`GH_TOKEN` affects GitHub API discovery only. It is not Git HTTPS authentication for private repositories.

SSH URLs are accepted, but the default Quadlet does not mount private keys, `known_hosts`, or an SSH agent. If needed, mount a dedicated restricted directory read-only and configure `GIT_SSH_COMMAND`; do not mount your whole `~/.ssh` by default.

## Mirror semantics

New repositories are created with `git clone --bare` and are not fetched a second time.

For an existing repository, remote branch heads are fetched into an internal staging namespace. The script compares those staged refs with `refs/heads/*`; for any non-fast-forward update it creates a backup branch named like:

```text
refs/heads/main-20261001T202200Z
```

Backup creation, live-branch promotion, and staging-ref deletion happen in one local Git ref transaction. Therefore an interruption before commit leaves live branches unchanged; after commit, backups and corresponding branch changes exist together.

The script does not prune removed upstream branches or tags. Moved tags are updated but are not backed up.

There is no shutdown/sleep inhibitor. During an orderly stop, an interrupted staging fetch may leave staging refs, but the next run refreshes them. Independent backups remain necessary for valuable mirrors and for power-loss recovery.

## Image policy

`ensure-image.sh` maintains `localhost/git-mirror:current`. It rebuilds if the image is missing, source files changed, the tag changed, the record is invalid, or the last successful build is at least 14 days old.

The build uses:

```bash
podman build --pull=always --no-cache --tag localhost/git-mirror:current CONTEXT
```

After a successful rebuild it runs:

```bash
podman image prune --force
```

`--force` only suppresses the confirmation prompt. Without `--all`, this prunes dangling images only. Do not automatically run `podman image prune --all` or `podman system prune`, since the rootless Podman image store may be shared with other applications under the same user.

## Test and schedule

Reload units and run one job manually:

```bash
systemctl --user daemon-reload
systemctl --user start git-mirror.service
journalctl --user -u git-mirror-image.service -u git-mirror.service -b
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

## Security model

The intended Quadlet configuration uses rootless Podman, a read-only container filesystem, dropped capabilities, no-new-privileges, an ephemeral restricted `/tmp`, a read-only config mount, and one dedicated writable mirror mount labeled with `:Z` for SELinux.

It does not use privileged mode, host networking, published ports, the Podman socket, or broad host directory mounts. These controls reduce exposure but do not protect the mirror data from a compromised process that has write access to the mirror mount. Keep separate backups.

## Troubleshooting

Generated service missing:

```bash
systemctl --user daemon-reload
systemctl --user cat git-mirror.service
```

Test image build alone:

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
