"""Loads product prompts from backend/prompts/*.md.

File format: YAML front matter between `---` lines, then sections started by
`## <name>` headings (e.g. `## system`, `## user`). Placeholders are `{{name}}`.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import get_settings

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_SECTION = re.compile(r"^## +(\w+) *$", re.MULTILINE)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class PromptError(ValueError):
    pass


@dataclass
class Prompt:
    id: str
    version: int
    meta: dict
    sections: dict[str, str] = field(default_factory=dict)

    def render(self, section: str, **variables: object) -> str:
        if section not in self.sections:
            raise PromptError(f"prompt {self.id!r} has no section {section!r}")

        def substitute(match: re.Match) -> str:
            name = match.group(1)
            if name not in variables:
                raise PromptError(f"prompt {self.id!r}: missing variable {name!r}")
            return str(variables[name])

        return _PLACEHOLDER.sub(substitute, self.sections[section])


def parse_prompt(text: str) -> Prompt:
    match = _FRONT_MATTER.match(text)
    if not match:
        raise PromptError("prompt file has no front matter")
    meta = yaml.safe_load(match.group(1)) or {}
    body = text[match.end() :]

    sections: dict[str, str] = {}
    parts = _SECTION.split(body)
    # parts = [preamble, name1, text1, name2, text2, ...]
    for name, content in zip(parts[1::2], parts[2::2], strict=True):
        sections[name] = content.strip()

    return Prompt(id=meta["id"], version=int(meta.get("version", 1)), meta=meta, sections=sections)


def load_prompt(prompt_id: str, prompts_dir: Path | None = None) -> Prompt:
    directory = prompts_dir or get_settings().prompts_dir
    path = directory / f"{prompt_id}.md"
    if not path.exists():
        raise PromptError(f"prompt file not found: {path}")
    return parse_prompt(path.read_text(encoding="utf-8"))
