from daemon.asr import build_prompt_kwargs


def test_english_prompt():
    kwargs = build_prompt_kwargs("en", "Some English context.")
    assert kwargs["language"] == "en"
    assert "Some English context." in kwargs["context"]


def test_chinese_prompt():
    kwargs = build_prompt_kwargs("zh", "以下是繁體中文")
    assert kwargs["language"] == "zh"
    assert "繁體中文" in kwargs["context"]


def test_auto_omits_language_hint():
    kwargs = build_prompt_kwargs("auto", "")
    # 'auto' means let the model decide → don't pass language=
    assert "language" not in kwargs or kwargs["language"] is None
