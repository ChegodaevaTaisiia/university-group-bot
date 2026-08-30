#!/usr/bin/env bash
# Бэкап базы бота. В cron: 0 4 * * * /root/group-bot/deploy/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p backups
STAMP=$(date +%F-%H%M)
sqlite3 data/bot.sqlite ".backup 'backups/bot-${STAMP}.sqlite'"

# оставляем последние 14 копий
ls -1t backups/bot-*.sqlite | tail -n +15 | xargs -r rm --
echo "backup: backups/bot-${STAMP}.sqlite"
