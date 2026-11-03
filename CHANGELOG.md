# Changelog

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии по [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Added
- 2026-11-02: Комплект документации: ТЗ, README, ROADMAP, ARCHITECTURE, MODELS_AND_COSTS, PROMPTS, COMPETITORS, DEPLOY, DEMO_SCRIPT, METRICS, SUBMISSION_CHECKLIST.
- 2026-11-02: Черновики продуктовых промптов в `backend/prompts/` (scene_split, scene_regenerate, image_prompt, style_presets, music_mood).
- 2026-11-02: `CLAUDE.md` с правилом синхронизации документации, `.env.example`, `.gitignore`, LICENSE, NOTICE.
- 2026-11-02: Каркас: backend (FastAPI, pydantic-settings, SQLAlchemy-модели Project/Scene/RenderJob, загрузчик промптов, Celery с очередями `ai`/`render`, `/api/health`, тесты), frontend (Vite + React + TS + AntD), `docker-compose.yml`, `docker-compose.prod.yml`, `Caddyfile`, CI в GitHub Actions.
- 2026-11-02: Этап 1: LLM-клиент ProxyAPI (повторы, запасная модель, учёт токенов и ₽), сервис `split_script` (Pydantic-схема, проверка неизменности текста, retry-промпт, кэш), пресеты стилей, CLI `llm-models`/`smoke-llm`/`scenes`, тесты с моком LLM.
- 2026-11-02: Этап 2: адаптеры картинок Fal.ai (FLUX schnell) и ProxyAPI, сборка промптов со style bible, общий seed, кадрирование cover/blur под 9:16/16:9/1:1, параллельная генерация с повторами и кэшем, CLI `images`, тесты. Зависимость `pillow`.
- 2026-11-02: Этап 3: озвучка Edge TTS (тайминги слов, нормализация текста, повторы, кэш), субтитры SRT и ASS (пунктуация из исходного текста, фразы, karaoke-подсветка для 9:16), 5 голосов, CLI `tts`. Зависимость `edge-tts`. Части кода адаптированы из MoneyPrinterTurbo (MIT), см. NOTICE.
- 2026-11-02: Этап 4: compositor на FFmpeg (таймлайн с паузами, Ken Burns с 5 камерами, `xfade`, прожиг ASS, `loudnorm`, музыка с ducking, одно финальное кодирование), `run_pipeline` (сценарий → MP4, прогресс, `report.json`), CLI `render` и `compose`, e2e-тесты с ffmpeg в CI.
- 2026-11-02: Этап 5a: API проектов и сцен, демо-логин (HMAC-cookie), дневной лимит проектов, импорт .txt/.docx, Celery-задачи над БД, прогресс через SSE, перегенерация сцены (новый seed, новый промпт через `scene_regenerate`), раздача файлов. Поля прогресса в Project, `Scene.image_seed`.
- 2026-11-02: Этап 5b: веб-интерфейс на React + Ant Design: вход, история проектов, создание проекта (текст/файл, стиль, формат, голос), редактор сцен с перегенерацией, таймлайн, прогресс через SSE, плеер и скачивание. Зависимость `react-router-dom`.
- 2026-11-02: Этап 6: библиотека из 12 треков CC0 (проверка лицензии через API Wikimedia Commons, `catalog.json`, `LICENSES.md`), автоподбор музыки по настроению сцен, плавный вход и выход музыки; JSON-шаблоны форматов (субтитры, переходы, зум, логотип, безопасные зоны); брендинг: логотип, шрифт и цвета субтитров, карточки интро и аутро; 4 шрифта OFL с кириллицей; API музыки, логотипа и брендинга; вкладка «Музыка и стиль» и таймлайн с карточками; `python -m app.cli music`; `tests/sample_frames.py` и артефакт CI `sample-frames` для проверки рендера глазами.
- 2026-11-02: Этап 7 (без VPS): миграции Alembic с тестом на расхождение моделей и миграций; черновой рендер 480p (10 с на минуту видео) и кнопка «Быстрый предпросмотр»; ежедневная очистка по TTL с восстановлением зависших задач (Celery beat); тайминги шагов и отчёт по KPI `python -m app.cli stats`; бенчмарк рендера (workflow `Render benchmark`); сервисы `migrate` и `beat`, healthchecks, Caddy без буферизации SSE; задания CI `stack (docker compose, dev)` и `stack (… prod)` с smoke-тестом `scripts/smoke_stack.sh`.
- 2026-11-03: Адаптер картинок ProxyAPI подогнан под документацию: размер по ближайшим пропорциям с откатом на 1024×1024, `quality`, необязательный seed, стоимость по токенам из ответа, ясные ошибки. Команды `image-models` и `smoke-image`.
- 2026-11-03: По каталогу ProxyAPI (https://proxyapi.ru/models/browse): таблицы цен с идентификаторами в коде (`services/llm/pricing.py`, `services/images/pricing.py`, 46 моделей картинок); `image-models` показывает модели вашего ключа с ценами, дешёвые первыми; тест следит, чтобы `.env.example`, значения по умолчанию и таблицы цен не расходились.

### Changed
- 2026-11-03: Идентификаторы моделей ProxyAPI теперь с префиксом производителя: `anthropic/claude-haiku-5-5`, `deepseek/deepseek-v4.1-flash` (раньше без префикса). Картинки по умолчанию `black-forest-labs/flux-3-image-klein` (263 ₽ за 1 млн токенов), потому что `openai/gpt-image-1-mini` из примера в документации в каталоге нет. Подбор размера: по очереди, отвергнутые размеры отбрасываются, в конце запрос без `size`.
- 2026-11-03: Провайдер картинок по умолчанию — ProxyAPI (`openai/gpt-image-1-mini`, `quality=low`), Fal.ai запасной: про его доступность из РФ и оплату российскими картами подтверждений нет. Таймаут картинки 120 с.
- 2026-11-02: Клипы сцен кодируются `ultrafast` crf 18 вместо `veryfast` crf 20: рендер минуты видео 62 → 50 с (SSIM 0,986). Prod compose: код из образа, `AUTO_MIGRATE=false`, миграции в сервисе `migrate`.
- 2026-11-02: `STYLE_DEFAULTS` и настройки `TRANSITION_SEC`, `MUSIC_VOLUME` заменены шаблонами (`backend/templates`). Промпт-правило `music_mood` v2. Папки `assets/` и `templates/` находятся внутри `backend/` (попадают в Docker-образ).
- 2026-11-02: Промпт `scene_split` v2: секция `retry` вынесена из кода. Новый промпт `smoke_llm`. ruff зафиксирован на 0.17.3.

### Fixed
- 2026-11-02: `.env.example`: комментарий в конце строки (`PROXYAPI_KEY=   # …`) docker compose читал как значение, и стек ходил в настоящий API с «ключом»-комментарием (нашёл CI-проверка стека). Комментарии перенесены на отдельные строки, добавлен тест.

### Decided
- LLM через ProxyAPI: Claude Haiku 5.5 (основная), DeepSeek V4.1 Flash (запасная).
- Изображения: Fal.ai FLUX schnell (до сравнения с ProxyAPI), TTS: Edge TTS.
- Переиспользование модулей MoneyPrinterTurbo (MIT) с атрибуцией.
- 2026-11-02: Разработка на VPS (Docker Compose + `backend/.venv`), до появления VPS тесты Python гоняются в CI. Публичный репозиторий `Ivan22590/text2reel`.
- 2026-11-02: Видеоряд: одна AI-картинка на сцену + Ken Burns (`zoompan`) и `xfade`. Покадровой генерации и image-to-video нет. ТЗ обновлено до v0.2, в COMPETITORS добавлено сравнение с MoneyPrinterTurbo.
