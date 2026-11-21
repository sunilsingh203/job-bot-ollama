"""Resume file -> plain text (PDF, DOCX, TXT/MD)."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from docx import Document

from jobbot.text import normalize


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        with pymupdf.open(path) as doc:
            text = "\n".join(page.get_text() for page in doc)
    elif suffix == ".docx":
        text = "\n".join(p.text for p in Document(str(path)).paragraphs)
    elif suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"Unsupported resume format: {path.name} (use PDF, DOCX or TXT)")
    return normalize(text)
