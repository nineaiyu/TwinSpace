"""Configuration constants and path defaults for TwinSpace."""

import os
from pathlib import Path

# Pre-rebrand data root, retained so `twinspace migrate` can find existing installs.
LEGACY_TWINSPACE_DIR: Path = Path.home() / "ATBClone"

# Base configuration directory for TwinSpace
DEFAULT_TWINSPACE_DIR: Path = Path(
    os.environ.get("TWINSPACE_HOME", str(Path.home() / "TwinSpace"))
).expanduser()

# Default state file storing clone records
DEFAULT_STATE_FILE: Path = DEFAULT_TWINSPACE_DIR / "clones.yaml"

# Default root directory for application clone data storage
DEFAULT_DATA_DIR: Path = DEFAULT_TWINSPACE_DIR / "Data"

# Default directory for user-defined / override recipes
DEFAULT_RECIPES_DIR: Path = DEFAULT_TWINSPACE_DIR / "recipes"

# Default directory for wrapper applications
DEFAULT_APPS_DIR: Path = DEFAULT_TWINSPACE_DIR / "Apps"

# Default log file for runtime and operations
DEFAULT_LOG_FILE: Path = DEFAULT_TWINSPACE_DIR / "twinspace.log"

# Default YAML configuration file for user preferences (language, default paths, etc.)
DEFAULT_CONFIG_FILE: Path = DEFAULT_TWINSPACE_DIR / "config.yaml"


def legacy_base_dir_exists() -> bool:
    """True when the pre-rebrand ATBClone data root exists on this machine."""
    return LEGACY_TWINSPACE_DIR.is_dir()


def load_config() -> dict:
    """Load configuration dictionary from disk (YAML format with legacy JSON fallback)."""
    import yaml

    if DEFAULT_CONFIG_FILE.exists():
        try:
            with open(DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # Backward compatibility: fallback to legacy config.json if config.yaml does not exist
    legacy_json = DEFAULT_CONFIG_FILE.with_suffix(".json")
    if legacy_json.exists():
        import json
        try:
            with open(legacy_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    return {}


def save_config(cfg: dict) -> None:
    """Persist configuration dictionary to disk in YAML format atomically."""
    import os
    import tempfile

    import yaml

    DEFAULT_TWINSPACE_DIR.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(
        dir=DEFAULT_CONFIG_FILE.parent,
        prefix="config_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, DEFAULT_CONFIG_FILE)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise


def get_config_value(key: str, default: any = None) -> any:
    """Retrieve a single configuration value."""
    cfg = load_config()
    return cfg.get(key, default)


def set_config_value(key: str, value: any) -> None:
    """Update and persist a single configuration value."""
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)


def get_base_dir() -> Path:
    """Retrieve the base TwinSpace directory (configurable, defaults to DEFAULT_TWINSPACE_DIR)."""
    raw = get_config_value("base_dir", str(DEFAULT_TWINSPACE_DIR))
    return Path(raw) if raw else DEFAULT_TWINSPACE_DIR


def get_apps_dir() -> Path:
    """Retrieve the directory for wrapper applications."""
    return get_base_dir() / "Apps"


def get_data_dir() -> Path:
    """Retrieve the directory for application clone data storage."""
    return get_base_dir() / "Data"


def check_directory_access(path: Path) -> tuple[bool, str]:
    """Check if a directory exists (or can be created) and has read/write permissions.

    Returns:
        tuple[bool, str]: (passed, details). If passed is True, details is 'OK'.
                          If passed is False, details describes the error.
    """
    import os
    import uuid

    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, str(e)

    test_file = path / f".twinspace_perm_test_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    try:
        test_file.write_text("ok", encoding="utf-8")
        content = test_file.read_text(encoding="utf-8")
        if content != "ok":
            return False, "Read-back verification failed"
        test_file.unlink(missing_ok=True)
        return True, "OK"
    except Exception as e:
        if test_file.exists():
            try:
                test_file.unlink()
            except OSError:
                pass
        return False, str(e)

