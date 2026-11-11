import copy
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from twinspace.core.config import DEFAULT_RECIPES_DIR

from .models import Recipe


class RecipeLoader:
    BUILTIN_DIR = Path(__file__).parent / "builtin"
    LOCAL_DIR: Path | None = None

    # Parsed recipe files keyed by (path, mtime_ns, size): every ``match`` used
    # to re-read and re-parse YAML from disk. File edits invalidate via mtime,
    # and callers receive a deep copy so cached data can never be mutated.
    _FILE_CACHE: dict[tuple[str, int, int], dict] = {}

    @classmethod
    def get_local_dir(cls) -> Path:
        if cls.LOCAL_DIR is not None:
            return cls.LOCAL_DIR
        return DEFAULT_RECIPES_DIR

    @classmethod
    def has_recipe(cls, bundle_id: str) -> bool:
        local_file = cls.get_local_dir() / f"{bundle_id}.yaml"
        builtin_file = cls.BUILTIN_DIR / f"{bundle_id}.yaml"
        return local_file.is_file() or builtin_file.is_file()

    @classmethod
    def get(cls, bundle_id: str) -> Recipe | None:
        local_file = cls.get_local_dir() / f"{bundle_id}.yaml"
        builtin_file = cls.BUILTIN_DIR / f"{bundle_id}.yaml"
        try:
            if local_file.is_file():
                return cls._load_file(local_file)
        except (PermissionError, OSError):
            pass
        try:
            if builtin_file.is_file():
                return cls._load_file(builtin_file)
        except (PermissionError, OSError):
            pass
        return None

    @classmethod
    def match(cls, bundle_id: str, app_path: Path | str | None = None) -> Recipe:
        recipe = cls.get(bundle_id)
        if recipe is not None:
            return recipe

        if app_path is not None:
            from twinspace.core.app_prober import AppProber

            try:
                return AppProber.probe(app_path)
            except Exception:
                pass

        return Recipe(
            bundle_id=bundle_id,
            app_name="Unknown",
            strategy="hard_clone",
        )

    @staticmethod
    def _load_file(path: Path) -> Recipe:
        key = None
        try:
            stat = path.stat()
            key = (str(path), stat.st_mtime_ns, stat.st_size)
        except OSError:
            pass
        if key is not None:
            cached = RecipeLoader._FILE_CACHE.get(key)
            if cached is not None:
                return Recipe(**copy.deepcopy(cached))
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if key is not None:
            RecipeLoader._FILE_CACHE[key] = copy.deepcopy(data)
        return Recipe(**data)
