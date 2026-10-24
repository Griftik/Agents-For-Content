"""LLM-нормализатор сырых карточек в Event (п. 7 спеки). OpenRouter, JSON по схеме EventIn, валидация pydantic.

Второй этап плана (неделя 7–8); функция готова к вызову из воркера, как только появятся коллекторы.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from leisure import settings
from leisure.core.catalog import ALL_CATS, KNOWN_TAGS

from .schema import EventIn, RawEvent

PROMPT_PATH = Path(__file__).with_name("prompts") / "normalize_event.md"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")

TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


def make_slug(title: str, first_date: str, max_len: int = 100) -> str:
    base = _SLUG_CLEAN.sub("-", title.lower().translate(TRANSLIT)).strip("-")[: max_len - 11]
    return f"{base or 'event'}-{first_date}"


def build_prompt(raw: RawEvent, date_from: str, date_to: str) -> str:
    schema = json.dumps(EventIn.model_json_schema(), ensure_ascii=False)
    text = PROMPT_PATH.read_text(encoding="utf-8")
    repl = {
        "categories": ", ".join(ALL_CATS), "tags": ", ".join(sorted(KNOWN_TAGS)), "date_from": date_from,
        "date_to": date_to, "schema": schema, "source": raw.source, "url": raw.url, "title": raw.title,
        "date_text": raw.date_text, "venue": raw.venue, "price_text": raw.price_text, "text": raw.text,
    }
    for k, v in repl.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def _extract_json(s: str) -> dict:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    return json.loads(s)


def normalize_raw(raw: RawEvent, date_from: str, date_to: str, model: str | None = None, timeout: float = 90) -> EventIn:
    """Один вызов LLM → валидное событие в статусе draft. Исключения — наружу, воркер решает, что ретраить."""
    payload = {
        "model": model or settings.NORMALIZE_MODEL,
        "messages": [{"role": "user", "content": build_prompt(raw, date_from, date_to)}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.openrouter_key()}", "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        r = client.post(OPENROUTER_URL, headers=headers, json=payload)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    data = _extract_json(content)
    data.setdefault("url", raw.url)
    data.setdefault("sources", [raw.url])
    data["status"] = "draft"
    if not data.get("slug"):
        data["slug"] = make_slug(data.get("title") or raw.title, str((data.get("dates") or [date_from])[0]))
    return EventIn.model_validate(data)
