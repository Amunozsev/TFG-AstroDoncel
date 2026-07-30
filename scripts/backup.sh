#!/usr/bin/env sh
set -eu

database_only=0
if [ "${1:-}" = "--database-only" ]; then
    database_only=1
elif [ "$#" -gt 0 ]; then
    echo "Usage: $0 [--database-only]" >&2
    exit 2
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

timestamp=$(date -u +%Y%m%d-%H%M%S)
backup_dir="$repo_root/backups/$timestamp"
mkdir -p "$backup_dir"

docker compose exec -T db sh -c \
    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --file=/tmp/astrodoncel.dump'
docker compose cp db:/tmp/astrodoncel.dump "$backup_dir/postgres.dump"
docker compose exec -T db rm -f /tmp/astrodoncel.dump

if [ "$database_only" -eq 0 ]; then
    docker compose exec -T api tar -czf /tmp/app-data.tar.gz -C /data .
    docker compose cp api:/tmp/app-data.tar.gz "$backup_dir/app-data.tar.gz"
    docker compose exec -T api rm -f /tmp/app-data.tar.gz
fi

(
    cd "$backup_dir"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum postgres.dump
        if [ -f app-data.tar.gz ]; then
            sha256sum app-data.tar.gz
        fi
    else
        shasum -a 256 postgres.dump
        if [ -f app-data.tar.gz ]; then
            shasum -a 256 app-data.tar.gz
        fi
    fi
) > "$backup_dir/SHA256SUMS.txt"

echo "Backup created at $backup_dir"
