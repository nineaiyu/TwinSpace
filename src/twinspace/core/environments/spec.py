"""Portable environment specifications and built-in templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

from twinspace.validation import validate_clone_name

from .apps import KNOWN_APPS, app_for_key

SCHEMA_VERSION = 1


@dataclass
class EnvironmentAppSpec:
    key: str
    clone_name: str = ""
    env_overrides: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"key": self.key}
        if self.clone_name:
            data["clone_name"] = self.clone_name
        if self.env_overrides:
            data["env_overrides"] = dict(self.env_overrides)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvironmentAppSpec":
        if not isinstance(data, dict):
            raise ValueError("Each environment app must be a mapping.")
        key = str(data.get("key", "")).strip()
        if app_for_key(key) is None:
            raise ValueError(f"Unknown app key: {key!r}")
        clone_name = str(data.get("clone_name", "") or "").strip()
        if clone_name:
            validate_clone_name(clone_name)
        raw_overrides = data.get("env_overrides") or {}
        if not isinstance(raw_overrides, dict):
            raise ValueError("env_overrides must be a mapping.")
        overrides = {str(k): str(v) for k, v in raw_overrides.items()}
        return cls(key=key, clone_name=clone_name, env_overrides=overrides)


@dataclass
class EnvironmentSpec:
    name: str
    apps: list[EnvironmentAppSpec] = field(default_factory=list)
    version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_clone_name(self.name)
        if self.version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported environment schema version: {self.version}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "apps": [app.to_dict() for app in self.apps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvironmentSpec":
        if not isinstance(data, dict):
            raise ValueError("Environment file must contain a mapping.")
        version = int(data.get("version", SCHEMA_VERSION))
        if version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported environment schema version: {version}")
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("Environment file is missing a name.")
        raw_apps = data.get("apps") or []
        if not isinstance(raw_apps, list) or not raw_apps:
            raise ValueError("Environment file must contain at least one app.")
        apps = [EnvironmentAppSpec.from_dict(item) for item in raw_apps]
        seen: set[str] = set()
        for app in apps:
            if app.key in seen:
                raise ValueError(f"Duplicate app key in environment file: {app.key}")
            seen.add(app.key)
        return cls(name=name, apps=apps, version=version)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> "EnvironmentSpec":
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid environment YAML: {exc}") from exc
        return cls.from_dict(data or {})


TEMPLATES: dict[str, tuple[str, ...]] = {
    "all": tuple(app.key for app in KNOWN_APPS),
    "phone": ("chrome", "zcode", "workbuddy", "codebuddy"),
    "dev": ("chrome", "codebuddy", "qoder", "trae"),
}


def template_app_keys(name: str) -> tuple[str, ...]:
    try:
        return TEMPLATES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(TEMPLATES))
        raise ValueError(f"Unknown template {name!r}. Available: {choices}") from exc
