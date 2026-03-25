# syntax=docker/dockerfile:1.7
# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Layer-cache npm install separately from source
COPY package*.json ./
RUN npm ci --ignore-scripts

COPY . .
RUN npm run build

# Create a runtime env template that entrypoint.sh populates via envsubst.
# The Vue app reads window._env_.VITE_API_URL for non-relative API origins.
RUN printf 'window._env_ = { VITE_API_URL: "${VITE_API_URL}" };\n' \
    > /app/dist/env.js

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# gettext provides envsubst; curl is needed for health check
RUN apk add --no-cache gettext curl \
    && rm -f /etc/nginx/conf.d/default.conf

# Static assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx site config (SPA routing, security headers, /health)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Runtime entrypoint: envsubst → env.js, then start nginx
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Allow nginx user (101) to write env.js at runtime
RUN chown -R nginx:nginx /usr/share/nginx/html \
    && chown nginx:nginx /docker-entrypoint.sh

EXPOSE 80

# curl /health — matches the dedicated health location in nginx.conf
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost/health || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
