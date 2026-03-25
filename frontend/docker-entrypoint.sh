#!/bin/sh
# Inject runtime environment variables into the SPA's env.js before nginx starts.
# Any variable listed in the envsubst call below will be substituted;
# unset variables are replaced with an empty string.
set -eu

ENV_JS=/usr/share/nginx/html/env.js

# Substitute ${VITE_API_URL} in the template (created during docker build).
# We write to a temp file first to avoid a half-written file on errors.
VITE_API_URL="${VITE_API_URL:-}" \
    envsubst '${VITE_API_URL}' < "${ENV_JS}" > "${ENV_JS}.tmp"
mv "${ENV_JS}.tmp" "${ENV_JS}"

echo "env.js written (VITE_API_URL=${VITE_API_URL:-<empty>})"

exec nginx -g 'daemon off;'
