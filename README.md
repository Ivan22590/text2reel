# Text2Reel — видео из текста с помощью AI

> Вставьте сценарий и получите готовый ролик для YouTube, TikTok, Reels или Instagram: AI-картинки на каждую сцену, озвучка, субтитры, музыка и переходы.

Учебный проект курса Zerocoder. Репозиторий: https://github.com/Ivan22590/text2reel. Цель: освоить AI-генерацию изображений, TTS, видеообработку через FFmpeg и построение медиапайплайнов с очередями.

## Статус

| Компонент | Статус |
|---|---|
| Документация (ТЗ, архитектура, промпты, roadmap) | ✅ готово (черновик v0.1) |
| Каркас (FastAPI, модели, Celery, React, Docker Compose, CI) | 🔄 CI зелёный, ждёт проверки на VPS |
| Этап 1: разбивка сценария на сцены (LLM через ProxyAPI) | 🔄 код и тесты готовы, ждёт прогона с ключом |
| Этап 2: генерация картинок (Fal.ai / ProxyAPI) | 🔄 код и тесты готовы, ждёт прогона с ключом |
| Этап 3: озвучка Edge TTS + субтитры SRT/ASS | 🔄 код и тесты готовы, ждёт прогона на VPS |
| Этап 4: монтаж FFmpeg, команда `render` (сценарий → MP4) | 🔄 e2e-тесты в CI зелёные, ждёт прогона с API |
| Frontend | ⏳ не начат |
| Музыка, шаблоны, брендинг | ⏳ не начат |
| Деплой и демо | ⏳ не начат |

Актуальный прогресс: [docs/ROADMAP.md](docs/ROADMAP.md). История изменений: [CHANGELOG.md](CHANGELOG.md).

## Возможности (план MVP)

- 🧠 **Разбивка сценария на сцены.** LLM делит текст на сцены и пишет визуальное описание для каждой.
- 🎨 **AI-изображения в едином стиле.** 6 стилей: реализм, аниме, акварель, комикс, 3D, минимализм.
- 🗣 **Озвучка.** Русские и английские голоса, естественные паузы, настройка темпа.
- 🎬 **Монтаж через FFmpeg.** Ken Burns, переходы `xfade`, прожжённые субтитры и SRT.
  Видео не генерируется покадрово: на каждую сцену создаётся одна картинка, и FFmpeg «оживляет» её плавным зумом и панорамой.
- 🎵 **Фоновая музыка.** Подбирается по настроению, приглушается под голос.
- 📐 **Форматы.** 9:16 (Shorts, Reels, TikTok), 16:9 (YouTube), 1:1 (Instagram).
- 🏷 **Брендинг.** Логотип, цвета, интро и аутро.
- 🖥 **Веб-интерфейс.** Редактор сцен, таймлайн, прогресс рендера в реальном времени.

## Архитектура

```
React (Vite + Ant Design) ──REST/SSE──▶ FastAPI ──▶ Redis ──▶ Celery workers
                                          │                    ├─ ai:     scene_split (LLM) · image_gen · tts
                                   SQLite / Postgres           └─ render: compose (FFmpeg) · export
                                          │
                                  storage/ (картинки, аудио, видео)
```

Подробно: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Стек

