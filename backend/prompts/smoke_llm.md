---
id: smoke_llm
version: 1
model: ${LLM_MODEL} and ${LLM_FALLBACK_MODEL}
max_tokens: 50
response_format: json_object
variables: []
---

## system
Answer with JSON: {"ok": true, "lang": "<language of the user message>"}

## user
Привет! На каком языке это сообщение?
