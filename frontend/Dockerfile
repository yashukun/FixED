# syntax=docker/dockerfile:1
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# Reverse-proxy upstreams, rendered by the nginx image's envsubst step at start.
# Locally these are Docker DNS names; on AWS set them to ECS Service Connect names.
# NGINX_ENVSUBST_FILTER ensures only ${UPSTREAM_*} are substituted (not $host etc.).
ENV UPSTREAM_GATEWAY=gateway:8000 \
    UPSTREAM_INGEST=ingest:8000 \
    UPSTREAM_SEARCH=search:8000 \
    UPSTREAM_QPAPER=qpaper:8000 \
    UPSTREAM_VIVA=viva:8000 \
    NGINX_ENVSUBST_FILTER=UPSTREAM_
COPY --from=builder /app/dist /usr/share/nginx/html
COPY default.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost/ >/dev/null 2>&1 || exit 1
# Inherit the official nginx ENTRYPOINT (/docker-entrypoint.sh) which renders the
# templates before launching nginx.
CMD ["nginx", "-g", "daemon off;"]
