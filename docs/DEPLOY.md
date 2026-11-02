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
cp .env.example .env && nano .env
```
В `.env` для prod задать: `APP_ENV=prod`, `DOMAIN` (A-запись домена должна смотреть на сервер), `SECRET_KEY` (длинная случайная строка), `POSTGRES_PASSWORD`, `DEMO_USER` и `DEMO_PASSWORD`, `PROXYAPI_KEY`, `FAL_KEY`. **Комментарии в `.env` только на отдельных строках**: `KEY=значение # комментарий` docker compose и Python читают по-разному (пустой ключ превращался в непустой).

```bash
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$COMPOSE up -d --build          # собирает образы, применяет миграции, поднимает всё
scripts/smoke_stack.sh https://ВАШ_ДОМЕН https://ВАШ_ДОМЕН demo ПАРОЛЬ   # проверка стека
```
Порядок запуска (зависимости описаны в compose): `postgres` (healthcheck) → `migrate` (разово: `alembic upgrade head`) → `api`, `worker-ai`, `worker-render`, `beat` → `caddy` (после healthcheck API). Фронтенд собирается разово в общий том, который раздаёт Caddy.

Те же два варианта стека (dev на SQLite и prod на PostgreSQL с Caddy и HTTPS) проверяются в GitHub Actions при каждом push: задания `stack (docker compose, dev)` и `stack (docker compose, prod ...)` поднимают их и гонят `scripts/smoke_stack.sh`.

## 3. Сервисы в prod
| Сервис | Назначение | Ресурсы |
|---|---|---|
| `caddy` | Reverse proxy + автоматический HTTPS (Let's Encrypt; для `localhost` самоподписанный), статика фронтенда, без буферизации SSE | — |
| `api` | FastAPI (uvicorn, 2 процесса), healthcheck `/api/health` | 0,5 CPU |
| `worker-ai` | Celery `-Q ai -c 4`: LLM, картинки, озвучка | 0,5 CPU |
| `worker-render` | Celery `-Q render -c 2`: FFmpeg | 2–3 CPU |
| `beat` | Расписание Celery: ежедневная очистка в 03:15 UTC | — |
| `migrate` | Разовая задача `alembic upgrade head` перед запуском остальных | — |
| `redis` | Брокер очередей | — |
| `postgres` | БД, healthcheck `pg_isready` | — |

В prod код берётся из образа, исходники с хоста не монтируются. Тома: `pgdata` (БД), `storage` (файлы проектов и кэш), `frontend_dist`, `caddy_data` (сертификаты).

## 4. Обновление
```bash
cd /opt/text2reel && git pull
$COMPOSE up -d --build          # новая версия миграций применится сервисом migrate сама
```
Миграции лежат в `backend/migrations/versions`. Новую создают после правки моделей: `alembic revision --autogenerate -m "..."`; тест `tests/test_migrations.py` падает, если модели и миграции разошлись.

## 5. Бэкап и обслуживание
- БД: ежедневный `$COMPOSE exec -T postgres pg_dump -U text2reel text2reel | gzip > /opt/backups/db-$(date +%F).sql.gz` по cron, хранение 7 дней.
- Файлы: ежедневная задача Celery beat (`app.workers.tasks.ai.cleanup`) удаляет проекты, к которым не прикасались `STORAGE_TTL_DAYS` дней (по умолчанию 7), старый кэш и возвращает в рабочее состояние задачи, зависшие после падения воркера. Вручную: `$COMPOSE exec api python -m app.cli cleanup`.
- **Перед сдачей поставить `STORAGE_TTL_DAYS=0`** (очистка отключена, зависшие задачи всё равно восстанавливаются), иначе примеры проектов для проверяющих исчезнут через неделю.
- Логи: `$COMPOSE logs -f --tail=200 worker-render`.
- Статистика и KPI из БД: `$COMPOSE exec api python -m app.cli stats`.

## 6. Демо-доступ
- Логин и пароль из `DEMO_USER` / `DEMO_PASSWORD`, указываются в README и в сдаче.
- Лимит `DEMO_MAX_PROJECTS_PER_DAY` защищает бюджет API.
- Перед проверкой заранее создать 5 примеров проектов, чтобы проверяющий сразу видел результат.

## 7. Если что-то не работает
| Симптом | Что смотреть |
|---|---|
| Сайт не открывается по HTTPS | `$COMPOSE logs caddy`; A-запись домена, порты 80 и 443 открыты (`ufw`) |
| `api` не стартует | `$COMPOSE logs migrate api`: пароль PostgreSQL, миграции |
| Задача не уходит из «в обработке» | `$COMPOSE logs worker-ai worker-render`; через 2 часа ежедневная очистка вернёт проект в рабочее состояние |
| «PROXYAPI_KEY is not set» | ключ не попал в `.env` (проверить, что нет комментария в той же строке) |
| Рендер дольше ожидаемого | `$COMPOSE exec api python -m app.cli stats`, [METRICS.md](METRICS.md); кнопка «Быстрый предпросмотр» собирает 480p за секунды |
