---
id: image_prompt
version: 1
type: template            # не LLM-промпт, а шаблон сборки промпта для генератора картинок
variables: [style_prefix, style_bible_short, visual_prompt, style_suffix]
---

## positive
{{style_prefix}}, {{visual_prompt}}. {{style_bible_short}}. {{style_suffix}}

## negative
text, letters, watermark, logo, signature, caption, blurry, low quality, deformed hands,
extra fingers, distorted face, cropped head, duplicate, jpeg artifacts
