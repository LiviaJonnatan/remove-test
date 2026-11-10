"""Prompt templates and schemas from prompts/ and schemas/, with `{name}` placeholders.

Placeholders are filled with str.replace, not str.format: the templates show the model JSON shapes
with literal braces.
"""

from __future__ import annotations

import json
from functools import cache

from config import ROOT

PROMPTS = ROOT / "prompts"
SCHEMAS = ROOT / "schemas"


@cache
def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text().strip()


@cache
def schema(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.json").read_text())


def render(template: str, **fields: str) -> str:
    for key, value in fields.items():
        template = template.replace("{" + key + "}", value)
    return template


def split_static(template: str, marker: str) -> tuple[str, str]:
    """The template up to the line holding `marker` (shared by a section's calls, cached by the
    SDK backend) and the rest (what varies per call)."""
    i = template.find(marker)
    if i < 0:
        return "", template
    return template[:i].rstrip(), template[i:]
