#!/bin/sh
# Install or update calsd as a systemd user service (TOOLS.md 2.3).
#
#   deploy/deploy.sh          # newest v* tag
#   deploy/deploy.sh v1.4.0   # a specific tag
#
# Settings come from ~/.config/calsd/env:
#   CALSD_DATA_REPO   the data repository to clone and push to (required)
#   CALSD_DEPLOY_KEY  ssh key with write access to it (optional)
#   CALSD_HOST        address to listen on (default 127.0.0.1)
#   CALSD_PORT        port (default 8642)
#   CALSD_APP_REPO    where to fetch these tools (default: this repository)
#
# ~/.local/share/calsd/app   these tools, checked out at a tag
# ~/.local/share/calsd/data  the clone calsd edits and pushes from
set -eu
ENV=$HOME/.config/calsd/env
[ -f "$ENV" ] || { echo "deploy.sh: create $ENV first (see TOOLS.md 2.3)" >&2; exit 1; }
. "$ENV"
: "${CALSD_DATA_REPO:?is not set in $ENV}"
APP_REPO=${CALSD_APP_REPO:-https://github.com/jgarofoli/calendar.git}
BASE=$HOME/.local/share/calsd

mkdir -p "$BASE"
# A checkout of some other repository (an older layout) is replaced.
if [ -d "$BASE/app/.git" ] && [ "$(git -C "$BASE/app" remote get-url origin)" != "$APP_REPO" ]; then
    rm -rf "$BASE/app"
fi
[ -d "$BASE/app/.git" ] || git clone -q "$APP_REPO" "$BASE/app"
if [ ! -d "$BASE/data/.git" ]; then
    git clone -q "$CALSD_DATA_REPO" "$BASE/data"
fi
if [ -n "${CALSD_DEPLOY_KEY:-}" ]; then
    KEY=$(eval echo "$CALSD_DEPLOY_KEY")
    SSH="ssh -i $KEY -o IdentitiesOnly=yes"
    git -C "$BASE/data" config core.sshCommand "$SSH"
    if ! $SSH -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
        echo "warning: $KEY is not accepted by GitHub yet; calsd cannot push until"
        echo "it is added to the data repository as a deploy key with write access."
    fi
fi
git -C "$BASE/app" fetch -q --tags origin
TAG=${1:-$(git -C "$BASE/app" tag --list 'v*' --sort=-v:refname | head -n 1)}
git -C "$BASE/app" -c advice.detachedHead=false checkout -q "$TAG"

mkdir -p "$HOME/.config/systemd/user"
cp "$BASE/app/deploy/calsd.service" "$HOME/.config/systemd/user/calsd.service"
systemctl --user daemon-reload
systemctl --user enable -q calsd.service
systemctl --user restart calsd.service
echo "calsd $TAG: http://${CALSD_HOST:-127.0.0.1}:${CALSD_PORT:-8642}/"
