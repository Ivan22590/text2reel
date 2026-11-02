---
id: music_mood
version: 1
type: rule                # правило без LLM: mood берётся из ответа scene_split
---

Трек подбирается по самому частому `mood` среди сцен с весом по длительности.
При ничьей приоритет такой: epic > tense > happy > calm > corporate > sad > mysterious.
Если в каталоге несколько треков с этим тегом, выбираем случайный из них с seed проекта.
