"""Test release manifest (latest.json) generator."""

import hashlib
import json
from pathlib import Path


def generate_manifest(dist_dir: Path, version: str, pub_date: str) -> Path:
    dmg_file = dist_dir / f"TwinSpace-{version}-arm64.dmg"
    notes_file = dist_dir / "release_notes.md"
    manifest_file = dist_dir / "latest.json"

    dmg_bytes = dmg_file.read_bytes()
    sha256 = hashlib.sha256(dmg_bytes).hexdigest()
    notes = notes_file.read_text(encoding="utf-8") if notes_file.exists() else ""

    data = {
        "version": version,
        "notes": notes,
        "pub_date": pub_date,
        "platforms": {
            "darwin-aarch64": {
                "checksum": sha256,
                "url": f"https://github.com/nineaiyu/TwinSpace/releases/download/v{version}/TwinSpace-{version}-arm64.dmg",
            }
        },
    }
    manifest_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_file


def test_generate_manifest(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    dmg = dist_dir / "TwinSpace-1.6.0-arm64.dmg"
    dmg.write_bytes(b"mock dmg binary data")
    notes = dist_dir / "release_notes.md"
    notes.write_text("## Changelog\n- Fix bug", encoding="utf-8")

    manifest = generate_manifest(dist_dir, "1.6.0", "2026-09-13T12:00:00.000Z")
    assert manifest.exists()

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["version"] == "1.6.0"
    assert data["notes"] == "## Changelog\n- Fix bug"
    assert data["pub_date"] == "2026-09-13T12:00:00.000Z"
    assert "darwin-aarch64" in data["platforms"]
    plat = data["platforms"]["darwin-aarch64"]
    assert len(plat["checksum"]) == 64
    assert plat["url"] == "https://github.com/nineaiyu/TwinSpace/releases/download/v1.6.0/TwinSpace-1.6.0-arm64.dmg"
