#!/bin/sh
# Ежедневный дамп прод-БД.
# Ставится в cron деплой-пользователя на ВМ, не в compose — расписание раз в сутки не тянет
# отдельного долгоживущего сервиса.
set -eu
cd "$(dirname "$0")/.."

ts=$(date +%Y%m%d_%H%M%S)
mkdir -p backups

# --env-file обязателен (см. комментарий в compose.prod.yaml) — без него Compose резолвит
# ${VAR} относительно каталога deploy/, не корня репо, и молча теряет .env.
docker compose -f deploy/compose.yaml -f deploy/compose.prod.yaml --env-file .env exec -T postgres \
    pg_dump -U "${POSTGRES_USER:-copilot}" "${POSTGRES_DB:-copilot}" | gzip > "backups/pg_${ts}.sql.gz"

find backups -name 'pg_*.sql.gz' -mtime +7 -delete
