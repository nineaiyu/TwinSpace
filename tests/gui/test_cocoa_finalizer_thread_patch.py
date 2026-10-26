"""Guard tests: Toga Cocoa finalizers must only touch AppKit on the main thread."""

import sys
import threading
from types import SimpleNamespace

import pytest

from twinspace.gui import patch_cocoa

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Cocoa-only behaviour")


class _FakeNativeView:
    def __init__(self):
        self.removed = []

    def removeConstraint(self, constraint):
        self.removed.append(constraint)


def _make_constraints():
    """Build a Constraints instance without constructing native layout objects."""
    from toga_cocoa.constraints import Constraints

    constraints = object.__new__(Constraints)
    constraints.widget = SimpleNamespace()
    native = _FakeNativeView()
    constraints._container = SimpleNamespace(native=native)
    constraints.width_constraint = "width"
    constraints.height_constraint = "height"
    constraints.left_constraint = "left"
    constraints.top_constraint = "top"
    return constraints, native


def _run_in_thread(func) -> None:
    thread = threading.Thread(target=func)
    thread.start()
    thread.join()


def test_background_finalizer_is_deferred_to_main_thread():
    patch_cocoa.patch_cocoa_widgets()
    constraints, native = _make_constraints()
    before = patch_cocoa.pending_cocoa_work_count()

    _run_in_thread(constraints._remove_constraints)

    assert native.removed == []
    assert patch_cocoa.pending_cocoa_work_count() == before + 1

    assert patch_cocoa.drain_pending_cocoa_work() >= 1
    assert native.removed == ["width", "height", "left", "top"]


def test_main_thread_finalizer_runs_immediately():
    patch_cocoa.patch_cocoa_widgets()
    constraints, native = _make_constraints()

    constraints._remove_constraints()

    assert native.removed == ["width", "height", "left", "top"]


def test_drain_is_ignored_off_main_thread():
    patch_cocoa.patch_cocoa_widgets()
    constraints, native = _make_constraints()
    _run_in_thread(constraints._remove_constraints)

    results = []
    _run_in_thread(lambda: results.append(patch_cocoa.drain_pending_cocoa_work()))

    assert results == [0]
    assert native.removed == []

    patch_cocoa.drain_pending_cocoa_work()
    assert native.removed == ["width", "height", "left", "top"]


def test_patch_install_is_idempotent():
    patch_cocoa.patch_cocoa_widgets()
    patch_cocoa.patch_cocoa_widgets()

    constraints, native = _make_constraints()
    before = patch_cocoa.pending_cocoa_work_count()
    _run_in_thread(constraints._remove_constraints)

    assert patch_cocoa.pending_cocoa_work_count() == before + 1
    patch_cocoa.drain_pending_cocoa_work()
    assert native.removed == ["width", "height", "left", "top"]


def test_main_window_finalizer_is_deferred_to_main_thread():
    from toga_cocoa.window import MainWindow

    patch_cocoa.patch_cocoa_widgets()
    purged = []
    window = object.__new__(MainWindow)
    window.purge_toolbar = lambda: purged.append(True)

    _run_in_thread(lambda: MainWindow.__del__(window))

    assert purged == []
    patch_cocoa.drain_pending_cocoa_work()
    assert purged == [True]
