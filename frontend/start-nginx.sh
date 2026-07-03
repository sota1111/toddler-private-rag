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

# SOT-1494: Self-host the Firebase Auth helper so Google sign-in popups work under browser
# storage partitioning. When FIREBASE_AUTH_DOMAIN is set, reverse-proxy /__/auth/ and
# /__/firebase/ to the real Firebase auth domain (*.firebaseapp.com); the frontend sets its
# own origin as authDomain so the popup handler becomes same-origin with the app. When unset,
# the snippet is empty so nginx still starts and only Google sign-in stays unconfigured.
mkdir -p /etc/nginx/snippets
FIREBASE_AUTH_DOMAIN="$(printf '%s' "${FIREBASE_AUTH_DOMAIN:-}" | sed -E 's#^https?://##; s#/.*$##')"
if [ -n "$FIREBASE_AUTH_DOMAIN" ]; then
  cat > /etc/nginx/snippets/firebase-auth.conf <<EOF
location /__/ {
    proxy_pass https://${FIREBASE_AUTH_DOMAIN};
    proxy_http_version 1.1;
    proxy_set_header Host ${FIREBASE_AUTH_DOMAIN};
    proxy_ssl_server_name on;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Real-IP \$remote_addr;
}
EOF
  echo "start-nginx: Firebase auth self-host proxy /__/ -> https://${FIREBASE_AUTH_DOMAIN}"
else
  : > /etc/nginx/snippets/firebase-auth.conf
  echo "start-nginx: FIREBASE_AUTH_DOMAIN unset; Google sign-in self-host proxy disabled"
fi

echo "start-nginx: proxying /api -> ${BACKEND_URL} (Host ${BACKEND_HOST}); upload -> ${UPLOAD_URL} (Host ${UPLOAD_HOST})"
exec nginx -g 'daemon off;'
