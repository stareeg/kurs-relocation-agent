#!/usr/bin/env bash
# Раскатка на ВМ: fetch main → build → migrate → up → /health.
# Источник правды для Actions (script_path) и локального deploy/deploy_prod.ps1.
set -eu
cd /opt/copilot

# reset --hard, не pull: деплой-пользователь никогда не должен иметь локальных
# изменений, а автоматика не должна зависать на конфликте.
git fetch origin main
git reset --hard origin/main

compose="docker compose -f deploy/compose.yaml -f deploy/compose.prod.yaml --env-file .env"
# --env-file .env обязателен на каждый вызов (см. комментарий в compose.prod.yaml).

export GIT_SHA=$(git rev-parse --short HEAD)
echo "deploy: GIT_SHA=$GIT_SHA"
$compose build
# -T: не забирать stdin — иначе при `bash -s` / pipe остаток remote_up.sh
# съедается compose run и up -d никогда не выполняется.
$compose run --rm -T api uv run --no-sync python -m core.platform.db.migrate
# --force-recreate: иначе после build контейнеры могут остаться на старом image id
# (compose up -d молча no-op, /health зелёный — ложное DEPLOY_OK).
$compose up -d --force-recreate --remove-orphans

ok=""
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if curl -sf http://localhost:8000/health > /dev/null; then
    ok=1
    break
  fi
  sleep 5
done

if [ -z "$ok" ]; then
  echo "deploy: /health не поднялся за 60s после up -d" >&2
  $compose logs --tail=100
  exit 1
fi

echo "DEPLOY_OK $GIT_SHA"
