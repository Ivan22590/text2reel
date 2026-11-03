# Библиотека промптов

Здесь собраны **все** промпты проекта:
- **Часть A** — промпты продукта, которые платформа отправляет AI-моделям при работе.
- **Часть B** — промпты разработки, с которыми проект создавался вместе с AI-ассистентом (Claude Code).

Исходники продуктовых промптов лежат в [`backend/prompts/`](../backend/prompts/), код загружает их в рантайме. Ниже приведены копии с пояснениями. **При изменении файла промпта обновляем эту страницу и повышаем `version`.**

Формат записи: ID · назначение · модель и параметры · переменные · текст · пример · история версий.

---

## Часть A. Промпты продукта

### A1. `scene_split` — разбивка сценария на сцены
- **Файл:** [`backend/prompts/scene_split.md`](../backend/prompts/scene_split.md)
- **Этап:** 1 (FR-1.1–FR-1.5)
- **Модель:** Claude Haiku 5.5 через ProxyAPI, запасная DeepSeek V4.1 Flash. `temperature=0.4`, `response_format=json_object`
- **Переменные:** `language`, `style_name`, `format`, `target_scene_count` (= длительность в секундах / 6), `script`

**System:**
```
You are a storyboard artist for short vertical and horizontal videos.
Split the user's script into scenes and design visuals for each scene.

Rules:
1. Keep the narration text EXACTLY as in the script (same language, same words). You may only split it. Do not rewrite, translate, add or drop sentences.
2. One scene = 1–3 sentences, about 3–12 seconds of speech. Aim for {{target_scene_count}} scenes.
3. `visual_prompt` must be in English, 25–60 words, describe one concrete still frame: subject, action, setting, lighting, composition. No text, letters, logos or watermarks in the image.
4. Keep characters and places consistent: describe them once in `style_bible` and reuse the same names and features in every `visual_prompt`.
5. Composition must suit the {{format}} aspect ratio (for 9:16 — vertical, subject centered; for 16:9 — wide shot).
6. `mood` is one of: calm, happy, epic, sad, tense, corporate, mysterious.
7. `camera` is one of: zoom_in, zoom_out, pan_left, pan_right, static.
8. Return ONLY valid JSON matching the schema. No markdown.

Schema:
{
  "style_bible": {"characters": [{"name": str, "appearance": str}], "setting": str, "palette": str},
  "scenes": [{"narration": str, "visual_prompt": str, "mood": str, "camera": str}]
}
```

**User:**
```
Visual style: {{style_name}}
Format: {{format}}
Script language: {{language}}

Script:
"""
{{script}}
"""
```

**Пример ввода:** «Лиса жила на краю леса. Каждое утро она встречала рассвет на старом холме. Однажды она нашла там светящийся камень.» (стиль `watercolor`, формат `9:16`)

**Ожидаемый вывод (сокращённо):**
```json
{
  "style_bible": {
    "characters": [{"name": "the fox", "appearance": "small red fox with white chest and amber eyes"}],
    "setting": "edge of a pine forest, an old grassy hill",
    "palette": "warm orange, soft green, pale gold"
  },
  "scenes": [
    {"narration": "Лиса жила на краю леса.", "visual_prompt": "the fox, a small red fox with white chest and amber eyes, sitting at the edge of a pine forest, vertical composition, morning mist ...", "mood": "calm", "camera": "zoom_in"},
    {"narration": "Каждое утро она встречала рассвет на старом холме.", "visual_prompt": "...", "mood": "calm", "camera": "pan_right"},
    {"narration": "Однажды она нашла там светящийся камень.", "visual_prompt": "...", "mood": "mysterious", "camera": "zoom_in"}
  ]
}
```

**Защита:** проверка Pydantic-схемой. Склеенный текст всех `narration` сравнивается с исходным сценарием (нормализованное сходство ≥ 0,97), иначе повтор.

| Версия | Дата | Изменение |
|---|---|---|
| 1 | 2026-11-02 | Первая версия |
| 2 | 2026-11-02 | Добавлена секция `retry`: текст повторного запроса при отклонённом ответе (раньше был в коде) |

**Retry** (добавляется в диалог после ответа модели, если он не прошёл проверку; `{{error}}` — причина: невалидный JSON, несоответствие схеме или переписанный текст):
```
Your answer was rejected: {{error}}. Return the corrected JSON only.
```
Порядок попыток: основная модель до 3 раз (1 + 2 повтора с retry-сообщением), затем запасная до 2 раз. При сетевой недоступности основной модели сразу переходим к запасной.

---

### A2. `scene_regenerate` — новый визуальный промпт для одной сцены
- **Файл:** [`backend/prompts/scene_regenerate.md`](../backend/prompts/scene_regenerate.md)
- **Этап:** 2 (FR-2.5)
- **Модель:** Claude Haiku 5.5, `temperature=0.7`, JSON
- **Где используется:** `POST /api/scenes/{id}/regenerate` с непустым `hint` → `app/services/scenes.py::regenerate_visual_prompt()`
- **Переменные:** `style_bible_json`, `narration`, `previous_prompt`, `user_hint`

