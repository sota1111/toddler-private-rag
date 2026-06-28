#!/bin/sh
set -e

if [ -z "${BACKEND_URL:-}" ]; then
  echo "FATAL: BACKEND_URL env var is required (backend Cloud Run URL, e.g. https://xxx.a.run.app)" >&2
  exit 1
fi

# Derive the bare host for the upstream Host header / SNI (Cloud Run routes by Host).
BACKEND_HOST="$(printf '%s' "$BACKEND_URL" | sed -E 's#^https?://##; s#/.*$##')"

# SOT-1322: photo upload goes to a separate lightweight upload service. Defaults to BACKEND_URL when
# UPLOAD_URL is unset, so behavior is unchanged until the upload service is deployed/configured.
UPLOAD_URL="${UPLOAD_URL:-$BACKEND_URL}"
UPLOAD_HOST="$(printf '%s' "$UPLOAD_URL" | sed -E 's#^https?://##; s#/.*$##')"

export BACKEND_URL BACKEND_HOST UPLOAD_URL UPLOAD_HOST

# Only substitute our own vars; leave nginx's own $variables intact.
envsubst '${BACKEND_URL} ${BACKEND_HOST} ${UPLOAD_URL} ${UPLOAD_HOST}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

echo "start-nginx: proxying /api -> ${BACKEND_URL} (Host ${BACKEND_HOST}); upload -> ${UPLOAD_URL} (Host ${UPLOAD_HOST})"
exec nginx -g 'daemon off;'
