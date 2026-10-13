"""
The library: the texts of the books you can read.

Each book is a plain text file, ``assets/books/<id>.txt``, read through the
data-package loader (engine/asset_archives.py): pack them into
``books.fiopak`` with the same paths and nothing else changes -- the packed
copy is read first, and a loose file still works (and still overrides, for
an author trying a change). The format::

    Title: The Last Ferryman of Mirrormere
    Author: Edda Reedwife

    "An epigraph, if you like."

    -- whoever said it

    The first paragraph. Paragraphs are separated by a blank line; a long
    one may run over several lines in the file.

    [page]

    A line that is only [page] starts a new page.

Everything before the first blank line is the header (``Title:``,
``Author:``; unknown keys are kept in ``Book.meta``). A book item names its
text with ``"book": "<id>"`` in ``game/data/items.json``.
"""

from __future__ import annotations

from typing import Dict, List, Optional

BOOK_DIR = "assets/books"
PAGE_BREAK = "[page]"

_cache: Dict[str, Optional["Book"]] = {}


class Book:
    def __init__(self, book_id: str, title: str, author: str,
                 paragraphs: List[str], meta: Dict[str, str]):
        self.id = book_id
        self.title = title
        self.author = author
        #: Paragraph texts, with PAGE_BREAK entries where a page must turn.
        self.paragraphs = paragraphs
        self.meta = meta


def parse(book_id: str, text: str) -> Book:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    meta: Dict[str, str] = {}
    i = 0
    while i < len(lines) and lines[i].strip():
        key, sep, value = lines[i].partition(":")
        if sep:
            meta[key.strip().lower()] = value.strip()
        i += 1
    paragraphs: List[str] = []
    current: List[str] = []
    for line in lines[i:]:
        s = line.strip()
        if s == PAGE_BREAK:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append(PAGE_BREAK)
        elif not s:
            if current:
                paragraphs.append(" ".join(current))
                current = []
        else:
            current.append(s)
    if current:
        paragraphs.append(" ".join(current))
    title = meta.get("title") or book_id.replace("_", " ").title()
    return Book(book_id, title, meta.get("author", ""), paragraphs, meta)


def get(book_id: str) -> Optional[Book]:
    """The book called *book_id*, or None if there is no such text."""
    key = str(book_id or "").strip()
    if not key or "/" in key or "\\" in key or key.startswith("."):
        return None
    if key in _cache:
        return _cache[key]
    from engine import asset_archives
    raw = asset_archives.read(f"{BOOK_DIR}/{key}.txt")
    book = None
    if raw is not None:
        try:
            book = parse(key, raw.decode("utf-8"))
        except UnicodeDecodeError:
            book = parse(key, raw.decode("latin-1"))
    _cache[key] = book
    return book


def ids() -> List[str]:
    """Every book text there is, packed or loose."""
    from engine import asset_archives
    out = []
    for path in asset_archives.listing(BOOK_DIR, (".txt",)):
        name = path.rsplit("/", 1)[-1][:-4]
        if name not in out:
            out.append(name)
    return out


def refresh() -> None:
    """Forget cached texts (a package was added, or a text edited)."""
    _cache.clear()


def book_of_item(item_id) -> Optional[Book]:
    """The text a book item holds, or None for a book with no text."""
    from .rpg import items as rpg_items
    d = rpg_items.get(item_id)
    if d is None or d.category != rpg_items.BOOK:
        return None
    return get(d.get("book") or "")
