"""Host resource mapping.

Maps host-side resources (singleton services, package manager caches, mirror /
credential configs, shell toolchains) into clone HOMEs so tools inside an
isolated clone transparently reuse the host's state instead of duplicating or
conflicting with it.

Mechanism: directory/file level symlinks from the clone's fake HOME into the
real user HOME at the same relative path (e.g. ``.orbstack``, ``.npm``,
``.zshrc``). Sockets, caches and configs appear/update inside the host
directory, so they stay visible through the link without any daemon.

Two sources of entries:
- Global switch: ``host_resources`` in ``config.yaml`` (GUI/CLI managed),
  materialised into ``HostResources.list`` next to ``config.yaml``. The clone
  launcher re-reads this file on every launch, so toggling the switch affects
  already-built clones.
- Per-clone extras: ``Recipe.host_resources`` (group keys, resource keys or
  HOME-relative paths), baked into the launcher at build time and always
  applied.

The launcher reconciles both ways: it creates missing links and unlinks links
it previously created for entries that are no longer enabled. Real directories
in the clone HOME are never touched.

Resource groups (see :data:`HOST_RESOURCE_GROUPS`):
- ``service``: host singleton daemons reachable via sockets under HOME.
- ``cache``: rebuildable package/model caches, safe to share concurrently.
- ``config``: mirror sources and credential-bearing configs (opt-in).
- ``shell``: shell rc files and version-manager toolchains (opt-in).
"""

from pathlib import Path
from typing import Any, Iterable

from twinspace.core.logger import get_logger

logger = get_logger("core.host_resources")

# Simple text list consumed by the compiled clone launcher / injected dylib.
HOST_RESOURCES_FILENAME = "HostResources.list"

# Config key storing {"enabled": bool, "selections": {group: [resource-or-path]}}.
CONFIG_KEY = "host_resources"

# Group display/iteration order; also the order paths land in the list file.
RESOURCE_GROUP_ORDER: tuple[str, ...] = ("service", "cache", "config", "shell")

# Built-in resource catalog. Every path is relative to the real user HOME;
# entries pointing at locations that don't exist on the host are skipped at
# clone launch, so listing both macOS and XDG-convention layouts is harmless.
HOST_RESOURCE_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    # Host singleton daemons: clone terminals reach the running instance
    # instead of starting a conflicting second one.
    "service": {
        "orbstack": (".orbstack", ".docker"),
        "docker": (".docker",),
        "colima": (".colima", ".docker"),
    },
    # Rebuildable caches: disk savings and no re-downloading across clones.
    "cache": {
        "pip": ("Library/Caches/pip", ".cache/pip"),
        "npm": (".npm",),
        "pnpm": ("Library/pnpm", ".config/pnpm", ".local/share/pnpm"),
        "yarn": ("Library/Caches/Yarn",),
        "uv": ("Library/Caches/uv",),
        "go": ("go", "Library/Caches/go-build"),
        "maven": (".m2",),
        "gradle": (".gradle",),
        "huggingface": (".cache/huggingface",),
        "ollama": (".ollama",),
    },
    # Mirror sources and credential-bearing configs: the clone reuses the
    # host's registry/auth state. Opt-in only — enabling a resource here lets
    # the clone read the corresponding host credentials.
    "config": {
        "npmrc": (".npmrc",),
        "pip-config": (".config/pip",),
        "git": (".gitconfig",),
        "ssh": (".ssh",),
        "netrc": (".netrc",),
        "kube": (".kube",),
    },
    # Shell rc files and version-manager toolchains: the clone terminal gets
    # the host's PATH, aliases and node/python/rust toolchains. Opt-in only —
    # host assumptions baked into rc files will apply inside clones too.
    "shell": {
        "shell-rc": (".zshrc", ".zprofile", ".zshenv", ".config/zsh"),
        "oh-my-zsh": (".oh-my-zsh",),
        "nvm": (".nvm",),
        "pyenv": (".pyenv",),
        "rust": (".cargo", ".rustup"),
    },
}

# Resources pre-selected on first use (no explicit config saved yet): the
# recommended rule is "everything except the credential-heavy trio". Caches and
# toolchain dirs are rebuildable/shared safely; singleton services are no-ops
# when the tool isn't installed; mirror-source configs and shell rc files give
# clones the host's registries and shell environment. Only .ssh/.netrc/.kube —
# machine-wide credentials with the widest blast radius — stay opt-in.
RECOMMENDED_RESOURCE_KEYS: frozenset[str] = frozenset({
    "orbstack", "docker", "colima",
    "pip", "npm", "pnpm", "yarn", "uv", "go", "maven", "gradle", "huggingface", "ollama",
    "npmrc", "pip-config", "git",
    "shell-rc", "oh-my-zsh", "nvm", "pyenv", "rust",
})


def default_selections() -> dict[str, list[str]]:
    """Recommended per-group selections used when no explicit config exists yet."""
    return {
        group: [key for key in HOST_RESOURCE_GROUPS[group] if key in RECOMMENDED_RESOURCE_KEYS]
        for group in RESOURCE_GROUP_ORDER
    }


# Upper bound of entries the compiled launcher reads from the list file.
MAX_LIST_ENTRIES = 64


