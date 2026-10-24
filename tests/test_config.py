"""Tests for TwinSpace core config management (YAML format)."""

import json
from pathlib import Path

import yaml

from twinspace.core import config
from twinspace.core.config import (
    DEFAULT_CONFIG_FILE,
    get_config_value,
    load_config,
    save_config,
    set_config_value,
)


def test_default_config_file_path():
    assert DEFAULT_CONFIG_FILE.name == "config.yaml"


def test_load_config_nonexistent(tmp_path, monkeypatch):
    test_cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", test_cfg)
    monkeypatch.setattr(config, "DEFAULT_TWINSPACE_DIR", tmp_path)

    assert load_config() == {}


def test_save_and_load_config_yaml(tmp_path, monkeypatch):
    test_cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", test_cfg)
    monkeypatch.setattr(config, "DEFAULT_TWINSPACE_DIR", tmp_path)

    data = {
        "language": "zh",
        "minimize_to_tray": True,
        "custom_settings": {"nested": "value", "count": 42},
    }
    save_config(data)

    assert test_cfg.exists()
    # Check that it's valid YAML
    with open(test_cfg, "r", encoding="utf-8") as f:
        loaded_raw = yaml.safe_load(f)
    assert loaded_raw == data

    # Check via load_config
    assert load_config() == data


def test_legacy_json_fallback(tmp_path, monkeypatch):
    test_cfg_yaml = tmp_path / "config.yaml"
    test_cfg_json = tmp_path / "config.json"
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", test_cfg_yaml)
    monkeypatch.setattr(config, "DEFAULT_TWINSPACE_DIR", tmp_path)

    # Write legacy json
    legacy_data = {"language": "ja", "minimize_to_tray": False}
    with open(test_cfg_json, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)

    # Config yaml doesn't exist yet -> loads legacy json
    assert not test_cfg_yaml.exists()
    assert load_config() == legacy_data

    # Once a new setting is saved, it writes to config.yaml
    set_config_value("minimize_to_tray", True)
    assert test_cfg_yaml.exists()
    assert get_config_value("minimize_to_tray") is True
    assert get_config_value("language") == "ja"


def test_get_and_set_config_value(tmp_path, monkeypatch):
    test_cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", test_cfg)
    monkeypatch.setattr(config, "DEFAULT_TWINSPACE_DIR", tmp_path)

    assert get_config_value("non_existent", default="fallback") == "fallback"

    set_config_value("theme", "dark")
    assert get_config_value("theme") == "dark"

    set_config_value("minimize_to_tray", True)
    assert get_config_value("minimize_to_tray") is True
    assert get_config_value("theme") == "dark"


def test_corrupted_config_handling(tmp_path, monkeypatch):
    test_cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", test_cfg)
    monkeypatch.setattr(config, "DEFAULT_TWINSPACE_DIR", tmp_path)

    with open(test_cfg, "w", encoding="utf-8") as f:
        f.write("invalid: yaml: : : [}")

    assert load_config() == {}
    assert get_config_value("anything", "default") == "default"


def test_get_base_dir_and_subdirs(tmp_path, monkeypatch):
    test_cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", test_cfg)
    monkeypatch.setattr(config, "DEFAULT_TWINSPACE_DIR", tmp_path / "DefaultATB")

    # When no base_dir set, defaults to DEFAULT_TWINSPACE_DIR
    assert config.get_base_dir() == tmp_path / "DefaultATB"
    assert config.get_apps_dir() == tmp_path / "DefaultATB" / "Apps"
    assert config.get_data_dir() == tmp_path / "DefaultATB" / "Data"

    # When custom base_dir is set in config
    custom_dir = tmp_path / "CustomBase"
    set_config_value("base_dir", str(custom_dir))
    assert config.get_base_dir() == custom_dir
    assert config.get_apps_dir() == custom_dir / "Apps"
    assert config.get_data_dir() == custom_dir / "Data"


def test_check_directory_access_success(tmp_path):
    target = tmp_path / "test_access_dir"
    passed, detail = config.check_directory_access(target)
    assert passed is True
    assert detail == "OK"
    assert target.exists()
    assert target.is_dir()
    # Ensure temporary probe file is removed
    assert len(list(target.glob(".twinspace_perm_test_*"))) == 0


def test_check_directory_access_failure(tmp_path, monkeypatch):
    # Test directory creation failure
    target = tmp_path / "blocked"
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("Mock write denied")))
    passed, detail = config.check_directory_access(target)
    assert passed is False
    assert "Mock write denied" in detail
