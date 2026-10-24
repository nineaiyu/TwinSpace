"""Tests for locale and language resolver."""

from unittest.mock import patch

from twinspace.core.locale import (
    SUPPORTED_LANGUAGES,
    LanguageConfig,
    build_language_wrapper_snippet,
    normalize_locale_code,
    resolve_language_config,
)


def test_supported_languages_contains_presets():
    assert set(SUPPORTED_LANGUAGES.keys()) == {"system", "zh-Hans", "en"}


def test_normalize_locale_code():
    assert normalize_locale_code(None) == "system"
    assert normalize_locale_code("system") == "system"
    assert normalize_locale_code("zh") == "zh-Hans"
    assert normalize_locale_code("zh_CN") == "zh-Hans"
    assert normalize_locale_code("zh-Hans-CN") == "zh-Hans"
    # Chinese variants (incl. Traditional) resolve to the Simplified Chinese preset.
    assert normalize_locale_code("zh-Hant") == "zh-Hans"
    assert normalize_locale_code("zh_TW") == "zh-Hans"
    assert normalize_locale_code("en") == "en"
    assert normalize_locale_code("en-US") == "en"
    # Unsupported locales fall back to English.
    assert normalize_locale_code("ja") == "en"
    assert normalize_locale_code("ko-KR") == "en"
    assert normalize_locale_code("de-DE") == "en"


def test_resolve_language_zh_hans():
    config = resolve_language_config("zh-Hans")
    assert isinstance(config, LanguageConfig)
    assert config.lang_id == "zh-Hans"
    assert config.apple_locale == "zh_CN"
    assert "zh-Hans" in config.apple_languages or "zh-Hans-CN" in config.apple_languages
    assert config.posix_lang == "zh_CN.UTF-8"
    assert config.chromium_lang == "zh-CN"


def test_resolve_language_en():
    config = resolve_language_config("en")
    assert config.apple_locale == "en_US"
    assert "en-US" in config.apple_languages
    assert config.posix_lang == "en_US.UTF-8"
    assert config.chromium_lang == "en-US"


def test_resolve_language_unsupported_falls_back_to_en():
    for lang in ("ja", "ko", "de", "fr", "es", "ru", "unknown_lang"):
        config = resolve_language_config(lang)
        assert config.lang_id == "en"
        assert config.apple_locale == "en_US"
        assert config.chromium_lang == "en-US"


def test_resolve_language_zh_hant_maps_to_zh_hans():
    config = resolve_language_config("zh-Hant")
    assert config.lang_id == "zh-Hans"
    assert config.apple_locale == "zh_CN"
    assert config.posix_lang == "zh_CN.UTF-8"
    assert config.chromium_lang == "zh-CN"


def test_resolve_language_system_mock():
    with patch("twinspace.core.locale.get_system_apple_languages", return_value=["zh-Hans-CN", "en"]), \
         patch("twinspace.core.locale.get_system_apple_locale", return_value="zh_CN"):
        config = resolve_language_config("system")
        assert config.lang_id == "system"
        assert config.apple_locale == "zh_CN"
        assert "zh-Hans-CN" in config.apple_languages
        assert config.posix_lang == "zh_CN.UTF-8"
        assert config.chromium_lang == "zh-CN"


def test_build_language_wrapper_snippet_default_cocoa():
    env_snippet, args = build_language_wrapper_snippet("zh-Hans")
    assert "export LANG=\"zh_CN.UTF-8\"" in env_snippet
    assert "export LC_ALL=\"zh_CN.UTF-8\"" in env_snippet
    assert "GlobalPreferences.plist" in env_snippet
    assert "-AppleLanguages" in args
    assert "-AppleLocale" in args
    assert "zh_CN" in args
    assert "--lang=" not in " ".join(args)


def test_build_language_wrapper_snippet_chromium():
    env_snippet, args = build_language_wrapper_snippet("zh-Hans", app_type="chromium")
    assert "export LANG=\"zh_CN.UTF-8\"" in env_snippet
    assert "--lang=zh-CN" in args
    assert "-AppleLanguages" not in args
    assert "-AppleLocale" not in args


def test_build_language_wrapper_snippet_electron():
    env_snippet, args = build_language_wrapper_snippet("en", app_type="electron")
    assert "export LANG=\"en_US.UTF-8\"" in env_snippet
    assert "--lang=en-US" in args
    assert "-AppleLanguages" not in args
    assert "-AppleLocale" not in args


def test_build_language_wrapper_snippet_cocoa():
    env_snippet, args = build_language_wrapper_snippet("zh-Hans", app_type="cocoa")
    assert "-AppleLanguages" in args
    assert "-AppleLocale" in args
    assert "--lang=" not in " ".join(args)


def test_build_language_wrapper_snippet_firefox():
    env_snippet, args = build_language_wrapper_snippet("zh-Hans", app_type="firefox")
    assert "export LANG=\"zh_CN.UTF-8\"" in env_snippet
    assert args == []


def test_build_language_wrapper_snippet_generic():
    env_snippet, args = build_language_wrapper_snippet("zh-Hans", app_type="generic")
    assert "export LANG=\"zh_CN.UTF-8\"" in env_snippet
    assert args == []


def test_build_language_wrapper_snippet_system_none():
    env_snippet, args = build_language_wrapper_snippet(None, app_type="cocoa")
    assert "export LANG=" in env_snippet
    assert "-AppleLanguages" in args
