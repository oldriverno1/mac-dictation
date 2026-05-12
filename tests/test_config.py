from daemon.config import resolve_language, IME_TO_LANG, CONTEXT_PROMPTS


def test_us_keyboard_resolves_to_english():
    lang, ctx = resolve_language("com.apple.keylayout.ABC")
    assert lang == "en"
    assert "English" in ctx


def test_zhuyin_resolves_to_chinese():
    lang, ctx = resolve_language("com.apple.inputmethod.TCIM.Zhuyin")
    assert lang == "zh"
    assert "繁體中文" in ctx


def test_cangjie_resolves_to_chinese():
    lang, ctx = resolve_language("com.apple.inputmethod.TCIM.Cangjie")
    assert lang == "zh"


def test_simplified_chinese_resolves_to_chinese():
    lang, ctx = resolve_language("com.apple.inputmethod.SCIM.Pinyin")
    assert lang == "zh"


def test_unknown_falls_back_to_auto():
    lang, ctx = resolve_language("com.example.foo.bar")
    assert lang == "auto"
    assert ctx == ""


def test_empty_string_falls_back_to_auto():
    lang, ctx = resolve_language("")
    assert lang == "auto"