```
[system]
You write a single image prompt for one scene of a video storyboard.
Keep characters, setting and palette from the style bible. English, 25–60 words, one still frame,
no text or logos in the image. Make it visually different from the previous prompt.
Return JSON: {"visual_prompt": str}

[user]
Style bible: {{style_bible_json}}
Scene narration: {{narration}}
Previous prompt: {{previous_prompt}}
User wishes (may be empty): {{user_hint}}
```

| Версия | Дата | Изменение |
|---|---|---|
| 1 | 2026-11-02 | Первая версия |

---

### A3. `image_prompt` — шаблон промпта для генератора изображений
- **Файл:** [`backend/prompts/image_prompt.md`](../backend/prompts/image_prompt.md)
- **Этап:** 2 (FR-2.1, FR-2.2)
- **Модель:** модель картинок ProxyAPI (по умолчанию `openai/gpt-image-1-mini`) или FLUX schnell (Fal.ai). Размер зависит от формата и от допустимых размеров модели; общий seed есть только у Fal
- **Тип:** шаблон без LLM. Обеспечивает консистентность: одинаковые префикс и суффикс стиля и одинаковое описание персонажей во всех кадрах
- **Код:** `app/services/images/prompting.py`. `style_bible_short` = «имя: внешность; …; setting: …; palette: …». Negative передаётся только провайдерам, которые его поддерживают (у FLUX schnell его нет; ProxyAPI получает строку «Avoid: …»)

```
positive: {{style_prefix}}, {{visual_prompt}}. {{style_bible_short}}. {{style_suffix}}
negative: text, letters, watermark, logo, signature, caption, blurry, low quality, deformed hands,
          extra fingers, distorted face, cropped head, duplicate, jpeg artifacts
```

### A4. `style_presets` — пресеты визуальных стилей
- **Файл:** [`backend/prompts/style_presets.md`](../backend/prompts/style_presets.md)

| id | Название | prefix | suffix |
|---|---|---|---|
| realism | Реализм | cinematic photo, 35mm film, natural lighting | shallow depth of field, highly detailed, photorealistic |
| anime | Аниме | anime key visual, studio-quality cel shading | vibrant colors, clean line art, detailed background |
| watercolor | Акварель | soft watercolor painting on textured paper | gentle washes, muted pastel palette, hand-painted |
| comic | Комикс | bold comic book illustration, ink outlines, halftone shading | dynamic composition, saturated flat colors |
| render3d | 3D | 3D render, Pixar-like stylized characters, global illumination | soft shadows, octane render, high detail |
| minimal | Минимализм | flat vector illustration, minimalist, geometric shapes | limited palette, lots of negative space, clean |

### A5. `music_mood` — правило подбора музыки
- **Файл:** [`backend/prompts/music_mood.md`](../backend/prompts/music_mood.md) (версия 2)
- **Тип:** детерминированное правило поверх поля `mood` из A1, без отдельного вызова LLM (экономия). Код: `app/services/music.py`

1. Настроение ролика = самое частое `mood` сцен с весом по длительности озвучки; при ничьей приоритет epic > tense > happy > calm > corporate > sad > mysterious.
2. Берутся треки, где это настроение указано первым в `moods`; если таких нет, то где оно указано вторым.
3. Нет ни одного: запасные настроения (epic → tense, happy; sad → calm; mysterious → tense, calm и т. д.), затем любой трек.
4. Выбор среди подходящих: `seed проекта % число треков`.

| Версия | Дата | Изменение |
|---|---|---|
| 1 | 2026-11-02 | Первая версия |
| 2 | 2026-11-02 | Реализовано: предпочтение основного тега, цепочка запасных настроений, выбор по seed |

---

## Часть B. Промпты разработки (Claude Code)

Промпты, которыми автор управлял AI-ассистентом при создании проекта. Записываются в хронологическом порядке и дословно, лишь с минимальной правкой опечаток.

