# CLAUDE.md — подсказки для AI-ассистента

## Проект
Text2Reel — учебный проект Zerocoder: платформа «текстовый сценарий → видео» (AI-картинки, TTS, субтитры, музыка, FFmpeg).
Задание: `description.md`, критерии оценки: `criteria.md`. Главные документы: `docs/TZ.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`.

## Ключевые решения (не менять без согласования с пользователем)
- Свой код: FastAPI + Celery/Redis + React/TS + FFmpeg.
- Модули TTS и субтитров можно адаптировать из MoneyPrinterTurbo (MIT): в заголовке файла указать источник, обновить `NOTICE`.
- Код story-flicks НЕ копировать: у него нет лицензии.
- LLM только через ProxyAPI (`services/llm/client.py`, OpenAI-совместимый SDK, `PROXYAPI_BASE_URL`, `PROXYAPI_KEY`). Основная модель Claude Haiku 5.5, запасная DeepSeek V4.1 Flash. Preview-модели не использовать.
- Картинки: адаптер с `IMAGE_PROVIDER` (`fal` | `proxyapi`). TTS: Edge TTS.
- Бюджет API ≈ $5–20. Не делать лишних платных вызовов в тестах (мокать клиентов).

## Окружение
- Репозиторий: https://github.com/Ivan22590/text2reel (публичный).
- Разработка и демо идут на VPS (`docs/DEPLOY.md` §0). На старой локальной машине нет Docker, ffmpeg, pip и venv: там только редактируем файлы и собираем frontend (Node 22 есть).
- Python-зависимости только в `backend/.venv`. Сервисы запускаются в Docker Compose.
- Пока VPS нет, источник правды для Python-тестов и линтера — GitHub Actions CI.

## Правило синхронизации документации (обязательно)
При ЛЮБОЙ правке плана или кода в том же шаге обновить затронутые документы:

| Что изменилось | Что обновить |
|---|---|
| Завершена или начата задача этапа | `docs/ROADMAP.md` (чекбоксы), `CHANGELOG.md` |
| Запуск, зависимости, статус, переменные | `README.md`, `.env.example` |
| API, модели данных, пайплайн, FFmpeg | `docs/ARCHITECTURE.md` |
| Требования, границы, KPI | `docs/TZ.md` (повысить версию) |
| Модели, провайдеры, цены | `docs/MODELS_AND_COSTS.md` (+ таблица истории) |
| Любой промпт продукта (`backend/prompts/*.md`) | `docs/PROMPTS.md` (часть A), поднять `version` |
| Новый промпт пользователя при разработке | `docs/PROMPTS.md` (часть B, дословно) |
| Деплой | `docs/DEPLOY.md` |
| Замеры KPI | `docs/METRICS.md` |
| Артефакты сдачи | `docs/SUBMISSION_CHECKLIST.md` |

## Команды (целевые, актуализировать по мере появления кода)
```bash
docker compose up --build                     # весь стек
cd backend && source .venv/bin/activate && pytest   # тесты backend (в .venv)
cd backend && ruff check . && ruff format .   # линт
cd frontend && npm run dev | npm run lint
python -m app.cli render script.txt --style anime --format 9:16   # пайплайн из CLI
```

## Соглашения
- Документация и UI на русском, код, идентификаторы и коммиты на английском.
- Промпты продукта хранятся только в `backend/prompts/*.md`, без хардкода в коде.
- Шаги пайплайна идемпотентны и кэшируются по hash входа.
- Секреты только в `.env`. `.env`, `storage/`, большие медиа в git не коммитить.
- Коммиты и push только по просьбе пользователя.
