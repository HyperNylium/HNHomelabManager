#!/usr/bin/env sh
set -eu

USER_ID="${UID:-1000}"
GROUP_ID="${GID:-1000}"
USERNAME="hnh-manager"

if [ -z "${BOT_TOKEN:-}" ]; then
  echo "[entrypoint] ERROR: BOT_TOKEN environment variable is not set." >&2
  exit 1
fi

SETTINGS_DIR="${SETTINGS_DIR:-/app/config}"
REPORTS_DIR="${REPORTS_DIR:-/data/reports}"

if ! getent group "${GROUP_ID}" >/dev/null 2>&1; then
  addgroup -g "${GROUP_ID}" -S "${USERNAME}" 2>/dev/null || true
fi

if ! getent passwd "${USER_ID}" >/dev/null 2>&1; then
  adduser -D -H -u "${USER_ID}" -G "${USERNAME}" -s /sbin/nologin "${USERNAME}" 2>/dev/null || true
fi

mkdir -p "${SETTINGS_DIR}" "${REPORTS_DIR}"
chown -R "${USER_ID}:${GROUP_ID}" /app /data 2>/dev/null || true

echo "[entrypoint] Starting bot as ${USER_ID}:${GROUP_ID}..."
echo "[entrypoint] SETTINGS_DIR=${SETTINGS_DIR}"
echo "[entrypoint] REPORTS_DIR=${REPORTS_DIR}"

exec su-exec "${USER_ID}:${GROUP_ID}" /app/.venv/bin/python /app/app.py
