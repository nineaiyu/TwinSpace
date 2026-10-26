"""Deterministic simulated device identity for environments and standalone clones.

Apps inside one environment must report the same machine identity (they would run
on one physical Mac), while different environments stay isolated. Values are
derived from a stable scope string instead of being stored, so they survive
state-file edits and can be previewed in the UI without rebuilding a clone.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_SERIAL_ALPHABET = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"


@dataclass(frozen=True)
class DeviceIdentity:
    """Simulated hardware values shared by every app in one scope."""

    scope: str
    platform_uuid: str
    serial: str
    seed: str
    hostname: str


def environment_scope(name: str) -> str:
    """Return the identity scope shared by all apps in an environment."""
    return f"env|{name}"


def clone_scope(clone_name: str, new_bundle_id: str) -> str:
    """Return the identity scope of a standalone clone."""
    return f"clone|{clone_name}|{new_bundle_id}"


def identity_for_environment(name: str) -> DeviceIdentity:
    """Return the simulated identity shared by apps in ``name``."""
    return _build_identity(environment_scope(name), name)


def identity_for_clone(
    clone_name: str,
    new_bundle_id: str,
    env_group: str = "",
) -> DeviceIdentity:
    """Return the simulated identity for a clone record."""
    if env_group:
        return identity_for_environment(env_group)
    return _build_identity(clone_scope(clone_name, new_bundle_id), clone_name)


def keychain_prefix(clone_name: str, new_bundle_id: str) -> str:
    """Return a stable, filesystem/keychain-safe namespace prefix for a clone."""
    digest = hashlib.sha256(f"{clone_name}|{new_bundle_id}".encode()).hexdigest()[:16]
    return f"twinspace.{digest}."


def instance_number(clone_name: str, new_bundle_id: str) -> str:
    """Return a stable numeric instance id used by multi-instance launch switches."""
    match = re.search(r"(\d+)$", clone_name)
    if match:
        try:
            number = int(match.group(1))
            if 1 <= number <= 9999:
                return str(number)
        except ValueError:
            pass
    digest = hashlib.sha256(f"{clone_name}|{new_bundle_id}".encode()).hexdigest()
    return str(1000 + int(digest[:8], 16) % 9000)


def _build_identity(scope: str, label: str) -> DeviceIdentity:
    uuid_digest = hashlib.sha256(f"{scope}|platform-uuid".encode()).hexdigest()
    serial_digest = hashlib.sha256(f"{scope}|platform-serial".encode()).hexdigest()
    seed_digest = hashlib.sha256(f"{scope}|device-seed".encode()).hexdigest()[:16]
    hostname_digest = hashlib.sha256(f"{scope}|hostname".encode()).hexdigest()[:6]

    serial_value = int(serial_digest[:16], 16)
    serial_chars = []
    for _ in range(9):
        serial_value, remainder = divmod(serial_value, len(_SERIAL_ALPHABET))
        serial_chars.append(_SERIAL_ALPHABET[remainder])

    slug = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")
    slug = slug[:24].strip("-") or "clone"

    return DeviceIdentity(
        scope=scope,
        platform_uuid=_format_uuid(uuid_digest[:32].upper()),
        serial="C02" + "".join(serial_chars),
        seed=seed_digest,
        hostname=f"{slug}-{hostname_digest}.local",
    )


def _format_uuid(raw: str) -> str:
    chars = list(raw)
    chars[12] = "4"
    chars[16] = "89AB"[int(chars[16], 16) % 4]
    text = "".join(chars)
    return f"{text[:8]}-{text[8:12]}-{text[12:16]}-{text[16:20]}-{text[20:]}"
