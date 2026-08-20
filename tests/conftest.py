"""Shared fixtures and marker registration for the crude test suite.

The live smoke tests reach real site APIs and need real credentials, so they are
gated twice: they carry the ``live`` marker (deselected by default in pyproject),
and the ``crude_config`` fixture skips the run entirely when no config.toml is
found. Config is located through ``crude_common.config.find_config`` so its
location stays single-sourced with the CLIs rather than hardcoded here.
"""

import pytest
import typer


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: hits real site APIs; needs a crude config and `-m live` to run.",
    )


@pytest.fixture(scope="session")
def crude_config() -> dict:
    """Return the parsed config, or skip the test when none is present."""
    from crude_common.config import find_config, read_config

    try:
        path = find_config()
    except (typer.Exit, SystemExit):
        pytest.skip("no crude config.toml found")
    return read_config(path)


@pytest.fixture(autouse=True)
def _claude_config_dir_sandbox(tmp_path_factory, monkeypatch):
    """Point ``CLAUDE_CONFIG_DIR`` at a scratch tree for every test.

    Each site CLI rewrites its Claude Code command on every invocation, so a
    ``CliRunner`` call from the suite would otherwise reach the developer's live
    configuration and rewrite the command file there.
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path_factory.mktemp("claude")))
