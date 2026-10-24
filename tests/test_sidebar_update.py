"""Unit tests for sidebar update check error formatting and behavior."""

import pytest
import requests

from twinspace.core.i18n import set_language
from twinspace.gui.components.sidebar import format_update_error


@pytest.mark.parametrize(
    "lang,expected_timeout,expected_network,expected_short",
    [
        ("zh", "网络超时", "网络连接异常", "检查更新失败"),
        ("en", "Timeout", "Network error", "Update check failed"),
    ],
)
def test_format_update_error_types(lang, expected_timeout, expected_network, expected_short):
    set_language(lang)
    try:
        # 1. Timeout error
        timeout_err = requests.exceptions.ConnectTimeout("HTTPSConnectionPool: Connection timed out")
        msg = format_update_error(timeout_err)
        assert expected_timeout in msg
        assert "\n" not in msg

        # 2. Network / DNS error
        conn_err = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='raw.githubusercontent.com', port=443): Max retries exceeded "
            "with url: /nineaiyu/TwinSpace/releases/latest/download/latest.json "
            "(Caused by NewConnectionError('<urllib3.connection.HTTPSConnection object>: "
            "Failed to establish a new connection: [Errno 8] nodename nor servname provided, or not known'))"
        )
        msg = format_update_error(conn_err)
        assert expected_network in msg
        assert "\n" not in msg
        # Length should be short and well within single line boundary
        assert len(msg) < 40

        # 3. HTTP status error
        resp = requests.Response()
        resp.status_code = 404
        http_err = requests.exceptions.HTTPError("404 Client Error: Not Found", response=resp)
        msg = format_update_error(http_err)
        assert "404" in msg
        assert "\n" not in msg

        # 4. Unknown / generic exception
        generic_err = ValueError("Unexpected token in JSON")
        msg = format_update_error(generic_err)
        assert expected_short in msg
        assert "\n" not in msg
    finally:
        set_language(None)


def test_format_update_error_http_status_fallback():
    # When response object is missing but error text contains HTTP code
    http_err_without_resp = requests.exceptions.HTTPError("Server returned 502 Bad Gateway")
    msg = format_update_error(http_err_without_resp)
    assert "502" in msg
    assert "\n" not in msg


def test_on_check_update_failure_behavior():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from twinspace.gui.components.sidebar import SidebarNav

    async def _test():
        with patch.object(SidebarNav, "__init__", return_value=None):
            sidebar = SidebarNav(on_select=lambda _: None)
            sidebar.btn_check_update = MagicMock()
            sidebar.lbl_update_status = MagicMock()
            sidebar.lbl_update_status.text = ""
            sidebar.progress_bar = MagicMock()
            sidebar.progress_bar.style = MagicMock()
            sidebar.update_service = MagicMock()
            sidebar.update_service.check_for_updates = AsyncMock(
                side_effect=requests.exceptions.ConnectionError("nodename nor servname provided")
            )

            await sidebar.on_check_update()
            assert sidebar.btn_check_update.enabled is True
            assert sidebar.progress_bar.stop.called
            # Check that error text is set and single-line
            assert sidebar.lbl_update_status.text != ""
            assert "\n" not in sidebar.lbl_update_status.text

    asyncio.run(_test())

