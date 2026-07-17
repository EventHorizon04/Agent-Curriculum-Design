from __future__ import annotations

from typing import cast

from keybert import KeyBERT

from curriculum_agent.nlp.embedding import get_model
from curriculum_agent.nlp.thai_tokenizer import tokenize_for_keybert

_kw_model: KeyBERT | None = None


def get_keybert() -> KeyBERT:
    global _kw_model
    if _kw_model is None:
        _kw_model = KeyBERT(model=get_model())
    return _kw_model


def extract_keywords(
    text: str,
    top_n: int = 10,
    ngram_range: tuple[int, int] = (1, 2),
) -> list[tuple[str, float]]:
    tokenized = tokenize_for_keybert(text)
    # KeyBERT ships no type information — cast its untyped return to the declared shape.
    return cast(
        list[tuple[str, float]],
        get_keybert().extract_keywords(
            tokenized,
            keyphrase_ngram_range=ngram_range,
            top_n=top_n,
            use_mmr=True,
            diversity=0.5,
        ),
    )
