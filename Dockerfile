FROM docker.io/library/alpine:latest

RUN apk add --no-cache \
        bash \
        ca-certificates \
        curl \
        git \
        github-cli \
        jq

COPY git_safe_mirror.sh /usr/local/bin/git_safe_mirror.sh

RUN bash -n /usr/local/bin/git_safe_mirror.sh

USER 1000:1000
WORKDIR /mirrors

ENTRYPOINT ["/bin/bash", "/usr/local/bin/git_safe_mirror.sh"]
