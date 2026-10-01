#!/usr/bin/env bash
#
# git_safe_mirror.sh
#
# HTTPS-only bare mirrors with timestamped branch backups before a forced
# upstream update is promoted into refs/heads/*.
#
# Environment:
#   BASE_DIR    default: /mirrors
#   ORGS_FILE   default: /config/orgs.txt
#   REPOS_FILE  default: /config/repos.txt
#   GH_TOKEN    optional; GitHub API discovery only, not Git HTTPS auth
#
set -euo pipefail
umask 077

BASE_DIR=${BASE_DIR:-/mirrors}
ORGS_FILE=${ORGS_FILE:-/config/orgs.txt}
REPOS_FILE=${REPOS_FILE:-/config/repos.txt}
TS=$(date -u +%Y%m%d%H%M%S)
FAILS=0

log() {
    printf '%s | %s\n' "$(date -u +%FT%TZ)" "$*" >&2
}

read_list() {
    sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d; s/\r$//' "$1"
}

org_repos() {
    local org=$1 page=1 resp urls
    local args=(
        -fsSL
        --proto '=https'
        --proto-redir '=https'
        --connect-timeout 30
        --max-time 120
        -H 'Accept: application/vnd.github+json'
    )

    [[ $org =~ ^[A-Za-z0-9-]+$ ]] || return 1

    if command -v gh >/dev/null 2>&1 &&
       gh auth status >/dev/null 2>&1; then
        gh api --paginate \
            "orgs/$org/repos?per_page=100&type=public" \
            --jq '.[].clone_url'
        return
    fi

    [[ -z ${GH_TOKEN:-} ]] ||
        args+=(-H "Authorization: Bearer $GH_TOKEN")

    while :; do
        resp=$(
            curl "${args[@]}" \
                "https://api.github.com/orgs/$org/repos?per_page=100&page=$page&type=public"
        ) || return 1

        urls=$(jq -er '
            if type != "array" then
                error("GitHub API response is not an array")
            elif length == 0 then
                empty
            else
                .[].clone_url
            end
        ' <<<"$resp") || return 1

        [[ -n $urls ]] || break
        printf '%s\n' "$urls"
        page=$((page + 1))
    done
}

validate_url() {
    local url=$1

    case "$url" in
        https://* | ssh://* | *@*:*)
            return 0
            ;;
        file://* | /* | ./* | ../* | ~/* | "")
            return 1
            ;;
        *)
            # Plain host/path Git URL, e.g. github.com:owner/repo, is
            # intentionally not accepted because it is ambiguous and not a
            # normal explicit remote form.
            return 1
            ;;
    esac
}