def validate_resource_path(item: str) -> str:
    """Validate and normalise a HOME-relative resource path entry.

    Rejects absolute paths and ``..`` components: entries always resolve
    relative to the real user HOME and are embedded into shell/C contexts.
    """
    cleaned = (item or "").strip().strip("/")
    if not cleaned:
        raise ValueError(f"Invalid host resource entry: {item!r} is empty.")
    if (item or "").strip().startswith("/") or (item or "").strip().startswith("~"):
        raise ValueError(
            f"Invalid host resource entry: {item!r}. "
            f"Entries must be relative to the user HOME."
        )
    if any(part == ".." for part in cleaned.split("/")):
        raise ValueError(
            f"Invalid host resource entry: {item!r}. "
            f"'..' path components are not allowed."
        )
    return cleaned


def expand_entries(entries: Iterable[str]) -> list[str]:
    """Expand a mix of group keys, resource keys and raw paths, deduped, ordered."""
    paths: list[str] = []
    for entry in entries:
        name = (entry or "").strip()
        if not name:
            continue
        if name in RESOURCE_GROUP_ORDER:
            for resource in HOST_RESOURCE_GROUPS[name].values():
                for candidate in resource:
                    if candidate not in paths:
                        paths.append(candidate)
            continue
        candidates: tuple[str, ...] | None = None
        for group in HOST_RESOURCE_GROUPS.values():
            if name in group:
                candidates = group[name]
                break
        if candidates is None:
            candidates = (validate_resource_path(name),)
        for candidate in candidates:
            if candidate not in paths:
                paths.append(candidate)
    return paths


def find_resource_group(key: str) -> str | None:
    """Return the group a resource key belongs to, or None for raw paths/groups."""
    name = (key or "").strip()
    if name in RESOURCE_GROUP_ORDER:
        return name
    for group, resources in HOST_RESOURCE_GROUPS.items():
        if name in resources:
            return group
    return None


def all_managed_paths() -> list[str]:
    """Every path this feature can manage (catalog union), used for reconciliation."""
    paths: list[str] = []
    for group in RESOURCE_GROUP_ORDER:
        for candidates in HOST_RESOURCE_GROUPS[group].values():
            for candidate in candidates:
                if candidate not in paths:
                    paths.append(candidate)
    return paths


def normalize_selections(selections: Any) -> dict[str, list[str]]:
    """Normalise a raw ``selections`` value into a per-group string list dict."""
    if not isinstance(selections, dict):
        return {group: [] for group in RESOURCE_GROUP_ORDER}
    normalized: dict[str, list[str]] = {}
    for group in RESOURCE_GROUP_ORDER:
        raw = selections.get(group) or []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            logger.warning(f"Ignoring malformed {CONFIG_KEY}.selections.{group} (expected a list)")
            raw = []
        normalized[group] = [str(item) for item in raw]
    return normalized


def expand_selections_map(selections: dict[str, list[str]]) -> list[str]:
    """Expand normalised per-group selections into an ordered, deduped path list."""
    return expand_entries(
        item for group in RESOURCE_GROUP_ORDER for item in selections.get(group, [])
    )


def parse_resource_config(cfg: dict[str, Any] | None = None) -> list[str]:
    """Return the expanded enabled resource paths from a config dict (None loads from disk).

    Falls back to the recommended default selection when ``host_resources`` has
    never been saved; once a config exists it is respected exactly, including
    an explicit ``enabled: false``.
    """
    if cfg is None:
        from twinspace.core.config import load_config

        cfg = load_config()
    resource_cfg = (cfg or {}).get(CONFIG_KEY)
    if resource_cfg is None:
        return expand_selections_map(default_selections())
    if not isinstance(resource_cfg, dict) or not resource_cfg.get("enabled"):
        return []
    return expand_selections_map(normalize_selections(resource_cfg.get("selections")))


def get_resources_list_path() -> Path:
    """Return the launcher-readable resource list file path (next to config.yaml)."""
    from twinspace.core.config import get_base_dir

    return get_base_dir() / HOST_RESOURCES_FILENAME


def render_resources_list(paths: list[str]) -> str:
    """Render the plain-text list consumed by the compiled launcher."""
    lines = [
        "# Managed by TwinSpace - host resource mapping.",
        "# One HOME-relative path per line; '#' comments are ignored.",
        "# Regenerated from config.yaml via GUI settings or 'twinspace resources sync'.",
    ]
    lines.extend(paths)
    return "\n".join(lines) + "\n"


def write_resources_list(paths: list[str]) -> Path:
    """Atomically write the resource list file. An empty list means 'all off'."""
    import os
    import tempfile

    target = get_resources_list_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = render_resources_list(paths)
    temp_fd, temp_path = tempfile.mkstemp(dir=target.parent, prefix="resources_", suffix=".tmp")
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp_path, 0o644)
        os.replace(temp_path, target)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise
    return target


def sync_resources_list(cfg: dict[str, Any] | None = None) -> Path:
    """Recompute enabled resources from config and rewrite the list file."""
    paths = parse_resource_config(cfg)
    written = write_resources_list(paths)
    logger.info(f"Host resources synced ({len(paths)} path(s)): {paths}")
    return written
