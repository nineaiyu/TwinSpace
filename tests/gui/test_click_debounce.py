"""One physical click must not reach the handler twice."""

from twinspace.gui import cocoa_events


def test_repeated_clicks_inside_the_window_collapse(monkeypatch):
    now = {"value": 100.0}
    monkeypatch.setattr(cocoa_events.time, "monotonic", lambda: now["value"])
    calls: list[int] = []
    handler = cocoa_events._debounced(lambda: calls.append(1), 0.12)

    handler()
    now["value"] += 0.004  # the second recognizer of the same click
    handler()
    now["value"] += 0.006
    handler()

    assert calls == [1]


def test_click_after_the_window_is_delivered(monkeypatch):
    now = {"value": 100.0}
    monkeypatch.setattr(cocoa_events.time, "monotonic", lambda: now["value"])
    calls: list[int] = []
    handler = cocoa_events._debounced(lambda: calls.append(1), 0.12)

    handler()
    now["value"] += 0.5  # a genuinely separate click
    handler()

    assert calls == [1, 1]
