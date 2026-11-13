#!/usr/bin/env bash

#   cd ~/motiv-case && bash deploy/autoupdate.sh [ветка] [минуты]

BRANCH=${1:-main}
MINUTES=${2:-5}
export COMPOSE_BAKE=false
cd "$(dirname "$0")/.." || exit 1

log() { echo "[$(date +%H:%M:%S)] $*"; }

deploy() {
    if [ "$1" = reset ]; then
        log "Изменился init_scripts — пересоздаю базу"
        docker compose down -v
    elses
        docker compose down
    fi
    if docker compose up -d --build; then log "Готово: http://localhost:82"; else log "ОШИБКА сборки — смотрите вывод выше"; fi
}

git fetch -q origin "$BRANCH"
git reset -q --hard "origin/$BRANCH"
log "Первый запуск, $BRANCH на $(git rev-parse --short HEAD)"
deploy

while true; do
    sleep $((MINUTES * 60))
    git fetch -q origin "$BRANCH"
    old=$(git rev-parse HEAD)
    new=$(git rev-parse "origin/$BRANCH")
    if [ "$old" = "$new" ]; then log "Изменений нет"; continue; fi

    log "Новые коммиты:"
    git log --oneline "$old..$new"
    changed=$(git diff --name-only "$old" "$new")
    git reset -q --hard "$new"
    if echo "$changed" | grep -q '^init_scripts/'; then deploy reset; else deploy; fi
done
