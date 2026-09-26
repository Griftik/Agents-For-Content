#!/usr/bin/env python3
"""Транскрибатор — расшифровка записей встреч в документы.

Поток: аудио (запись встречи) → OpenRouter Whisper → markdown-документ:
расшифровка + краткие тезисы/решения + замеченные «боли» (сырьё для встреч).

Режимы:
  python -m agents.transcriber file.m4a            # разовый файл → .md рядом
  python -m agents.transcriber file.m4a -o out/    # указать папку результата
  python -m agents.transcriber --watch             # следить за папкой (сервер)

В watch-режиме сканирует DATA_DIR/transcribe_in, результат кладёт в
DATA_DIR/transcriptions, обработанное аудио переносит в transcribe_in/done.
Синхронизацию папок с Google Drive даёт rclone (core.drive_sync, Слайс 3).

Длинные записи режутся на куски ffmpeg'ом (стоит на сервере из bootstrap.sh).
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import httpx

from core import config
from core.logging_setup import setup_logging

logger = setup_logging("transcriber")

OPENROUTER_URL = "https://openrouter.ai/api/v1"
AUDIO_EXT = {".ogg", ".oga", ".mp3", ".m4a", ".wav", ".flac", ".webm", ".aac", ".opus", ".mp4"}
# Больше этого размера — режем на куски (лимиты API на файл).
MAX_FILE_MB = 20
CHUNK_MINUTES = 10

SUMMARY_PROMPT = """Ниже расшифровка рабочей встречи. Сделай по ней выжимку на русском:

1. **О чём встреча** — 2-3 предложения.
2. **Ключевые тезисы** — маркированный список.
3. **Решения и договорённости** — маркированный список (если были).
4. **Задачи** — кто/что/к когда, если прозвучало.
5. **Боли и запросы** — какие проблемы, тревоги, потребности звучали у участников
   (это сырьё для тем контента и встреч, выписывай живыми формулировками).

Пиши только выжимку, без предисловий."""


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def _split_audio(path: Path, workdir: Path) -> list[Path]:
    """Режет длинное аудио на куски по CHUNK_MINUTES минут (mp3 mono)."""
    pattern = workdir / "chunk_%03d.mp3"
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-ac", "1", "-b:a", "64k", "-f", "segment",
        "-segment_time", str(CHUNK_MINUTES * 60), str(pattern),
    ])
    return sorted(workdir.glob("chunk_*.mp3"))


async def _transcribe_file(client: httpx.AsyncClient, path: Path) -> str:
    """Один файл → текст. Multipart, чтобы не раздувать base64."""
    with open(path, "rb") as f:
        r = await client.post(
            f"{OPENROUTER_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.openrouter_key()}"},
            files={"file": (path.name, f, "application/octet-stream")},
            data={"model": config.VOICE_MODEL, "language": "ru"},
        )
    r.raise_for_status()
    return r.json()["text"].strip()


async def _summarize(client: httpx.AsyncClient, transcript: str) -> str:
    r = await client.post(
        f"{OPENROUTER_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.openrouter_key()}",
            "Content-Type": "application/json",
        },
        json={
            "model": config.POST_MODEL,
            "messages": [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": transcript[:120_000]},
            ],
            "max_tokens": 2000,
        },
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


async def transcribe(path: Path, out_dir: Path | None = None) -> Path:
    """Аудио → markdown-документ. Возвращает путь к документу."""
    out_dir = out_dir or path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    size_mb = path.stat().st_size / 1_000_000
    async with httpx.AsyncClient(timeout=600) as client:
        if size_mb > MAX_FILE_MB:
            logger.info("%s: %.1f МБ — режу на куски по %d мин", path.name, size_mb, CHUNK_MINUTES)
            with tempfile.TemporaryDirectory() as td:
                chunks = _split_audio(path, Path(td))
                parts = []
                for i, chunk in enumerate(chunks, 1):
                    logger.info("кусок %d/%d", i, len(chunks))
                    parts.append(await _transcribe_file(client, chunk))
                transcript = "\n\n".join(parts)
        else:
            transcript = await _transcribe_file(client, path)

        logger.info("расшифровка готова (%d симв.), делаю выжимку", len(transcript))
        summary = await _summarize(client, transcript)

    stamp = datetime.now().strftime("%Y-%m-%d")
    doc = out_dir / f"{stamp} — {path.stem}.md"
    doc.write_text(
        f"# Расшифровка: {path.stem}\n\n"
        f"> Файл: {path.name} · {size_mb:.1f} МБ · расшифровано {stamp}\n\n"
        f"{summary}\n\n---\n\n## Полная расшифровка\n\n{transcript}\n",
        encoding="utf-8",
    )
    logger.info("документ: %s", doc)
    return doc


async def watch() -> None:
    """Режим сервера: следим за папкой, новые аудио превращаем в документы."""
    inbox = config.DATA_DIR / "transcribe_in"
    done = inbox / "done"
    out = config.DATA_DIR / "transcriptions"
    for d in (inbox, done, out):
        d.mkdir(parents=True, exist_ok=True)
    logger.info("Транскрибатор слушает %s (результат → %s)", inbox, out)
    while True:
        for f in sorted(inbox.iterdir()):
            if f.is_file() and f.suffix.lower() in AUDIO_EXT:
                try:
                    await transcribe(f, out)
                    f.rename(done / f.name)
                except Exception as e:
                    logger.error("%s: %s", f.name, e)
                    f.rename(done / f"FAILED_{f.name}")
        time.sleep(30)


def main() -> None:
    ap = argparse.ArgumentParser(description="Расшифровка записей встреч")
    ap.add_argument("files", nargs="*", help="аудиофайлы для расшифровки")
    ap.add_argument("-o", "--out", help="папка для документов")
    ap.add_argument("--watch", action="store_true", help="следить за папкой (сервер)")
    args = ap.parse_args()

    if args.watch:
        asyncio.run(watch())
        return
    if not args.files:
        ap.print_help()
        sys.exit(1)
    out = Path(args.out) if args.out else None
    for f in args.files:
        asyncio.run(transcribe(Path(f), out))


if __name__ == "__main__":
    main()
