"""CloneTask dataclass — bundles all parameters for a single clone operation."""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from twinspace.recipes.models import Recipe
from twinspace.validation import (
    validate_bundle_id,
    validate_clone_name,
    validate_display_name,
    validate_path_component,
)

from .device_identity import (
    DeviceIdentity,
    identity_for_clone,
)
from .device_identity import (
    instance_number as _instance_number,
)
from .device_identity import (
    keychain_prefix as _keychain_prefix,
)
from .models import AppInfo


@dataclass
class CloneTask:
    """All parameters required to perform one clone operation."""

    source: AppInfo
    dest_path: Path
    data_dir: Path
    recipe: Recipe
    clone_name: str
    new_bundle_id: str
    display_name: str | None = None  # Dock/Finder label; defaults to clone_name when None
    icon_path: Path | None = None    # Custom .icns; defaults to copying src Resources when None
    language: str = "system"         # Desired locale/language; defaults to "system"
    injection_strategy: str = "auto" # "auto" | "dylib" | "launcher"
    actual_injection_strategy: str = "auto" # Recorded actual strategy executed ("dylib" | "launcher")
    env_group: str | None = None     # Optional named environment shared by several clones
    env_dir: Path | None = None      # Shared environment directory; defaults to data_dir

    def __post_init__(self) -> None:
        """Validate every field that the engines interpolate into generated scripts.

        CloneTask is the single chokepoint shared by CLI, GUI and update flows,
        so untrusted values are rejected here before any shell script is built.
        """
        validate_clone_name(self.clone_name)
        validate_bundle_id(self.new_bundle_id, field="new_bundle_id")
        if self.display_name is not None:
            validate_display_name(self.display_name)
        if self.env_group is not None:
            validate_clone_name(self.env_group)
        validate_path_component(str(self.dest_path), field="dest_path")
        validate_path_component(str(self.data_dir), field="data_dir")
        if self.env_dir is not None:
            validate_path_component(str(self.env_dir), field="env_dir")

    @property
    def resolved_env_dir(self) -> Path:
        """Return the shared environment directory, falling back to the clone data dir."""
        return self.env_dir or self.data_dir

    @property
    def instance_number(self) -> str:
        """Return a stable numeric instance id used by apps with multi-instance switches."""
        return _instance_number(self.clone_name, self.new_bundle_id)

    @property
    def keychain_prefix(self) -> str:
        """Return a stable, filesystem/keychain-safe namespace prefix for this clone."""
        return _keychain_prefix(self.clone_name, self.new_bundle_id)

    @property
    def device_identity(self) -> DeviceIdentity:
        """Return the simulated hardware identity shared by this clone's scope."""
        return identity_for_clone(
            self.clone_name,
            self.new_bundle_id,
            self.env_group or "",
        )

    @property
    def device_identity_key(self) -> str:
        """Return the scope that shares one simulated machine identity."""
        return self.device_identity.scope

    @property
    def device_uuid(self) -> str:
        """Return the platform UUID reported through IOKit for this environment."""
        return self.device_identity.platform_uuid

    @property
    def device_serial(self) -> str:
        """Return the platform serial number reported through IOKit."""
        return self.device_identity.serial

    @property
    def device_seed(self) -> str:
        """Return the seed used to derive disk UUIDs and MAC addresses."""
        return self.device_identity.seed

    @property
    def device_hostname(self) -> str:
        """Return the hostname reported by gethostname() for this environment."""
        return self.device_identity.hostname


@contextmanager
def preserve_clone_icon(dest_path: Path) -> Iterator[Path | None]:
    """Keep the installed custom icon outside the bundle while an update rebuilds it."""
    installed_icon = dest_path / "Contents/Resources/TwinSpaceIcon.icns"
    if not installed_icon.is_file():
        yield None
        return
    with TemporaryDirectory(prefix="twinspace-icon-") as directory:
        saved_icon = Path(directory) / "TwinSpaceIcon.icns"
        shutil.copyfile(installed_icon, saved_icon)
        yield saved_icon
