#!/bin/sh
set -eu

auth_mode=${AUTH_MODE:-local}
allow_local_auth=${ALLOW_INSECURE_DOCKER_LOCAL_AUTH:-0}
app_env=${APP_ENV:-production}
deployment_scope=${DEPLOYMENT_SCOPE:-shared}

case "$auth_mode" in
    local|supabase) ;;
    *)
        echo "AUTH_MODE must be local or supabase" >&2
        exit 1
        ;;
esac

case "$allow_local_auth" in
    0|1) ;;
    *)
        echo "ALLOW_INSECURE_DOCKER_LOCAL_AUTH must be 0 or 1" >&2
        exit 1
        ;;
esac

if [ "$auth_mode" = "local" ] && {
    [ "$allow_local_auth" != "1" ] ||
    [ "$app_env" != "development" ] ||
    [ "$deployment_scope" != "isolated" ];
}; then
    echo "AUTH_MODE=local requires ALLOW_INSECURE_DOCKER_LOCAL_AUTH=1, APP_ENV=development, and DEPLOYMENT_SCOPE=isolated" >&2
    echo "Use AUTH_MODE=supabase for shared or production deployments." >&2
    exit 1
fi

if [ "$auth_mode" = "supabase" ] && [ "$allow_local_auth" = "1" ]; then
    echo "ALLOW_INSECURE_DOCKER_LOCAL_AUTH=1 is only valid with isolated development local auth" >&2
    exit 1
fi

uvicorn app.main:app --app-dir /app/backend --host 127.0.0.1 --port 8000 &
api_pid=$!

cleanup() {
    kill "$api_pid" 2>/dev/null || true
    wait "$api_pid" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

ready=0
attempt=0
while [ "$attempt" -lt 60 ]; do
    if ! kill -0 "$api_pid" 2>/dev/null; then
        echo "The API process exited before becoming ready" >&2
        exit 1
    fi
    if python -c 'import urllib.request; response = urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2); raise SystemExit(0 if response.status == 200 else 1)' 2>/dev/null; then
        ready=1
        break
    fi
    attempt=$((attempt + 1))
    sleep 1
done

if [ "$ready" != "1" ]; then
    echo "The API did not become ready within 60 seconds" >&2
    exit 1
fi

nginx -g 'daemon off;' &
nginx_pid=$!

cleanup() {
    kill "$nginx_pid" 2>/dev/null || true
    kill "$api_pid" 2>/dev/null || true
    wait "$nginx_pid" 2>/dev/null || true
    wait "$api_pid" 2>/dev/null || true
}

trap cleanup INT TERM EXIT
wait "$nginx_pid"
