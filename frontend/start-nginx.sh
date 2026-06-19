#!/bin/sh
set -e

if [ -z "${BACKEND_URL:-}" ]; then
  echo "FATAL: BACKEND_URL env var is required (backend Cloud Run URL, e.g. https://xxx.a.run.app)" >&2
  exit 1
fi

# Derive the bare host for the upstream Host header / SNI (Cloud Run routes by Host).
BACKEND_HOST="$(printf '%s' "$BACKEND_URL" | sed -E 's#^https?://##; s#/.*$##')"
export BACKEND_URL BACKEND_HOST

# Only substitute our two vars; leave nginx's own $variables intact.
envsubst '${BACKEND_URL} ${BACKEND_HOST}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

echo "start-nginx: proxying /api -> ${BACKEND_URL} (Host ${BACKEND_HOST})"
exec nginx -g 'daemon off;'
