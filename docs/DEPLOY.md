# Деплой

> Целевая инструкция. Уточняется на этапе 7.

## 0. Dev-окружение на VPS (решение от 2026-11-02)
Разработка идёт сразу на VPS, который потом становится демо-стендом. Причина: на локальной машине нет Docker, ffmpeg, python3-venv и sudo, а ресурсов мало.

**Какой сервер взять:**
- 4 vCPU, 8 ГБ RAM, 80 ГБ NVMe, Ubuntu 24.04, публичный IPv4, оплата в рублях.
- Подходят, например, Timeweb Cloud, Selectel или REG.RU Cloud. Цены и наличие сверить на сайте.
- GPU не нужен: картинки генерируются по API, видео кодируется на CPU.

**Первая настройка (с root):**
```bash
adduser dev && usermod -aG sudo dev               # рабочий пользователь
rsync -a ~/.ssh /home/dev/ && chown -R dev:dev /home/dev/.ssh   # вход по SSH-ключу
ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable
apt update && apt install -y git python3.12-venv python3-pip ffmpeg
curl -fsSL https://get.docker.com | sh && usermod -aG docker dev
```

**Проект и инструменты (под пользователем `dev`):**
```bash
git clone https://github.com/Ivan22590/text2reel.git ~/text2reel && cd ~/text2reel
cp .env.example .env && nano .env                 # PROXYAPI_KEY, FAL_KEY
python3 -m venv backend/.venv && backend/.venv/bin/pip install -e "backend[dev]"   # тесты и линтер
docker compose up --build                          # весь стек
npm install -g @anthropic-ai/claude-code           # Claude Code на сервере (нужен Node 18+)
```
Python-зависимости ставятся только в `backend/.venv`, системный Python не трогаем. Сервисы работают в контейнерах.

Пока VPS нет, тесты Python запускаются в GitHub Actions (`.github/workflows/ci.yml`).

## 1. Сервер
- VPS: 4 vCPU, 8 GB RAM, 80 GB SSD, Ubuntu 24.04. Подойдёт любой провайдер с оплатой в рублях.
- Домен с A-записью на IP сервера (например, `text2reel.example.ru`).
- Открытые порты: 22, 80, 443.

## 2. Установка
```bash
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# Проект
git clone https://github.com/Ivan22590/text2reel.git /opt/text2reel
cd /opt/text2reel
cp .env.example .env && nano .env      # ключи, DOMAIN, DEMO_USER/DEMO_PASSWORD, APP_ENV=prod
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## 3. Сервисы в prod
| Сервис | Назначение | Ресурсы |
|---|---|---|
| `caddy` | Reverse proxy + автоматический HTTPS (Let's Encrypt), раздача статики фронтенда | — |
| `api` | FastAPI (uvicorn, 2 воркера) | 0,5 CPU |
| `worker-ai` | Celery `-Q ai -c 4` | 0,5 CPU |
| `worker-render` | Celery `-Q render -c 2` | 2–3 CPU |
| `redis` | Брокер и pub/sub | — |
| `postgres` | БД | — |

Caddyfile (черновик):
```
{$DOMAIN} {
  encode gzip
  handle /api/* { reverse_proxy api:8000 }
  handle { root * /srv/frontend; try_files {path} /index.html; file_server }
}
```

## 4. Обновление
```bash
cd /opt/text2reel && git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose exec api alembic upgrade head
```

## 5. Бэкап и обслуживание
- БД: ежедневный `pg_dump` по cron в `/opt/backups`, хранение 7 дней.
- Файлы: задача Celery beat удаляет проекты старше `STORAGE_TTL_DAYS` (по умолчанию 7).
- Логи: `docker compose logs -f --tail=200 worker-render`.

## 6. Демо-доступ
- Логин и пароль из `DEMO_USER` / `DEMO_PASSWORD`, указываются в README и в сдаче.
- Лимит `DEMO_MAX_PROJECTS_PER_DAY` защищает бюджет API.
- Перед проверкой заранее создать 5 примеров проектов, чтобы проверяющий сразу видел результат.
