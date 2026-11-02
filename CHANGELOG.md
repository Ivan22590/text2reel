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

### Changed
- 2026-11-02: Промпт `scene_split` v2: секция `retry` вынесена из кода. Новый промпт `smoke_llm`. ruff зафиксирован на 0.17.3.

### Decided
- LLM через ProxyAPI: Claude Haiku 5.5 (основная), DeepSeek V4.1 Flash (запасная).
- Изображения: Fal.ai FLUX schnell (до сравнения с ProxyAPI), TTS: Edge TTS.
- Переиспользование модулей MoneyPrinterTurbo (MIT) с атрибуцией.
- 2026-11-02: Разработка на VPS (Docker Compose + `backend/.venv`), до появления VPS тесты Python гоняются в CI. Публичный репозиторий `Ivan22590/text2reel`.
- 2026-11-02: Видеоряд: одна AI-картинка на сцену + Ken Burns (`zoompan`) и `xfade`. Покадровой генерации и image-to-video нет. ТЗ обновлено до v0.2, в COMPETITORS добавлено сравнение с MoneyPrinterTurbo.
