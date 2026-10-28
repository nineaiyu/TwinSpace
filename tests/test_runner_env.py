"""The clone scripts must not inherit a hijacked PATH."""

import os

from twinspace.executor.runner import Runner, sanitized_env


def test_sanitized_env_puts_system_directories_first(monkeypatch):
    shim = "/tmp/unsafe-shim"
    monkeypatch.setenv("PATH", os.pathsep.join([shim, "/usr/local/bin", "/usr/bin", "/bin"]))

    path = sanitized_env()["PATH"].split(os.pathsep)

    assert path[:4] == ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    # The injected directory is kept (other tools may live there) but demoted.
    assert shim in path
    assert path.index(shim) > path.index("/bin")


def test_sanitized_env_has_no_duplicates(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/bin")

    path = sanitized_env()["PATH"].split(os.pathsep)

    assert path.count("/usr/bin") == 1
    assert path.count("/bin") == 1


def test_scripts_resolve_rm_to_the_system_binary(monkeypatch):
    """A sandbox shim prepended to PATH must not capture `rm`."""
    shim_dir = "/tmp/twinspace-shim-test"
    os.makedirs(shim_dir, exist_ok=True)
    shim = os.path.join(shim_dir, "rm")
    with open(shim, "w") as handle:
        handle.write("#!/bin/sh\nexit 42\n")
    os.chmod(shim, 0o755)
    monkeypatch.setenv("PATH", os.pathsep.join([shim_dir, os.environ.get("PATH", "")]))

    assert Runner.run("command -v rm").strip() == "/bin/rm"
