#!/usr/bin/env bash
# Deploy the Label Verification Service to the app host.
#
# Run on the server as root:  /var/www/ttb-build/deploy/deploy.sh
# Pulls, rebuilds both sides, restarts the API, and gates on health — rolling
# back to the previous commit if the new one does not come up.
set -euo pipefail

APP=/var/www/ttb-build
PORT=8020
BASE=/ttb-build

cd "$APP"
PREVIOUS=$(git rev-parse HEAD)
echo "==> at $PREVIOUS"

git fetch --quiet origin
git reset --hard --quiet origin/main
echo "==> now $(git rev-parse --short HEAD)  $(git log -1 --pretty=%s)"

echo "==> api"
cd "$APP/api"
uv sync --quiet

echo "==> web"
cd "$APP/web"
npm ci --silent --legacy-peer-deps
PUBLIC_BASE_PATH="$BASE/" npm run build --silent

echo "==> restart"
systemctl restart ttb-build

# Health gate. The API rewrites its CSV mirror and touches the image directory
# on boot, so a green /api/health means storage is genuinely writable.
for i in $(seq 1 20); do
	if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
		echo "==> healthy after ${i}s"
		curl -fsS "http://127.0.0.1:$PORT/api/health"
		echo
		exit 0
	fi
	sleep 1
done

echo "!! unhealthy after 20s — rolling back to $PREVIOUS" >&2
git reset --hard --quiet "$PREVIOUS"
cd "$APP/api" && uv sync --quiet
systemctl restart ttb-build
exit 1
