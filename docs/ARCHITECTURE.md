# Архитектура

> Статус: проектирование. Документ описывает целевую архитектуру MVP и обновляется вместе с кодом.

## 1. Компоненты

```
┌──────────────┐  REST + SSE   ┌──────────────┐   enqueue   ┌───────┐   consume   ┌────────────────────┐
│ Frontend     │ ────────────▶ │ API (FastAPI)│ ──────────▶ │ Redis │ ──────────▶ │ Celery worker "ai" │──▶ ProxyAPI (LLM)
│ React + AntD │ ◀──────────── │              │ ◀── events ─│       │             │                    │──▶ Fal.ai / ProxyAPI (images)
└──────────────┘               └──────┬───────┘             └───────┘             │                    │──▶ Edge TTS
                                      │                          ▲                └────────────────────┘
                               ┌──────▼───────┐                  │                ┌────────────────────┐
                               │ DB           │                  └─────────────── │ Celery worker      │──▶ FFmpeg
                               │ SQLite / PG  │                                   │ "render"           │
                               └──────────────┘                                   └────────────────────┘
                                         storage/ (общий том: images, audio, video, cache)
```

| Компонент | Ответственность |
|---|---|
| **Frontend** | Создание проекта, редактор сцен, таймлайн, прогресс, плеер |
| **API** | CRUD проектов и сцен, запуск задач, SSE-стрим прогресса, раздача файлов, простая авторизация |
| **Redis** | Брокер Celery и pub/sub событий прогресса |
| **Worker `ai`** | Сетевые и I/O-задачи: LLM, генерация картинок, TTS. Concurrency около 4 |
| **Worker `render`** | CPU-задачи FFmpeg. Concurrency = 1–2 (по числу ядер / 2) |
| **DB** | Проекты, сцены, задачи рендера, стоимость |
| **storage/** | Файлы проекта: `storage/projects/{id}/...`, кэш `storage/cache/{hash}` |

## 2. Пайплайн

```
POST /projects/{id}/analyze      ──▶ [ai] scene_split ──▶ status=scenes_ready
POST /projects/{id}/generate     ──▶ chord( group(image_gen(scene_i)) , group(tts(scene_i)) ) ──▶ status=assets_ready
POST /projects/{id}/render       ──▶ [render] compose(format) ──▶ export ──▶ status=done
```

1. **scene_split.** Сценарий → LLM (промпт `scene_split`) → JSON `{style_bible, scenes[]}` → валидация → запись `Scene`.
2. **image_gen(scene).** `style_preset.prefix + style_bible + scene.visual_prompt` → провайдер → PNG → кадрирование под формат → `scene.image_path`.
3. **tts(scene).** `scene.narration` → Edge TTS (голос, rate, pitch) → MP3 + word boundaries → `scene.audio_path`, `scene.duration`, `scene.words`.
4. **compose.** Одна картинка на сцену превращается в клип 30 fps через `zoompan` (Ken Burns). Покадровой генерации и image-to-video нет (TZ §1.4). Затем клипы сцен → xfade → аудио (озвучка + паузы) → музыка с ducking → ASS → логотип → MP4.
5. **export.** MP4 + SRT, превью-кадр, запись стоимости и времени.

**Реализация (этап 4):** `app/services/pipeline.py::run_pipeline()` выполняет шаги 1–5 последовательно, внутри шагов — параллельно. Он вызывает `on_progress(step, percent, message)` с долями scenes 0–10 %, images 10–50 %, tts 50–60 %, render 60–100 %. Результат пишется в `out_dir/`: `storyboard.json`, `images/`, `audio/` + `narration.json`, `work/`, `subtitles.srt/.ass`, `video.mp4` и `report.json` (время и ₽ по шагам). Если упала хоть одна сцена, рендер не запускается: `PipelineError` и `report.json` с ошибкой.

Каждый шаг идемпотентен: если артефакт есть и hash входа совпадает, шаг пропускается. Это одновременно кэш и возможность продолжить с упавшего шага.

Прогресс: каждая задача публикует в Redis-канал `progress:{project_id}` событие `{step, scene, percent, message}`, API отдаёт его клиенту через SSE.

## 3. Модель данных

```
Project
  id, title, script, language, style, format, voice, music_track_id|null,
  branding_json, status (draft|analyzing|scenes_ready|generating|assets_ready|rendering|done|failed),
  style_bible, seed,
  step, progress, message, error, cost_rub      ← состояние текущей задачи (читает SSE)
  created_at, updated_at

Scene
  id, project_id, index, narration, visual_prompt, mood, camera,
  image_path, audio_path, duration_sec, words_json, status (pending|ready|failed), error,
  image_seed                                    ← +1 при перегенерации: seed кадра = project.seed + image_seed

RenderJob
  id, project_id, format, status (queued|running|done|failed), progress, step,
  output_path, srt_path, started_at, finished_at, error,
  tokens_in, tokens_out, images_count, cost_rub
```

Файлы проекта: `storage/projects/{id}/images/scene_XX.png`, `audio/scene_XX.mp3`, `renders/{job_id}/video.mp4 + subtitles.srt/.ass`. Кэш: `storage/cache/{llm,images,tts}` (через `/api/files` не отдаётся).

**Статусы и что их меняет.** `analyze`: draft → analyzing → scenes_ready (при ошибке снова draft + `error`). `generate`: → generating → assets_ready (если упала сцена — scenes_ready + `error`). `render`: → rendering → done (при ошибке assets_ready + `error`). Если изменить текст сцены, сбрасывается её озвучка; если изменить промпт, стиль или формат — картинка; если голос — озвучка всех сцен. После этого проект возвращается в scenes_ready. Пока проект в состоянии analyzing, generating или rendering, изменения отклоняются с кодом 409.

## 4. API (реализовано в `app/api/`, все пути кроме `/health` и `/auth/*` требуют входа)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/health` | Статус API, версия, выбранные модели |
| POST | `/api/auth/login` | Демо-логин (`DEMO_USER`/`DEMO_PASSWORD`), cookie `t2r_session` = `user:HMAC(SECRET_KEY)` |
| POST / GET | `/api/auth/logout`, `/api/auth/me` | Выход, текущий пользователь |
| GET | `/api/meta` | Стили, форматы, голоса, камеры, переходы по умолчанию |
| POST | `/api/scripts/parse` | Текст из загруженного `.txt` (UTF-8/CP1251) или `.docx` (≤ 1 МБ) |
| GET / POST | `/api/projects` | История; создать проект (лимит `DEMO_MAX_PROJECTS_PER_DAY` → 429) |
| GET / PATCH / DELETE | `/api/projects/{id}` | Проект со сценами и рендерами; изменить параметры; удалить |
| POST | `/api/projects/{id}/analyze` | Задача `ai.analyze`: разбить на сцены → 202 |
| POST | `/api/projects/{id}/generate` | Задача `ai.generate`: картинки и озвучка недостающих сцен → 202 |
| PATCH | `/api/scenes/{id}` | Изменить текст, визуальный промпт или камеру сцены |
| POST | `/api/scenes/{id}/regenerate` | `{target: image|audio|all, hint}`: новый seed; если задан `hint`, сначала LLM пишет новый промпт (`scene_regenerate`) |
| GET | `/api/projects/{id}/timeline` | Дорожки для превью: старты и длины клипов, озвучка, фразы субтитров |
| POST | `/api/projects/{id}/render` | Задача `render.render` → `RenderJob` (409, если у сцен нет ассетов) |
| GET | `/api/projects/{id}/events` | SSE: `{status, step, progress, message, error}` при каждом изменении; поток закрывается, когда задача завершена |
| GET | `/api/files/{path}` | Картинки, аудио, MP4, SRT из `storage/` (Range-запросы для перемотки видео) |
| POST | `/api/branding/logo` | Загрузка логотипа (этап 6) |

**Прогресс без шины сообщений.** Задача пишет `step`, `progress` и `message` в строку Project. SSE-эндпоинт опрашивает её раз в 0,7 с и отправляет только изменения. Так проще, чем Redis pub/sub, и работает в eager-режиме тестов.

## 5. Сервисы backend

| Модуль | Назначение |
|---|---|
| `services/llm/client.py` | ✅ Единый клиент ProxyAPI (OpenAI SDK, `base_url` из `.env`): повторы с экспоненциальной задержкой на сетевые ошибки, 429 и 5xx (3 раза), затем запасная модель; JSON-режим; учёт токенов и стоимости |
| `services/llm/pricing.py` | ✅ Цены моделей ProxyAPI (₽ за 1M токенов) для расчёта `cost_rub` |
| `services/scenes.py` | ✅ `split_script()`: проверка ввода (≤ 5 000 символов, стиль, формат), автоопределение языка, целевое число сцен (≈ 6 с на сцену), Pydantic-схема `Storyboard`, проверка совпадения текста со сценарием (≥ 0,97), повторы с retry-промптом, кэш `storage/cache/llm/{sha256}.json` |
| `services/styles.py` | ✅ Пресеты стилей из `prompts/style_presets.md` |
| `app/cli.py` | ✅ `llm-models`, `smoke-llm`, `scenes` (этап 1), `images` (этап 2), `tts` (этап 3), `compose` и `render` (этап 4) |
| `services/images/base.py` | ✅ Интерфейс провайдера: `ImageRequest` (prompt, negative, размер, seed) → `ImageResult` (байты, ₽) |
| `services/images/fal.py` | ✅ Fal.ai: `POST https://fal.run/<FAL_MODEL>`, `Authorization: Key …`, скачивание по URL. У FLUX schnell нет negative prompt |
| `services/images/proxyapi.py` | ✅ ProxyAPI Images API (OpenAI SDK), ответ в `b64_json` или `url` |
| `services/images/prompting.py` | ✅ Сборка промпта по шаблону `image_prompt`: префикс и суффикс стиля + style bible + визуал сцены |
| `services/images/crop.py` | ✅ Размеры генерации (~1 МП) и выхода (1080p), кадрирование `cover` / `blur` (размытый фон) |
| `services/images/generator.py` | ✅ Параллельная генерация (`IMAGE_CONCURRENCY`), общий seed проекта, 2 попытки на кадр, ошибка одной сцены не роняет остальные, кэш `storage/cache/images/{sha256}.img` |
| `services/tts.py` | ✅ Edge TTS (edge-tts 7, `boundary="WordBoundary"`): MP3 на сцену + тайминги слов, нормализация текста (финальная пунктуация для интонации), 3 попытки, кэш `storage/cache/tts/{sha256}.mp3/.json`, длительность через ffprobe (запасной вариант — расчёт по битрейту 48 кбит/с). Адаптировано из MoneyPrinterTurbo (MIT) |
| `services/subtitles.py` | ✅ Пунктуация из исходного текста → фразы (лимит символов по формату, ≤ 3,5 с, разрыв на конце предложения и паузе > 0,6 с) → SRT и ASS. Режимы `phrase` и `karaoke` (`\kf`, подсветка текущего слова) |
| `services/compositor.py` | ✅ Таймлайн, построители FFmpeg-команд (чистые функции, на них golden-тесты), `run_ffmpeg`, `render_video()` |
| `services/pipeline.py` | ✅ `run_pipeline()`: сценарий → MP4, прогресс, `report.json` (для CLI) |
| `services/project_jobs.py` | ✅ Те же шаги над БД для веб-интерфейса: `analyze_project`, `generate_assets` (только недостающее), `regenerate_scene`, `render_project`, `build_timeline` |
| `services/providers.py` | ✅ Фабрики LLM / картинок / TTS для задач; в тестах подменяются через `overrides` |
| `workers/tasks.py` | ✅ Celery-задачи `ai.analyze`, `ai.generate`, `ai.regenerate_scene`, `render.render` |
| `api/auth.py`, `api/projects.py`, `api/schemas.py` | ✅ REST, SSE, раздача файлов |
| `services/music.py` | Каталог треков, подбор по `mood` |
| `services/templates.py` | Загрузка JSON-шаблонов форматов |
| `app/prompts/loader.py` | ✅ Чтение `backend/prompts/*.md` (YAML front matter + секции `## system`/`## user`), подстановка `{{var}}`, ошибка при отсутствии переменной |
| `app/workers/celery_app.py` | ✅ Celery: маршрутизация `tasks.ai.*` → `ai`, `tasks.render.*` → `render`; `CELERY_EAGER=true` для тестов |

## 6. Рецепты FFmpeg (реализовано в `services/compositor.py`)

**Таймлайн.** T — переход (`TRANSITION_SEC`, 0,4 с), P — пауза после сцены (`TTS_SCENE_PAUSE_SEC`, 0,4 с), dᵢ — длина озвучки:
```
clipᵢ = dᵢ + P + T        (у последней сцены без T)
start₀ = 0;  startᵢ₊₁ = startᵢ + clipᵢ − T   ← offset для xfade и задержка озвучки i+1
total  = start_last + clip_last
```
Переход приходится на паузу, голос не обрезается.

**1. Клип сцены (Ken Burns)**, параллельно по `RENDER_CONCURRENCY`. Кадр сначала масштабируется в 2×, чтобы `zoompan` не дрожал из-за округления координат:
```bash
ffmpeg -i scene_00.png -vf "scale=2160:3840,zoompan=z='1+0.15*on/N':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=N:s=1080x1920:fps=30,format=yuv420p" \
  -frames:v N -c:v libx264 -preset veryfast -crf 20 work/clip_00.mp4
```
Камеры (поле `camera` из `scene_split`): `zoom_in`, `zoom_out` (z = 1.15 → 1), `pan_left` / `pan_right` (z = 1.12, x движется), `static` (z = 1.03).

**2. Аудио:** озвучка на таймлайне, нормализация, музыка с ducking:
```bash
ffmpeg -i v0.mp3 -i v1.mp3 [-stream_loop -1 -i music.mp3] -filter_complex \
 "[0:a]aresample=48000,aformat=channel_layouts=stereo,adelay=0:all=1[a0];[1:a]...adelay=2400:all=1[a1];
  [a0][a1]amix=inputs=2:normalize=0:duration=longest,apad,atrim=0:TOTAL,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[voice];
  [voice]asplit=2[vmix][vkey];[2:a]...volume=0.25,atrim=0:TOTAL[music];
  [music][vkey]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400[ducked];
  [vmix][ducked]amix=inputs=2:normalize=0:duration=first[mix]" -map "[mix]" -c:a aac -b:a 160k work/audio.m4a
```

**3. Финальная сборка за одно кодирование:** переходы, прожиг субтитров, mux. ffmpeg запускается с `cwd=out_dir`, поэтому путь к `.ass` относительный и не требует экранирования:
```bash
ffmpeg -i work/clip_00.mp4 -i work/clip_01.mp4 -i work/audio.m4a -filter_complex \
 "[0:v][1:v]xfade=transition=slideleft:duration=0.4:offset=START1[x1];[x1]ass=subtitles.ass[v]" \
 -map "[v]" -map 2:a -c:v libx264 -preset veryfast -crf 21 -pix_fmt yuv420p -c:a copy -t TOTAL -movflags +faststart video.mp4
```
Переходы по умолчанию: 9:16 → `slideleft`, 16:9 и 1:1 → `fade` (на этапе 6 переедут в шаблоны). Логотип (`overlay`) — этап 6.

### Паузы и тайминг (этап 3)
Edge TTS больше не принимает собственный SSML, поэтому тег `<break>` недоступен. Паузы внутри сцены дают знаки препинания. Паузу между сценами (`TTS_SCENE_PAUSE_SEC`, 0,4 с) compositor добавляет тишиной (`apad`). Длительность клипа сцены = длительность озвучки + пауза. Субтитры строятся по абсолютным таймингам: `place_on_timeline()` сдвигает слова каждой сцены на её старт в итоговом видео.

## 7. Шаблоны форматов (`templates/*.json`)

```json
{
  "id": "shorts_9x16",
  "size": [1080, 1920],
  "safe_area": {"top": 0.12, "bottom": 0.2},
  "subtitles": {"mode": "words", "font": "Montserrat ExtraBold", "size": 72, "position": "center", "outline": 4},
  "transition": {"type": "slideleft", "duration": 0.4},
  "ken_burns": {"zoom_max": 1.15},
  "music_volume": 0.2
}
```

## 8. Ошибки и надёжность
- Сетевые ошибки и 429/5xx: повтор с экспоненциальной задержкой до 3 раз, затем запасная модель или провайдер.
- Невалидный JSON от LLM: до 2 повторов с сообщением об ошибке, затем запасная модель.
- Ошибка одной сцены не роняет проект: сцена помечается `failed`, в UI появляется кнопка «Перегенерировать».
- Таймауты: LLM 60 с, картинка 90 с, TTS 30 с, рендер 15 мин.
