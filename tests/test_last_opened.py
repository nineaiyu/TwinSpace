"""Tests for recording and rendering the "last opened" timestamp."""

from datetime import datetime, timedelta

from twinspace.core.i18n import set_language
from twinspace.core.state import CloneRecord, StateManager
from twinspace.core.timestamps import format_last_opened, parse_iso_timestamp


def _local_time(days_ago: int, hour: int, minute: int, *, now: datetime) -> str:
    moment = (now - timedelta(days=days_ago)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return moment.isoformat()


def _now() -> datetime:
    return datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)


def _record(clone_name: str, dest: str) -> CloneRecord:
    return CloneRecord(
        clone_name=clone_name,
        source_app="App",
        source_path="/Applications/App.app",
        bundle_id="com.example.app",
        strategy="hard_clone",
        dest_path=dest,
        data_dir=f"/Data/{clone_name}",
        created_at="2026-10-01T00:00:00+00:00",
    )


def test_parse_iso_timestamp_variants():
    assert parse_iso_timestamp("") is None
    assert parse_iso_timestamp("not a date") is None
    assert parse_iso_timestamp("2026-10-28T05:30:00Z") is not None
    naive = parse_iso_timestamp("2026-10-28T05:30:00")
    assert naive is not None and naive.tzinfo is not None


def test_format_last_opened_english_buckets():
    set_language("en")
    now = _now()

    today = format_last_opened(_local_time(0, 5, 30, now=now), now=now)
    yesterday = format_last_opened(_local_time(1, 6, 20, now=now), now=now)
    day_before = format_last_opened(_local_time(2, 8, 30, now=now), now=now)
    five_days = format_last_opened(_local_time(5, 9, 0, now=now), now=now)

    assert today == "Last opened today at 5:30"
    assert yesterday == "Last opened yesterday at 6:20"
    assert day_before == "Last opened the day before yesterday at 8:30"
    assert five_days == "Last opened 5 days ago"


def test_format_last_opened_english_compact():
    set_language("en")
    now = _now()

    assert format_last_opened(_local_time(0, 5, 30, now=now), compact=True, now=now) == "Today 5:30"
    assert format_last_opened(_local_time(1, 6, 20, now=now), compact=True, now=now) == "Yesterday 6:20"
    assert format_last_opened(_local_time(2, 8, 30, now=now), compact=True, now=now) == "2 days ago"
    assert format_last_opened(_local_time(5, 9, 0, now=now), compact=True, now=now) == "5 days ago"


def test_format_last_opened_chinese_buckets():
    set_language("zh")
    now = _now()

    assert format_last_opened(_local_time(0, 5, 30, now=now), now=now) == "今天 5:30 打开"
    assert format_last_opened(_local_time(1, 6, 20, now=now), now=now) == "昨天 6:20 打开"
    assert format_last_opened(_local_time(2, 8, 30, now=now), now=now) == "前天 8:30 打开"
    assert format_last_opened(_local_time(5, 9, 0, now=now), now=now) == "5 天前打开"
    assert format_last_opened(_local_time(2, 8, 30, now=now), compact=True, now=now) == "前天 8:30 打开"
    assert format_last_opened(_local_time(5, 9, 0, now=now), compact=True, now=now) == "5 天前打开"


def test_format_last_opened_returns_empty_for_missing_value():
    assert format_last_opened("") == ""
    assert format_last_opened("garbage") == ""


def test_mark_opened_by_clone_name(tmp_path):
    manager = StateManager(state_file=tmp_path / "clones.yaml")
    manager.add(_record("App1", str(tmp_path / "App1.app")))

    result = manager.mark_opened("App1", timestamp="2026-10-28T05:30:00+00:00")

    assert result == ("App1", "2026-10-28T05:30:00+00:00")
    assert manager.get("App1").last_opened_at == "2026-10-28T05:30:00+00:00"


def test_mark_opened_by_bundle_path(tmp_path):
    manager = StateManager(state_file=tmp_path / "clones.yaml")
    manager.add(_record("App1", str(tmp_path / "App1.app")))

    result = manager.mark_opened(
        dest_path=str(tmp_path / "App1.app"), timestamp="2026-10-28T06:20:00+00:00"
    )

    assert result == ("App1", "2026-10-28T06:20:00+00:00")
    assert manager.get("App1").last_opened_at == "2026-10-28T06:20:00+00:00"


def test_mark_opened_ignores_unknown_targets(tmp_path):
    manager = StateManager(state_file=tmp_path / "clones.yaml")
    manager.add(_record("App1", str(tmp_path / "App1.app")))

    assert manager.mark_opened("Missing") is None
    assert manager.mark_opened(dest_path=str(tmp_path / "Other.app")) is None
    assert manager.mark_opened() is None


def test_mark_opened_dedupes_the_click_and_the_launch_notification(tmp_path):
    manager = StateManager(state_file=tmp_path / "clones.yaml")
    manager.add(_record("App1", str(tmp_path / "App1.app")))

    first = manager.mark_opened("App1", timestamp="2026-10-28T05:30:00+00:00")
    second = manager.mark_opened(
        dest_path=str(tmp_path / "App1.app"), timestamp="2026-10-28T05:30:02+00:00"
    )

    assert first == second == ("App1", "2026-10-28T05:30:00+00:00")
    assert manager.get("App1").last_opened_at == "2026-10-28T05:30:00+00:00"


def test_mark_opened_overwrites_older_timestamps(tmp_path):
    manager = StateManager(state_file=tmp_path / "clones.yaml")
    manager.add(_record("App1", str(tmp_path / "App1.app")))

    manager.mark_opened("App1", timestamp="2026-10-28T05:30:00+00:00")
    manager.mark_opened("App1", timestamp="2026-10-28T09:00:00+00:00")

    assert manager.get("App1").last_opened_at == "2026-10-28T09:00:00+00:00"