| Слой | Технологии |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy, Pydantic, Celery, Redis |
| Видео и аудио | FFmpeg 6+, Pillow, edge-tts |
| AI | LLM через [ProxyAPI](https://proxyapi.ru) (Claude Haiku 5.5, запасная DeepSeek V4.1 Flash), изображения через Fal.ai FLUX schnell или ProxyAPI |
| Frontend | React 18, TypeScript, Vite, Ant Design |
| Инфраструктура | Docker Compose, Caddy (HTTPS), GitHub Actions |

Выбор моделей и расчёт стоимости: [docs/MODELS_AND_COSTS.md](docs/MODELS_AND_COSTS.md).

## Быстрый старт

> ⚠️ Пока готов только каркас: API отвечает на `/api/health`, а фронтенд показывает статус API. Пайплайн генерации ещё не реализован.

### Требования
- Docker 24+ и Docker Compose v2
- Ключ [ProxyAPI](https://proxyapi.ru) (LLM) и ключ [Fal.ai](https://fal.ai) (изображения), если не используем картинки через ProxyAPI

### Запуск
```bash
git clone https://github.com/Ivan22590/text2reel.git
cd text2reel
cp .env.example .env        # впишите PROXYAPI_KEY и FAL_KEY
docker compose up --build
```
- Интерфейс: http://localhost:5173
- API и Swagger: http://localhost:8000/docs, проверка: http://localhost:8000/api/health

Prod: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` (см. [docs/DEPLOY.md](docs/DEPLOY.md))

### Разработка (на VPS, см. [docs/DEPLOY.md §0](docs/DEPLOY.md))
Python-зависимости ставятся только в виртуальное окружение `backend/.venv`.
```bash
# backend: тесты и линтер в .venv
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest && ruff check .
uvicorn app.main:app --reload
celery -A app.workers.celery_app worker -Q ai,render -l info   # нужен Redis

# frontend
cd frontend && npm install && npm run dev
```

### CLI
```bash
cd backend && source .venv/bin/activate
python -m app.cli smoke-llm                                   # проверить ключ ProxyAPI и модели
python -m app.cli scenes script.txt --style watercolor --format 9:16 --out sb.json   # разбить сценарий на сцены
python -m app.cli images sb.json --style watercolor --format 9:16 --out-dir out/       # картинка на каждую сцену
python -m app.cli tts sb.json --voice ru-RU-SvetlanaNeural --format 9:16 --out-dir out/  # озвучка + субтитры
python -m app.cli compose --storyboard sb.json --images out/ --narration out/narration.json --format 9:16  # монтаж

# всё сразу: сценарий → out/video.mp4 + subtitles.srt + report.json (время и ₽ по шагам)
python -m app.cli render script.txt --style watercolor --format 9:16 --voice ru-RU-SvetlanaNeural [--music track.mp3]
```

### Переменные окружения
Полный список с комментариями находится в [.env.example](.env.example). Основные:

| Переменная | Назначение |
|---|---|
| `PROXYAPI_KEY` | Ключ ProxyAPI для LLM |
| `PROXYAPI_BASE_URL` | Base URL ProxyAPI (OpenAI-совместимый) |
| `LLM_MODEL`, `LLM_FALLBACK_MODEL` | Основная и запасная модели |
| `IMAGE_PROVIDER`, `FAL_KEY` | Провайдер картинок (`fal` или `proxyapi`) и его ключ |
| `TTS_VOICE` | Голос Edge TTS по умолчанию |
| `REDIS_URL`, `DATABASE_URL`, `STORAGE_DIR` | Инфраструктура |
| `DEMO_USER`, `DEMO_PASSWORD` | Демо-доступ |

## Структура репозитория

```
backend/
  app/
    api/            REST- и SSE-эндпоинты
    models/         SQLAlchemy-модели (Project, Scene, RenderJob)
    services/       llm, scenes, images, tts, subtitles, compositor, music, templates
    workers/        Celery-задачи пайплайна
  prompts/          промпты продукта (.md), подгружаются в рантайме
  tests/
frontend/src/       pages, components (Timeline, SceneCard, ...)
assets/             music/, fonts/, logos/
templates/          JSON-шаблоны форматов
docs/               ТЗ, архитектура, промпты, сравнение, деплой, скриншоты
examples/           примеры готовых видео
```

## Документация

| Документ | Содержание |
|---|---|
| [docs/TZ.md](docs/TZ.md) | Техническое задание: цели, KPI, границы, требования |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Этапы и прогресс |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Компоненты, пайплайн, API, данные, FFmpeg |
| [docs/MODELS_AND_COSTS.md](docs/MODELS_AND_COSTS.md) | Выбор моделей, ProxyAPI, стоимость ролика |
| [docs/PROMPTS.md](docs/PROMPTS.md) | Библиотека промптов (продукт и разработка) |
| [docs/COMPETITORS.md](docs/COMPETITORS.md) | Сравнение с конкурентами |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Развёртывание на сервере |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | Сценарий видеопрезентации, список скриншотов и примеров |
| [docs/METRICS.md](docs/METRICS.md) | Замеры KPI |
| [docs/SUBMISSION_CHECKLIST.md](docs/SUBMISSION_CHECKLIST.md) | Чек-лист сдачи по критериям |

## Демо

- Демо-стенд: _будет добавлен_
- Примеры видео: [examples/](examples/)
- Скриншоты: [docs/screenshots/](docs/screenshots/)

## Благодарности и лицензии

- Модули озвучки и субтитров частично адаптированы из [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) (MIT). Подробности в [NOTICE](NOTICE).
- Музыка и шрифты под свободными лицензиями, список в `assets/*/LICENSES.md`.

Лицензия проекта: [MIT](LICENSE).
