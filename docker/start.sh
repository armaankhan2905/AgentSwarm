#!/bin/sh
set -eu

if [ "${AUTH_MODE:-local}" = "local" ] && [ "${ALLOW_INSECURE_DOCKER_LOCAL_AUTH:-0}" != "1" ]; then
    echo "AUTH_MODE=local is disabled in the public combined Docker image. Use AUTH_MODE=supabase, or explicitly set ALLOW_INSECURE_DOCKER_LOCAL_AUTH=1 for isolated development only." >&2
    exit 1
fi

uvicorn app.main:app --app-dir /app/backend --host 127.0.0.1 --port 8000 &
api_pid=$!

cleanup() {
    kill "$api_pid" 2>/dev/null || true
    wait "$api_pid" 2>/dev/null || true
}

trap cleanup INT TERM EXIT
exec nginx -g 'daemon off;'
