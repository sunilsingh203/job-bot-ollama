"""Small text helpers shared by resume parsing and scraping."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup


def normalize(text: str) -> str:
    text = text.replace(" ", " ").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(html: str) -> str:
    """HTML fragment -> readable plain text (list items become '- ' lines)."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6"]):
        block.insert_after("\n")
    return normalize(soup.get_text())
