# Changelog

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии по [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Added
- 2026-11-02: Комплект документации: ТЗ, README, ROADMAP, ARCHITECTURE, MODELS_AND_COSTS, PROMPTS, COMPETITORS, DEPLOY, DEMO_SCRIPT, METRICS, SUBMISSION_CHECKLIST.
- 2026-11-02: Черновики продуктовых промптов в `backend/prompts/` (scene_split, scene_regenerate, image_prompt, style_presets, music_mood).
- 2026-11-02: `CLAUDE.md` с правилом синхронизации документации, `.env.example`, `.gitignore`, LICENSE, NOTICE.

### Decided
- LLM через ProxyAPI: Claude Haiku 5.5 (основная), DeepSeek V4.1 Flash (запасная).
- Изображения: Fal.ai FLUX schnell (до сравнения с ProxyAPI), TTS: Edge TTS.
- Переиспользование модулей MoneyPrinterTurbo (MIT) с атрибуцией.
- 2026-11-02: Разработка на VPS (Docker Compose + `backend/.venv`), до появления VPS тесты Python гоняются в CI. Публичный репозиторий `Ivan22590/text2reel`.
- 2026-11-02: Видеоряд: одна AI-картинка на сцену + Ken Burns (`zoompan`) и `xfade`. Покадровой генерации и image-to-video нет. ТЗ обновлено до v0.2, в COMPETITORS добавлено сравнение с MoneyPrinterTurbo.
