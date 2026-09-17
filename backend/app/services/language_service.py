"""Language detection.

Runs once, on the first message of a conversation. The result is stored and the
system prompt turns it into a reply-in-this-language instruction.

`lingua` rather than an LLM call: detection is deterministic, free, adds no
latency to the first token, and can be asserted in a unit test. Asking the model
to classify would cost tokens on every new conversation and make the behaviour
untestable without a network.

The language set is restricted on purpose. `lingua` loads a model per language,
so a short list is both smaller in memory and markedly more accurate on short
text — and a first message is usually short.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from lingua import IsoCode639_1, Language, LanguageDetector, LanguageDetectorBuilder

logger = logging.getLogger(__name__)

# Minimum characters before a guess is worth making. Below this, "hi" and "hai"
# are indistinguishable and a wrong guess is worse than the default.
MIN_CONFIDENT_LENGTH = 12
MIN_CONFIDENCE = 0.55

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "ms": "Bahasa Melayu",
    "ta": "Tamil",
    "zh": "Chinese",
    "bn": "Bengali",
    "id": "Bahasa Indonesia",
    "ar": "Arabic",
    "hi": "Hindi",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ja": "Japanese",
    "ko": "Korean",
    "pt": "Portuguese",
    "ru": "Russian",
    "th": "Thai",
    "vi": "Vietnamese",
}


@lru_cache(maxsize=4)
def _detector(codes: tuple[str, ...]) -> LanguageDetector | None:
    """Build a detector for the configured languages.

    Cached because constructing one loads a model per language, which is slow
    enough to matter if it happened per request.
    """
    languages: list[Language] = []
    for code in codes:
        # IsoCode639_1 exposes members as attributes, not by subscript.
        iso = getattr(IsoCode639_1, code.upper(), None)
        if iso is None:
            logger.warning("unknown language code %r in SUPPORTED_LANGUAGES; ignoring", code)
            continue
        try:
            languages.append(Language.from_iso_code_639_1(iso))
        except (KeyError, ValueError):
            logger.warning("lingua has no model for %r; ignoring", code)

    if len(languages) < 2:
        # lingua needs at least two languages to choose between.
        logger.warning("need at least two supported languages to detect; detection disabled")
        return None
    return LanguageDetectorBuilder.from_languages(*languages).build()


def detect_language(text: str, *, supported: list[str], default: str) -> str:
    """Return an ISO 639-1 code, falling back to `default`.

    Never raises: a wrong or missing language should change the wording of a
    reply, never break a conversation.
    """
    cleaned = text.strip()
    if len(cleaned) < MIN_CONFIDENT_LENGTH:
        return default

    detector = _detector(tuple(supported))
    if detector is None:
        return default

    try:
        confidences = detector.compute_language_confidence_values(cleaned)
    except Exception:  # noqa: BLE001 - detection must not break a turn
        logger.exception("language detection failed; falling back to %s", default)
        return default

    if not confidences:
        return default

    best = confidences[0]
    if best.value < MIN_CONFIDENCE:
        return default
    return best.language.iso_code_639_1.name.lower()


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code.lower(), code)


def reply_instruction(code: str) -> str:
    """The sentence appended to the system prompt."""
    return (
        f"The user is writing in {language_name(code)}. "
        f"Reply in {language_name(code)} unless they ask for another language."
    )
