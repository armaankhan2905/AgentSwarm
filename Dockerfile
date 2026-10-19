FROM node:24.13.0-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13.5-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/tmp

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates nginx \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv

WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --requirement requirements.lock

COPY backend/ backend/
COPY --from=frontend-build /build/frontend/dist/ /usr/share/nginx/html/
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/start.sh docker/start.sh
RUN addgroup --system --gid 10001 agentswarm \
    && adduser --system --uid 10001 --gid 10001 --home /nonexistent --no-create-home agentswarm \
    && mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp \
        /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp \
    && chown -R agentswarm:agentswarm /tmp/nginx /usr/share/nginx/html \
    && chmod +x docker/start.sh

USER agentswarm

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; raise SystemExit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else 1)"]

CMD ["/app/docker/start.sh"]
