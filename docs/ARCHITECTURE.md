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

Каждый шаг идемпотентен: если артефакт есть и hash входа совпадает, шаг пропускается. Это одновременно кэш и возможность продолжить с упавшего шага.

Прогресс: каждая задача публикует в Redis-канал `progress:{project_id}` событие `{step, scene, percent, message}`, API отдаёт его клиенту через SSE.

## 3. Модель данных

```
Project
  id, title, script, language, style, format, voice, music_track_id|null,
  branding_json, status (draft|analyzing|scenes_ready|generating|assets_ready|rendering|done|failed),
  style_bible, seed, created_at, updated_at

Scene
  id, project_id, index, narration, visual_prompt, mood, camera,
  image_path, audio_path, duration_sec, words_json, status, error

RenderJob
  id, project_id, format, status, progress, step,
  output_path, srt_path, started_at, finished_at, error,
  tokens_in, tokens_out, images_count, cost_rub
```

## 4. API (черновик)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/health` | ✅ Статус API, версия, выбранные модели |
| POST | `/api/auth/login` | Демо-логин, выдаёт cookie-сессию |
| GET | `/api/meta` | Стили, форматы, голоса, треки, шаблоны |
| POST | `/api/projects` | Создать проект (текст или файл) |
| GET | `/api/projects` | История проектов |
| GET | `/api/projects/{id}` | Проект со сценами |
| PATCH | `/api/projects/{id}` | Изменить стиль, формат, голос, музыку, брендинг |
| POST | `/api/projects/{id}/analyze` | Разбить на сцены |
| PATCH | `/api/scenes/{id}` | Изменить текст или промпт сцены |
| POST | `/api/scenes/{id}/regenerate` | Перегенерировать картинку и/или озвучку сцены |
| POST | `/api/projects/{id}/generate` | Сгенерировать картинки и озвучку для всех сцен |
| GET | `/api/projects/{id}/timeline` | Данные для таймлайна (сцены, длительности, субтитры) |
| POST | `/api/projects/{id}/render` | Запустить рендер (`{format, draft: bool}`) |
| GET | `/api/projects/{id}/events` | SSE-поток прогресса |
| GET | `/api/files/{path}` | Раздача файлов (картинки, аудио, MP4, SRT) |
| POST | `/api/branding/logo` | Загрузка логотипа |

## 5. Сервисы backend

| Модуль | Назначение |
|---|---|
| `services/llm/client.py` | ✅ Единый клиент ProxyAPI (OpenAI SDK, `base_url` из `.env`): повторы с экспоненциальной задержкой на сетевые ошибки, 429 и 5xx (3 раза), затем запасная модель; JSON-режим; учёт токенов и стоимости |
| `services/llm/pricing.py` | ✅ Цены моделей ProxyAPI (₽ за 1M токенов) для расчёта `cost_rub` |
| `services/scenes.py` | ✅ `split_script()`: проверка ввода (≤ 5 000 символов, стиль, формат), автоопределение языка, целевое число сцен (≈ 6 с на сцену), Pydantic-схема `Storyboard`, проверка совпадения текста со сценарием (≥ 0,97), повторы с retry-промптом, кэш `storage/cache/llm/{sha256}.json` |
| `services/styles.py` | ✅ Пресеты стилей из `prompts/style_presets.md` |
| `app/cli.py` | ✅ `llm-models`, `smoke-llm`, `scenes` (пайплайн этапа 1 из командной строки) |
| `services/images/` | `base.py` (интерфейс), `fal.py`, `proxyapi.py`, `crop.py`, `styles.py` (пресеты) |
| `services/tts.py` | Edge TTS, word boundaries, SSML-паузы |
| `services/subtitles.py` | Сборка SRT и ASS (по фразам и по словам) |
| `services/compositor.py` | Построение и запуск FFmpeg-команд |
| `services/music.py` | Каталог треков, подбор по `mood` |
| `services/templates.py` | Загрузка JSON-шаблонов форматов |
| `app/prompts/loader.py` | ✅ Чтение `backend/prompts/*.md` (YAML front matter + секции `## system`/`## user`), подстановка `{{var}}`, ошибка при отсутствии переменной |
| `app/workers/celery_app.py` | ✅ Celery: маршрутизация `tasks.ai.*` → `ai`, `tasks.render.*` → `render`; `CELERY_EAGER=true` для тестов |

## 6. Рецепты FFmpeg (черновик)

**Клип сцены с Ken Burns** (кадр предварительно масштабирован до 2× размера выхода, чтобы зум был плавным):
```bash
ffmpeg -loop 1 -i scene.png -t {dur} -vf \
 "zoompan=z='min(zoom+0.0008,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps=30,format=yuv420p" \
 -c:v libx264 -preset veryfast -crf 20 clip_i.mp4
```

**Переходы** (смещение = сумма длительностей предыдущих клипов − n·T):
```bash
ffmpeg -i c0.mp4 -i c1.mp4 -i c2.mp4 -filter_complex \
 "[0][1]xfade=transition=fade:duration=0.5:offset={o1}[v1];[v1][2]xfade=transition=slideleft:duration=0.5:offset={o2}[v]" \
 -map "[v]" video.mp4
```

**Музыка с ducking, субтитры, логотип, финальное кодирование:**
```bash
ffmpeg -i video.mp4 -i voice.m4a -i music.mp3 -i logo.png -filter_complex \
 "[2:a]volume=0.25,aloop=-1:2e9[m];[m][1:a]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400[md];\
  [1:a][md]amix=inputs=2:duration=first:normalize=0[a];\
  [0:v]ass=subs.ass[vs];[3:v]scale=iw*0.12:-1,format=rgba,colorchannelmixer=aa=0.8[lg];\
  [vs][lg]overlay=W-w-40:40[v]" \
 -map "[v]" -map "[a]" -c:v libx264 -preset veryfast -crf 21 -c:a aac -b:a 160k -movflags +faststart out.mp4
```

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
