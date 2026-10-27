"""Sentence-level BM25 over one case's pseudonymised documents. Cases are small, so the index is built per run in
memory: nothing about one patient is ever searchable from another's run."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .grounding import Doc, sentences

_WORD = re.compile(r"[a-zäöüß0-9]+")
_SUFFIXES = ("ungen", "ung", "en", "er", "es", "em", "e", "s")


def _stem(w: str) -> str:
    for s in _SUFFIXES:
        if len(w) > len(s) + 3 and w.endswith(s):
            return w[: -len(s)]
    return w


def tokens(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower()) if len(w) > 1]


@dataclass
class Hit:
    doc_id: str
    sentence: str
    score: float


class Index:
    def __init__(self, docs: list[Doc], k1: float = 1.4, b: float = 0.75):
        self.rows: list[tuple[str, str, list[str]]] = []
        for d in docs:
            for _, _, s in sentences(d.text):
                # long unpunctuated dictation: index in windows of ~30 words
                words = s.split()
                for i in range(0, max(len(words), 1), 30):
                    chunk = " ".join(words[i : i + 30])
                    if chunk.strip():
                        self.rows.append((d.id, chunk, tokens(chunk)))
        self.k1, self.b = k1, b
        self.avg = sum(len(t) for _, _, t in self.rows) / max(len(self.rows), 1)
        df: Counter[str] = Counter()
        for _, _, t in self.rows:
            df.update(set(t))
        n = len(self.rows)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def search(self, query: str, k: int = 5) -> list[Hit]:
        q = tokens(query)
        scored = []
        for doc_id, s, t in self.rows:
            tf = Counter(t)
            score = 0.0
            for w in q:
                if w in tf:
                    f = tf[w]
                    score += (
                        self.idf.get(w, 0.0)
                        * f
                        * (self.k1 + 1)
                        / (f + self.k1 * (1 - self.b + self.b * len(t) / self.avg))
                    )
            if score > 0:
                scored.append(Hit(doc_id, s, round(score, 3)))
        scored.sort(key=lambda h: -h.score)
        return scored[:k]
