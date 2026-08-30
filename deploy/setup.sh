#!/usr/bin/env bash
# Первичная настройка сервера Ubuntu 22.04/24.04 под бота: Docker + фаервол.
# Запускать от root:  bash deploy/setup.sh
set -euo pipefail

echo ">> Обновление пакетов"
apt-get update -y
apt-get install -y ca-certificates curl git ufw sqlite3

echo ">> Установка Docker"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker

echo ">> Фаервол: разрешаем только SSH"
ufw allow OpenSSH
ufw --force enable

echo ">> Готово. Дальше:"
echo "   git clone <репозиторий> group-bot && cd group-bot"
echo "   cp .env.example .env && nano .env   # BOT_TOKEN, ADMIN_IDS, SUPERGROUP_ID, RASP_URL, ключ ИИ"
echo "   docker compose up -d --build"
echo "   docker compose logs -f bot"
