#!/usr/bin/env bash
# Обновить бота на сервере после изменений в репозитории.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull
docker compose up -d --build
docker compose logs --tail 15 bot
