"""Locale and Language environment resolver for TwinSpace."""

import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

from twinspace.core.logger import get_logger

logger = get_logger("core.locale")

SUPPORTED_LANGUAGES: dict[str, dict[str, Any]] = {
    "system": {
        "label_key": "lang_system",
        "apple_locale": "zh_CN",
        "apple_languages": ["zh-Hans-CN", "zh-Hans", "en"],
        "posix_lang": "zh_CN.UTF-8",
        "chromium_lang": "zh-CN",
    },
    "zh-Hans": {
        "label_key": "lang_zh_hans",
        "apple_locale": "zh_CN",
        "apple_languages": ["zh-Hans-CN", "zh-Hans", "en"],
        "posix_lang": "zh_CN.UTF-8",
        "chromium_lang": "zh-CN",
    },
    "en": {
        "label_key": "lang_en",
        "apple_locale": "en_US",
        "apple_languages": ["en-US", "en"],
        "posix_lang": "en_US.UTF-8",
        "chromium_lang": "en-US",
    },
}


@dataclass
class LanguageConfig:
    lang_id: str
    apple_languages: list[str] = field(default_factory=list)
    apple_locale: str = "zh_CN"
    posix_lang: str = "zh_CN.UTF-8"
    chromium_lang: str = "zh-CN"


def get_system_apple_languages() -> list[str]:
    """Retrieve host system AppleLanguages from macOS defaults."""
    try:
        res = subprocess.run(
            ["defaults", "read", "-g", "AppleLanguages"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            matches = re.findall(r'"([^"]+)"', res.stdout)
            if matches:
                return matches
    except Exception as e:
        logger.debug(f"Failed to read AppleLanguages from defaults: {e}")
    return ["zh-Hans-CN", "zh-Hans", "en"]


def get_system_apple_locale() -> str:
    """Retrieve host system AppleLocale from macOS defaults."""
    try:
        res = subprocess.run(
            ["defaults", "read", "-g", "AppleLocale"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception as e:
        logger.debug(f"Failed to read AppleLocale from defaults: {e}")
    return "zh_CN"


def normalize_locale_code(language: str | None) -> str:
    """Normalize input language code to a SUPPORTED_LANGUAGES key."""
    if not language or language == "system":
        return "system"
    clean = language.strip().replace("_", "-").lower()
    if clean.startswith("zh") or "hant" in clean:
        return "zh-Hans"
    if clean.startswith("en"):
        return "en"
    return "en"


def resolve_language_config(language: str | None) -> LanguageConfig:
    """Resolve a language identifier into concrete LanguageConfig."""
    lang_key = normalize_locale_code(language)

    if lang_key == "system":
        sys_langs = get_system_apple_languages()
        primary_lang = sys_langs[0] if sys_langs else "zh-Hans"

        if "zh" in primary_lang.lower():
            return LanguageConfig(
                lang_id="system",
                apple_languages=["zh-Hans-CN", "zh-Hans", "en"],
                apple_locale="zh_CN",
                posix_lang="zh_CN.UTF-8",
                chromium_lang="zh-CN",
            )
        return LanguageConfig(
            lang_id="system",
            apple_languages=["en-US", "en"],
            apple_locale="en_US",
            posix_lang="en_US.UTF-8",
            chromium_lang="en-US",
        )

    preset = SUPPORTED_LANGUAGES[lang_key]
    return LanguageConfig(
        lang_id=lang_key,
        apple_languages=list(preset["apple_languages"]),
        apple_locale=str(preset["apple_locale"]),
        posix_lang=str(preset["posix_lang"]),
        chromium_lang=str(preset["chromium_lang"]),
    )


def build_language_wrapper_snippet(
    language: str | None,
    app_type: str = "cocoa",
) -> tuple[str, list[str]]:
    """Build shell export commands and launch arguments for wrapper script based on app_type."""
    cfg = resolve_language_config(language)

    env_lines = [
        f'export LANG="{cfg.posix_lang}"',
        f'export LC_ALL="{cfg.posix_lang}"',
    ]

    # Preference directory sync block for isolated HOME
    pref_sync_block = (
        'REAL_USER_HOME="${REAL_USER_HOME:-$HOME}"\n'
        'if [ -n "$HOME" ] && [ "$HOME" != "$REAL_USER_HOME" ]; then\n'
        '    mkdir -p "$HOME/Library/Preferences"\n'
        '    if [ ! -f "$HOME/Library/Preferences/.GlobalPreferences.plist" ] && [ -f "$REAL_USER_HOME/Library/Preferences/.GlobalPreferences.plist" ]; then\n'
        '        cp "$REAL_USER_HOME/Library/Preferences/.GlobalPreferences.plist" "$HOME/Library/Preferences/.GlobalPreferences.plist" 2>/dev/null || true\n'
        '    fi\n'
        '    if [ ! -f "$HOME/.CFUserTextEncoding" ] && [ -f "$REAL_USER_HOME/.CFUserTextEncoding" ]; then\n'
        '        cp "$REAL_USER_HOME/.CFUserTextEncoding" "$HOME/.CFUserTextEncoding" 2>/dev/null || true\n'
        '    fi\n'
        'fi'
    )

    env_snippet = "\n".join(env_lines) + "\n" + pref_sync_block

    normalized_type = (app_type or "cocoa").lower()
    if normalized_type in ("chromium", "electron"):
        launch_args = [f"--lang={cfg.chromium_lang}"]
    elif normalized_type == "cocoa":
        # Format Cocoa -AppleLanguages array argument: '("zh-Hans-CN", "zh-Hans", "en")'
        quoted_langs = ", ".join(f'"{l}"' for l in cfg.apple_languages)
        apple_langs_arg = f"({quoted_langs})"
        launch_args = [
            "-AppleLanguages",
            apple_langs_arg,
            "-AppleLocale",
            cfg.apple_locale,
        ]
    else:  # firefox, generic, etc.
        launch_args = []

    return env_snippet, launch_args
