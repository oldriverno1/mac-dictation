"""IME identifier → (language, context prompt) resolution."""

IME_TO_LANG: dict[str, str] = {
    # English
    "com.apple.keylayout.ABC": "en",
    "com.apple.keylayout.US": "en",
    "com.apple.keylayout.British": "en",
    "com.apple.keylayout.Australian": "en",
    "com.apple.keylayout.Canadian": "en",
    "com.apple.keylayout.Dvorak": "en",
}

# Prefixes for fuzzy matching (input methods whose ID has a variable suffix).
IME_PREFIX_TO_LANG: list[tuple[str, str]] = [
    ("com.apple.inputmethod.TCIM.", "zh"),  # Traditional Chinese (Zhuyin, Cangjie, ...)
    ("com.apple.inputmethod.SCIM.", "zh"),  # Simplified Chinese
    ("com.apple.inputmethod.TYIM.", "zh"),  # Yale-style
]

CONTEXT_PROMPTS: dict[str, str] = {
    "en": "The following is English dictation. May include technical terms such as MLX, Python, transformer.",
    "zh": "以下是繁體中文（台灣）的口述輸入，可能包含技術術語如 MLX、Python、LLM。",
    "auto": "",
}


def resolve_language(ime_id: str) -> tuple[str, str]:
    """Return (lang_code, context_prompt) for a macOS input source identifier.

    Returns ('auto', '') for unknown identifiers — let the ASR model auto-detect.
    """
    if ime_id in IME_TO_LANG:
        lang = IME_TO_LANG[ime_id]
        return lang, CONTEXT_PROMPTS[lang]

    for prefix, lang in IME_PREFIX_TO_LANG:
        if ime_id.startswith(prefix):
            return lang, CONTEXT_PROMPTS[lang]

    return "auto", CONTEXT_PROMPTS["auto"]