repo_dir_for_url() {
    local url=$1 rest host path

    case "$url" in
        https://*)
            rest=${url#https://}
            host=${rest%%/*}
            path=${rest#*/}
            ;;

        ssh://*)
            rest=${url#ssh://}

            # Strip userinfo: "git@gitlab.example.com:2222/a/b/repo.git"
            rest=${rest#*@}

            host=${rest%%/*}
            path=${rest#*/}

            # Host-only storage key; deliberately omit optional SSH port.
            host=${host%%:*}
            ;;

        *@*:*)
            # SCP-like syntax:
            # git@gitlab.example.com:group/subgroup/repo.git
            host=${url%%:*}
            host=${host##*@}
            path=${url#*:}
            ;;

        *)
            return 1
            ;;
    esac

    path=${path%/}
    path=${path%.git}

    # Prevent empty, absolute, traversal, and repeated-slash paths.
    [[ -n $host && -n $path ]] || return 1
    [[ $host != */* && $host != . && $host != .. ]] || return 1
    [[ $path != /* && $path != *'//'*
       && $path != '.' && $path != '..'
       && $path != '../'* && $path != *'/../' && $path != *'/..' ]] || return 1

    # Path is already inside a host-specific directory. Each component is
    # retained: owner/repo and all GitLab group/subgroup components.
    printf '%s/%s/%s.git\n' "$BASE_DIR" "$host" "$path"
}

stage_and_promote_heads() {
    local dir=$1 url=$2
    local oldref newref oldoid newoid branch backup
    local staging_prefix='refs/git-mirror/staging/heads/'
    local txn

    # Remote heads are fetched into a private namespace. Existing live
    # refs/heads/* remain untouched until the update-ref transaction below.
    if ! git -C "$dir" \
        -c gc.auto=0 \
        fetch --atomic --quiet origin \
        '+refs/heads/*:refs/git-mirror/staging/heads/*'; then
        log "WARN: branch staging fetch failed: $url"
        return 1
    fi

    txn=$(mktemp "${TMPDIR:-/tmp}/git-mirror-refs.XXXXXXXX") || return 1
    trap 'rm -f "$txn"' RETURN

    {
        printf 'start\n'

        # Iterate staged remote branch tips.
        while read -r newoid newref; do
            branch=${newref#"$staging_prefix"}
            oldref="refs/heads/$branch"
            oldoid=$(git -C "$dir" rev-parse -q --verify "$oldref^{commit}" 2>/dev/null || true)

            # Existing local branch must still be at oldoid when we commit.
            # This guards against accidental concurrent mutation.
            if [[ -n $oldoid ]]; then
                if ! git -C "$dir" merge-base --is-ancestor "$oldoid" "$newoid"; then
                    backup="refs/heads/${branch}-${TS}"
                    log "FORCE PUSH on $branch: staging backup $backup"

                    # Do not silently overwrite a same-second collision.
                    printf 'create %s %s\n' "$backup" "$oldoid"
                fi

                printf 'update %s %s %s\n' "$oldref" "$newoid" "$oldoid"
            else
                printf 'create %s %s\n' "$oldref" "$newoid"
            fi

            # Remove staging reference in the same transaction.
            printf 'delete %s %s\n' "$newref" "$newoid"
        done < <(
            git -C "$dir" for-each-ref \
                --format='%(objectname) %(refname)' \
                "$staging_prefix"
        )

        # Branches removed upstream are deliberately not deleted locally:
        # no pruning means old branches remain part of this archive.
        printf 'prepare\n'
        printf 'commit\n'
    } >"$txn"

    if ! git -C "$dir" update-ref --stdin <"$txn"; then
        log "WARN: ref promotion failed; live branches were not changed: $url"
        return 1
    fi
}

sync_tags() {
    local dir=$1 url=$2

    # Tags update only after branch backup/promotion completes. No pruning,
    # and moved tags are intentionally not backed up.
    if ! git -C "$dir" -c gc.auto=0 fetch --atomic --quiet --force --tags origin; then
        log "WARN: tag fetch failed: $url"
        return 1
    fi
}

sync_repo() {
    local url=$1 dir

    if ! validate_url "$url"; then
        log "WARN: rejected repository URL: $url"
        FAILS=$((FAILS + 1))
        return
    fi

    dir=$(repo_dir_for_url "$url") || {
        log "WARN: rejected repository destination: $url"
        FAILS=$((FAILS + 1))
        return
    }

    if [[ ! -d $dir/objects ]]; then
        log "CLONE  $url"

        if ! git clone --bare --quiet "$url" "$dir"; then
            FAILS=$((FAILS + 1))
            return
        fi

        return
    fi

    log "UPDATE $url"

    if ! git -C "$dir" remote set-url origin "$url"; then
        FAILS=$((FAILS + 1))
        return
    fi

    if ! stage_and_promote_heads "$dir" "$url"; then
        FAILS=$((FAILS + 1))
        return
    fi

    if ! sync_tags "$dir" "$url"; then
        FAILS=$((FAILS + 1))
        return
    fi

    # This may write packed-refs, but only after all branch backups and
    # promotions succeeded. It does not prune branch or tag refs.
    git -C "$dir" pack-refs --all --prune >/dev/null 2>&1 || {
        log "WARN: pack-refs failed: $url"
        FAILS=$((FAILS + 1))
    }
}

declare -A seen=()

mapfile -t orgs < <(read_list "$ORGS_FILE")
mapfile -t repos < <(read_list "$REPOS_FILE")

for org in "${orgs[@]}"; do
    log "ORG    $org"

    if listing=$(org_repos "$org"); then
        while IFS= read -r url; do
            [[ -z $url ]] || repos+=("$url")
        done <<<"$listing"
    else
        log "WARN: listing failed for org $org"
        FAILS=$((FAILS + 1))
    fi
done

for url in "${repos[@]}"; do
    [[ -z ${seen[$url]:-} ]] || continue
    seen[$url]=1
    sync_repo "$url"
done

log "DONE: ${#seen[@]} repos, $FAILS failures"
(( FAILS == 0 ))
