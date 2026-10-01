#!/usr/bin/env bash
#
# Build localhost/git-mirror:current only when missing, source-changed,
# retagged externally, or at least fourteen days old.
#
set -euo pipefail
umask 077

IMAGE='localhost/git-mirror:current'
BASE="${HOME}/.local/share/git-mirror"
CONTEXT="${BASE}/image"
STATE="${BASE}/state"
RECORD="${STATE}/build.record"
LOCK="${STATE}/build.lock"
MAX_AGE=$((14 * 24 * 60 * 60))

mkdir -p -m 0700 "$STATE"

# Avoid simultaneous manual/timer builds.
exec 9>"$LOCK"
flock 9

source_hash=$(
    cd "$CONTEXT"
    sha256sum Dockerfile .dockerignore git_safe_mirror.sh |
        sha256sum |
        awk '{print $1}'
)

now=$(date +%s)
image_id=$(podman image inspect --format '{{.Id}}' "$IMAGE" 2>/dev/null || true)

built=0
record_hash=
record_id=

if [[ -r $RECORD ]]; then
    read -r built record_hash record_id <"$RECORD" || true
fi

if [[ $built =~ ^[0-9]+$ &&
      -n $image_id &&
      $image_id == "$record_id" &&
      $source_hash == "$record_hash" &&
      $now -ge $built &&
      $((now - built)) -lt $MAX_AGE ]]; then
    exit 0
fi

podman build \
    --pull=always \
    --no-cache \
    --tag "$IMAGE" \
    "$CONTEXT"

image_id=$(podman image inspect --format '{{.Id}}' "$IMAGE")

record_tmp=$(mktemp "${STATE}/build.record.XXXXXXXX")
trap 'rm -f "$record_tmp"' EXIT

printf '%s %s %s\n' \
    "$(date +%s)" \
    "$source_hash" \
    "$image_id" >"$record_tmp"

mv "$record_tmp" "$RECORD"

# After a successful replacement, the previous image normally loses its only
# tag and becomes dangling. Remove dangling images only; do not use --all or
# system prune because this user's rootless image store may serve other apps.
podman image prune --force
