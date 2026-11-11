"""Data-directory size computation with a short-lived cache.

Sizes feed the clone table's "Data Size" column, the detail window and cache
cleanup estimates. Walking multi-GB trees is expensive, so results are cached
per path for a few minutes and refreshed in worker threads only.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Iterable

# data_dir -> (computed_at monotonic, size in bytes)
_SIZE_CACHE: dict[str, tuple[float, int]] = {}
_SIZE_TTL = 1800.0


def dir_size(path: Path | str) -> int:
    """Recursive byte size of ``path``; 0 when missing or unreadable."""
    total = 0
    root = Path(path)
    if not root.is_dir():
        return 0
    for current, _dirs, files in os.walk(root, onerror=lambda _e: None):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(current, name))
            except OSError:
                continue
    return total


def compute_data_sizes(records: Iterable[Any]) -> dict[str, int]:
    """Map ``clone_name -> data size`` for the given records (cached)."""
    now = time.monotonic()
    result: dict[str, int] = {}
    for record in records:
        data_dir = str(getattr(record, "data_dir", "") or "")
        if not data_dir:
            continue
        name = record.clone_name
        cached = _SIZE_CACHE.get(data_dir)
        if cached is not None and now - cached[0] < _SIZE_TTL:
            result[name] = cached[1]
            continue
        size = dir_size(data_dir)
        _SIZE_CACHE[data_dir] = (now, size)
        result[name] = size
    return result


def invalidate_size_cache(path: Path | str | None = None) -> None:
    """Forget cached sizes (e.g. after cache cleanup changed the tree)."""
    if path is None:
        _SIZE_CACHE.clear()
    else:
        _SIZE_CACHE.pop(str(path), None)


def format_size(size: int) -> str:
    """Human-readable byte size ("12.3 MB")."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
