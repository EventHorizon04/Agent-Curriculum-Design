from __future__ import annotations

from pythainlp.tokenize import word_tokenize


def tokenize(text: str, engine: str = "newmm") -> list[str]:
    return word_tokenize(text, engine=engine)


def tokenize_for_keybert(text: str) -> str:
    """Space-joined tokens for KeyBERT (expects whitespace-separated words)."""
    return " ".join(tokenize(text))
