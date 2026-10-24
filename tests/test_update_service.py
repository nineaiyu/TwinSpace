"""Unit tests for UpdateService."""

import asyncio
import hashlib
from unittest.mock import MagicMock, patch

import pytest

from twinspace.gui.services.update_service import (
    UpdateInfo,
    UpdateService,
    _parse_version,
)


def test_parse_version():
    assert _parse_version("1.6.0") == (1, 6, 0)
    assert _parse_version("v1.6.0") == (1, 6, 0)
    assert _parse_version("2.10.1") > _parse_version("2.9.5")
    assert _parse_version("1.6.1") > _parse_version("1.6.0")
    assert _parse_version("1.6.0") == _parse_version("1.6.0")


def test_check_for_updates_has_newer():
    async def _test():
        service = UpdateService()
        mock_payload = {
            "version": "99.0.0",
            "notes": "Test notes",
            "pub_date": "2026-09-13T12:00:00.000Z",
            "platforms": {
                "darwin-aarch64": {
                    "checksum": "abc123sha",
                    "url": "https://example.com/TwinSpace-99.0.0-arm64.dmg",
                }
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_payload

        with patch("requests.get", return_value=mock_resp):
            info = await service.check_for_updates()
            assert info is not None
            assert info.version == "99.0.0"
            assert info.download_url == "https://example.com/TwinSpace-99.0.0-arm64.dmg"
            assert info.checksum == "abc123sha"

    asyncio.run(_test())


def test_check_for_updates_already_latest():
    async def _test():
        service = UpdateService()
        mock_payload = {
            "version": "0.0.1",
            "notes": "Old notes",
            "pub_date": "2020-01-01T00:00:00.000Z",
            "platforms": {
                "darwin-aarch64": {
                    "checksum": "abc",
                    "url": "https://example.com/old.dmg",
                }
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_payload

        with patch("requests.get", return_value=mock_resp):
            info = await service.check_for_updates()
            assert info is None

    asyncio.run(_test())


def test_check_for_updates_request_error():
    async def _test():
        service = UpdateService()
        with (
            patch("requests.get", side_effect=Exception("Connection refused")),
            pytest.raises(Exception, match="Connection refused"),
        ):
            await service.check_for_updates()

    asyncio.run(_test())


def test_download_and_verify_checksum_mismatch(tmp_path):
    async def _test():
        service = UpdateService()
        info = UpdateInfo(
            version="2.0.0",
            notes="Notes",
            pub_date="2026-09-13T00:00:00Z",
            checksum="expected_sha_hex_but_will_differ",
            download_url="https://example.com/TwinSpace-2.0.0-arm64.dmg",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": "12"}
        mock_resp.iter_content.return_value = [b"mock content"]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        progress_calls = []
        def on_progress(downloaded, total):
            progress_calls.append((downloaded, total))

        with (
            patch("requests.get", return_value=mock_resp),
            patch.object(service, "_get_download_path", return_value=tmp_path / "test.dmg"),
            pytest.raises(ValueError, match="Checksum mismatch"),
        ):
            await service.download_and_install(info, on_progress)

        assert len(progress_calls) > 0
        assert not (tmp_path / "test.dmg").exists()

    asyncio.run(_test())


def test_download_and_install_success(tmp_path):
    async def _test():
        service = UpdateService()
        test_content = b"valid installer binary content"
        test_sha = hashlib.sha256(test_content).hexdigest()

        info = UpdateInfo(
            version="2.0.0",
            notes="Notes",
            pub_date="2026-09-13T00:00:00Z",
            checksum=test_sha,
            download_url="https://example.com/TwinSpace-2.0.0-arm64.dmg",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": str(len(test_content))}
        mock_resp.iter_content.return_value = [test_content]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        commands_run = []
        def mock_subprocess_run(cmd, *args, **kwargs):
            commands_run.append(cmd)
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            res.stderr = ""
            return res

        dmg_file = tmp_path / "test.dmg"
        mount_dir = tmp_path / "mnt"
        mount_dir.mkdir()
        mock_app = mount_dir / "TwinSpace.app"
        mock_app.mkdir()
        fake_target = tmp_path / "FakeTwinSpace.app"

        with (
            patch("requests.get", return_value=mock_resp),
            patch.object(service, "_get_download_path", return_value=dmg_file),
            patch.object(service, "_get_target_app_path", return_value=fake_target),
            patch("twinspace.gui.services.update_service.tempfile.mkdtemp", return_value=str(mount_dir)),
            patch("subprocess.run", side_effect=mock_subprocess_run),
        ):
            await service.download_and_install(info)

        # Check that attach, ditto, and detach were executed
        assert any(c[0] == "hdiutil" and c[1] == "attach" for c in commands_run)
        assert any(c[0] == "ditto" for c in commands_run)
        assert any(c[0] == "hdiutil" and c[1] == "detach" for c in commands_run)
        # Temporary DMG should be deleted
        assert not dmg_file.exists()

    asyncio.run(_test())


def test_download_and_install_with_status_callbacks(tmp_path):
    async def _test():
        service = UpdateService()
        test_content = b"content"
        test_sha = hashlib.sha256(test_content).hexdigest()

        info = UpdateInfo(
            version="2.0.0",
            notes="Notes",
            pub_date="2026-09-13T00:00:00Z",
            checksum=test_sha,
            download_url="https://example.com/TwinSpace-2.0.0-arm64.dmg",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": str(len(test_content))}
        mock_resp.iter_content.return_value = [test_content]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        commands_run = []
        def mock_subprocess_run(cmd, *args, **kwargs):
            commands_run.append(cmd)
            res = MagicMock()
            res.returncode = 0
            return res

        dmg_file = tmp_path / "test.dmg"
        mount_dir = tmp_path / "mnt"
        mount_dir.mkdir()
        mock_app = mount_dir / "TwinSpace.app"
        mock_app.mkdir()
        fake_target = tmp_path / "FakeTwinSpace.app"

        status_records = []

        with (
            patch("requests.get", return_value=mock_resp),
            patch.object(service, "_get_download_path", return_value=dmg_file),
            patch.object(service, "_get_target_app_path", return_value=fake_target),
            patch("twinspace.gui.services.update_service.tempfile.mkdtemp", return_value=str(mount_dir)),
            patch("subprocess.run", side_effect=mock_subprocess_run),
        ):
            await service.download_and_install(
                info,
                on_status=status_records.append,
            )

        assert "downloading" in status_records
        assert "verifying" in status_records
        assert "installing" in status_records
        assert any(c[0] == "xattr" and c[1] == "-cr" for c in commands_run)

    asyncio.run(_test())


def test_configured_proxy_resolution():
    from twinspace.gui.services.update_service import _get_configured_proxies

    with patch("twinspace.core.config.get_config_value", return_value={"enabled": False}):
        assert _get_configured_proxies() is None

    with (
        patch("twinspace.core.config.get_config_value", return_value={
            "enabled": True,
            "type": "socks5",
            "host": "127.0.0.1",
            "port": 1080,
            "username": "user",
        }),
        patch("twinspace.core.keychain.get_default_proxy_password", return_value="pass123"),
    ):
        proxies = _get_configured_proxies()
        assert proxies is not None
        assert "socks5://user:pass123@127.0.0.1:1080" in proxies["https"]
