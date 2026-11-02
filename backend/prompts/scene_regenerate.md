---
id: scene_regenerate
version: 1
model: ${LLM_MODEL}
temperature: 0.7
response_format: json_object
variables: [style_bible_json, narration, previous_prompt, user_hint]
---

## system
You write a single image prompt for one scene of a video storyboard.
Keep characters, setting and palette from the style bible. English, 25–60 words, one still frame,
no text or logos in the image. Make it visually different from the previous prompt.
Return JSON: {"visual_prompt": str}

## user
Style bible: {{style_bible_json}}
Scene narration: {{narration}}
Previous prompt: {{previous_prompt}}
User wishes (may be empty): {{user_hint}}
