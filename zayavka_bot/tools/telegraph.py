"""Публикация документов из docs/*.md на telegra.ph (политика ПД, согласие, оферта).

    TELEGRAPH_TOKEN=... python tools/telegraph.py docs/privacy_policy.md            # новая страница
    TELEGRAPH_TOKEN=... python tools/telegraph.py docs/privacy_policy.md <path>     # обновить по той же ссылке

Разметка: «# » — заголовок страницы, «## » — раздел, «- » — список, **жирный**, ссылки
http(s)://… становятся кликабельными. {PRIVACY_URL} и подобное подставляются из окружения.
Токен даёт право править страницы — в git его не кладём.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://api.telegra.ph"
INLINE = re.compile(r"\*\*(.+?)\*\*|(https?://[^\s)]+[^\s).,;:])")


def inline(text: str) -> list:
    out: list = []
    pos = 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            out.append(text[pos:m.start()])
        if m.group(1):
            out.append({"tag": "strong", "children": inline(m.group(1))})
        else:
            out.append({"tag": "a", "attrs": {"href": m.group(2)}, "children": [m.group(2)]})
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return out


def to_nodes(md: str) -> tuple[str, list]:
    md = re.sub(r"\{([A-Z_]+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), md)
    title, nodes, ul = "", [], None
    for block in re.split(r"\n\s*\n", md.strip()):
        for line in block.splitlines():
            line = line.rstrip()
            if line.startswith("# "):
                title = line[2:].strip()
                continue
            if line.startswith("- "):
                if ul is None:
                    ul = {"tag": "ul", "children": []}
                    nodes.append(ul)
                ul["children"].append({"tag": "li", "children": inline(line[2:].strip())})
                continue
            ul = None
            if line.startswith("## "):
                nodes.append({"tag": "h3", "children": [line[3:].strip()]})
            elif line.strip():
                nodes.append({"tag": "p", "children": inline(line.strip())})
        ul = None
    return title, nodes


def call(method: str, **params) -> dict:
    data = urllib.parse.urlencode({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                                   for k, v in params.items()}).encode()
    with urllib.request.urlopen(urllib.request.Request(f"{API}/{method}", data=data), timeout=30) as r:
        res = json.load(r)
    if not res.get("ok"):
        raise SystemExit(f"telegra.ph: {res}")
    return res["result"]


def main() -> None:
    src, path = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
    token = os.environ["TELEGRAPH_TOKEN"]
    title, nodes = to_nodes(open(src, encoding="utf-8").read())
    common = dict(access_token=token, title=title, content=nodes,
                  author_name="ИП Григорьев Е. В.", author_url="https://t.me/GrigorevStratagy_bot")
    page = call(f"editPage/{path}", **common) if path else call("createPage", **common)
    print(page["url"])


if __name__ == "__main__":
    main()