| # | Дата | Этап | Промпт | Результат |
|---|---|---|---|---|
| B1 | 2026-11-02 | Анализ | «Мне нужно сделать и сдать проект, который описан в description.md, критерии приемки у меня проекта описаны здесь criteria.md. Проанализируй и составь план, также скажи может на GitHub уже есть готовые проекты, которые подходят под эти требования и мы можем их переиспользовать полностью или с доработками.» | План из 9 этапов; найдены MoneyPrinterTurbo (MIT, донор модулей), story-flicks (без лицензии), прочие аналоги |
| B2 | 2026-11-02 | Решения | Выбор в диалоге: «Свой проект + код MoneyPrinterTurbo», «Минимальный бюджет ~$5–20» | Зафиксированы стек и бюджет |
| B3 | 2026-11-02 | LLM-провайдер | «Сделай поправку, что для доступа к LLM используем провайдера ProxyAPI» | Единый LLM-клиент через ProxyAPI, ключ и base URL в `.env` |
| B4 | 2026-11-02 | Выбор модели | «Для ProxyAPI надо подобрать экономную модель LLM» | Сравнение цен; основная Claude Haiku 5.5, запасная DeepSeek V4.1 Flash ([MODELS_AND_COSTS](MODELS_AND_COSTS.md)) |
| B5 | 2026-11-02 | Документация | «Сейчас пока составь всю документацию, в том числе сделай техзадание, README, roadmap и прочие файлы документации и подсказок. При каждой правке плана или внесении изменений в проект — соответствующим образом обновляй нужные файлы» | Этот комплект документов и правило синхронизации в `CLAUDE.md` |
| B6 | 2026-11-02 | Концепция | «В чем разница моего проекта с изначальным проектом? Правильно я понимаю, что мы будем генерировать видео покадрово? Иначе зачем генерация картинок?» | Пояснено отличие от MoneyPrinterTurbo. Решение: одна картинка на сцену + Ken Burns, без image-to-video (TZ §1.4, COMPETITORS §4) |
| B7 | 2026-11-02 | Окружение | «Уточни, ты зависимости будешь ставить в виртуальное окружение?» → выбор в диалоге: «Разрабатывать сразу на VPS» | Python-зависимости в `backend/.venv`, сервисы в Docker Compose, разработка на VPS ([DEPLOY](DEPLOY.md) §0) |
| B8 | 2026-11-02 | GitHub | Выбор в диалоге: «VPS ещё нет», «Да, создай репозиторий через gh» | Публичный репозиторий `Ivan22590/text2reel`, каркас кода готовится до появления VPS, тесты Python гоняются в CI |
| B9 | 2026-11-02 | Этап 1 | «Продолжать с этапом 1» | LLM-клиент ProxyAPI, сервис `scene_split` с валидацией, повторами и кэшем, CLI `llm-models`/`smoke-llm`/`scenes`, тесты с моком LLM |
| B10 | 2026-11-02 | Этап 2 | «продолжай» | Адаптеры картинок Fal.ai и ProxyAPI, сборка промптов со style bible и общим seed, кадрирование cover/blur, параллельная генерация с кэшем, CLI `images`, тесты без платных вызовов |
| B11 | 2026-11-02 | Этап 3 | «продолжай» | Озвучка Edge TTS с таймингами слов (адаптация из MoneyPrinterTurbo, MIT), субтитры SRT/ASS с karaoke-подсветкой, CLI `tts`, тесты |
| B12 | 2026-11-02 | Этап 4 | «Продолжай» (план этапа 4 утверждён в plan mode) | Compositor на FFmpeg (Ken Burns, xfade, ASS, loudnorm, ducking), `run_pipeline` и CLI `render`/`compose`, e2e-тесты с ffmpeg в CI |
| B13 | 2026-11-02 | Этап 5 | «Продолжай» | 5a: API для веб-интерфейса, Celery-задачи, SSE-прогресс, демо-логин; промпт `scene_regenerate` подключён к перегенерации сцены. 5b: React-интерфейс (проекты, редактор сцен, таймлайн, прогресс, плеер) |
| B14 | 2026-11-02 | Этап 6 | «Продолжай с этапом 6. Треки подбери сам» | Библиотека из 12 треков CC0 с проверкой лицензий через API Wikimedia Commons, шаблоны форматов, брендинг (логотип, шрифты, цвета, интро и аутро), вкладка «Музыка и стиль», проверка рендера по кадрам из CI |
| B15 | 2026-11-02 | Этап 7 | «Делай этап 7» | Миграции Alembic, черновой рендер 480p, очистка по TTL, отчёт по KPI, бенчмарк и ускорение рендера, проверка dev и prod стеков в CI |
| B16 | 2026-11-03 | Картинки | «Ключ proxy api у меня есть, а где взять ключ Fal.ai, этот сервис доступен из рф?» → «Подгони адаптер» → «Продолжай» | Проверка источников (про доступность Fal из РФ подтверждений нет), ProxyAPI стал провайдером картинок по умолчанию, адаптер подогнан под его документацию, команды `image-models` и `smoke-image` |

### Шаблоны промптов для следующих этапов
Повторно используемые формулировки для работы с ассистентом:

- **Реализация этапа:** «Реализуй этап N из docs/ROADMAP.md. Следуй docs/ARCHITECTURE.md, требования FR-N.* из docs/TZ.md. Напиши тесты. Обнови ROADMAP, CHANGELOG и затронутые документы.»
- **Отладка:** «Вот лог ошибки [...]. Найди причину, исправь, добавь тест, который ловит этот случай.»
- **Ревью:** «/code-review high» перед коммитом этапа.
- **Промпт продукта:** «Улучши промпт backend/prompts/X.md: проблема [...], пример плохого ответа [...]. Подними version и обнови docs/PROMPTS.md.»
