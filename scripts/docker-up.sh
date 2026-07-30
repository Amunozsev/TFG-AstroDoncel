#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker was not found. Install Docker Engine with the Compose plugin first." >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed but its engine is not running or this user lacks permission." >&2
    exit 1
fi

if [ ! -f .env ]; then
    if command -v openssl >/dev/null 2>&1; then
        password=$(openssl rand -hex 24)
    else
        password=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
    fi
    temporary_env=$(mktemp "${TMPDIR:-/tmp}/astrodoncel-env.XXXXXX")
    trap 'rm -f "$temporary_env"' EXIT HUP INT TERM
    sed "s/change-this-password/$password/g" .env.example > "$temporary_env"
    mv "$temporary_env" .env
    trap - EXIT HUP INT TERM
    chmod 600 .env
    echo "Created .env with a random PostgreSQL password."
fi

if grep -q "change-this-password" .env; then
    echo ".env still contains the example password. Replace both occurrences before deployment." >&2
    exit 1
fi

mkdir -p data/archive
docker compose config --quiet
docker compose up --build -d

port_line=$(docker compose port web 80 | sed -n '1p')
web_port=${port_line##*:}
ready_url="http://127.0.0.1:${web_port}/ready"

attempt=1
while [ "$attempt" -le 60 ]; do
    if command -v curl >/dev/null 2>&1; then
        if curl --fail --silent "$ready_url" | grep -q '"status":"ok"'; then
            break
        fi
    elif wget -qO- "$ready_url" 2>/dev/null | grep -q '"status":"ok"'; then
        break
    fi
    attempt=$((attempt + 1))
    sleep 2
done

if [ "$attempt" -gt 60 ]; then
    docker compose ps
    docker compose logs --tail 100
    echo "The stack did not become ready at $ready_url." >&2
    exit 1
fi

docker compose ps
printf '\nAstroDoncel is ready:\n'
printf '  Portal:  http://127.0.0.1:%s\n' "$web_port"
printf '  API:     http://127.0.0.1:%s/docs\n' "$web_port"
printf '  Status:  %s\n' "$ready_url"
