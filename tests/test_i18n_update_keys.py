"""Tests for auto-update i18n translation keys."""

import pytest

from twinspace.core.i18n import MESSAGES, SUPPORTED_LANGUAGES, set_language, t

REQUIRED_KEYS = [
    "settings_btn_check_update",
    "update_checking",
    "update_already_latest",
    "update_found",
    "update_downloading",
    "update_verifying",
    "update_installing",
    "update_done_title",
    "update_done_msg",
    "update_error_short",
    "update_error_timeout",
    "update_error_network",
    "update_error_http",
]


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_update_keys_exist_for_all_languages(key):
    assert key in MESSAGES, f"Missing key '{key}' in MESSAGES"
    msg_dict = MESSAGES[key]
    for lang in SUPPORTED_LANGUAGES:
        assert lang in msg_dict, f"Missing language '{lang}' for key '{key}'"
        assert msg_dict[lang].strip(), f"Empty translation for '{lang}' in '{key}'"


def test_update_formatted_strings():
    set_language("zh")
    assert "v1.6.0" in t("update_already_latest", ver="1.6.0")
    assert "45%" in t("update_downloading", pct=45)
    assert "网络超时" in t("update_error_timeout")
    assert "网络连接异常" in t("update_error_network")
    assert "404" in t("update_error_http", code=404)
    assert "检查更新失败" in t("update_error_short")
    set_language(None)

