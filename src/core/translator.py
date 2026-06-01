"""Translation backends.

Backends
--------
openai  — GPT-4o-mini batched (cloud, requires API key, excellent quality)
argos   — Argos Translate OPUS-MT (offline, ~100 MB model per language pair,
           downloaded on first use, decent quality)
"""

from __future__ import annotations

import json
import re
from typing import Callable

# ── Helpers ───────────────────────────────────────────────────────────── #

def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _extract_json_array(raw: str) -> list[str]:
    """Robustly extract a JSON array from an LLM response."""
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    return json.loads(raw)


# ── OpenAI ────────────────────────────────────────────────────────────── #

_OPENAI_BATCH = 80   # subtitles per API call


def translate_openai(
    texts: list[str],
    target_lang: str,
    api_key: str,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[str]:
    """Translate *texts* to *target_lang* using gpt-4o-mini (batched)."""
    from openai import OpenAI  # noqa: PLC0415

    client  = OpenAI(api_key=api_key)
    results : list[str] = []
    total   = len(texts)

    for batch in _chunks(texts, _OPENAI_BATCH):
        prompt = (
            f"Translate the following subtitle texts to {target_lang}. "
            "Return ONLY a valid JSON array of translated strings, same order "
            "and count as the input. Preserve all formatting and line breaks. "
            "No explanations.\n\n"
            + json.dumps(batch, ensure_ascii=False)
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        translated = _extract_json_array(resp.choices[0].message.content.strip())
        # Guard: if LLM returned wrong count, pad / trim
        if len(translated) < len(batch):
            translated += batch[len(translated):]
        results.extend(translated[: len(batch)])
        if progress_cb:
            progress_cb(len(results), total)

    return results


# ── Argos Translate (local) ───────────────────────────────────────────── #

def translate_argos(
    texts: list[str],
    target_lang: str,
    source_lang: str = "en",
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[str]:
    """Translate using Argos Translate (offline OPUS-MT models).

    Language models (~100 MB each) are downloaded automatically on first use
    for each language pair.
    """
    import argostranslate.package    # noqa: PLC0415
    import argostranslate.translate  # noqa: PLC0415

    def _installed():
        return argostranslate.translate.get_installed_languages()

    def _get_translation(installed):
        from_l = next((l for l in installed if l.code == source_lang), None)
        to_l   = next((l for l in installed if l.code == target_lang), None)
        if from_l is None or to_l is None:
            return None
        return from_l.get_translation(to_l)

    translation = _get_translation(_installed())

    if translation is None:
        # Download the required language package
        if progress_cb:
            progress_cb(0, len(texts))
        argostranslate.package.update_package_index()
        available = argostranslate.package.get_available_packages()
        pkg = next(
            (p for p in available
             if p.from_code == source_lang and p.to_code == target_lang),
            None,
        )
        if pkg is None:
            raise ValueError(
                f"No Argos model available for {source_lang} → {target_lang}.\n"
                "Try a different language pair or use the OpenAI backend."
            )
        argostranslate.package.install_from_path(pkg.download())
        translation = _get_translation(_installed())

    if translation is None:
        raise ValueError(
            f"Could not load translation for {source_lang} → {target_lang}."
        )

    results = []
    total   = len(texts)
    for i, text in enumerate(texts):
        results.append(translation.translate(text))
        if progress_cb:
            progress_cb(i + 1, total)
    return results
