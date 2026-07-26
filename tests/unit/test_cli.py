"""The command line's shape is a promise SPEC 12 makes, so it is asserted.

These tests exist because the failure they catch is invisible to every other
gate: Typer collapses a single-command app into a bare command, so
`smokejumper check-config` starts failing with "unexpected extra argument"
while imports, types, and lint all stay green.
"""

from __future__ import annotations

from typer.testing import CliRunner

from smokejumper.cli import app

runner = CliRunner()

# Commands SPEC 12 assigns to a later milestone. A command that exists and exits
# 0 without doing anything is worse than a missing one, because a reader trusts
# it — so their absence is asserted rather than left to habit.
UNIMPLEMENTED_UNTIL_LATER = ("logs", "replay", "eval", "distill", "fixtures", "doctor")

# The two values that have no default anywhere, because a wrong database URL must
# fail at boot rather than silently point somewhere plausible. Compose supplies
# them to the container; a test has to supply them too.
REQUIRED_URLS = {
    "SMOKEJUMPER__DATABASE__URL": "postgresql+psycopg://smokejumper:pw@postgres:5432/smokejumper",
    "SMOKEJUMPER__REDIS__URL": "redis://redis:6379/0",
}


def test_check_config_is_a_subcommand() -> None:
    """`smokejumper check-config` must keep working as the CLI grows."""
    result = runner.invoke(app, ["check-config"], env=REQUIRED_URLS)

    assert result.exit_code == 0, result.output
    assert "configuration valid for SMOKEJUMPER_ENV=local" in result.output


def test_missing_required_url_fails_with_the_variable_named() -> None:
    """The operator must learn which variable to set, not that something is wrong."""
    result = runner.invoke(app, ["check-config"], env=dict.fromkeys(REQUIRED_URLS, ""))

    assert result.exit_code == 1
    assert "SMOKEJUMPER__DATABASE__URL" in result.output
    assert "SMOKEJUMPER__REDIS__URL" in result.output


def test_bare_invocation_shows_help_rather_than_running_something() -> None:
    """A bare `smokejumper` must not silently execute a command."""
    result = runner.invoke(app, [])

    assert result.exit_code != 0
    assert "check-config" in result.output


def test_no_command_exists_before_its_milestone() -> None:
    for name in UNIMPLEMENTED_UNTIL_LATER:
        result = runner.invoke(app, [name])
        assert result.exit_code != 0, f"{name!r} must not exist until its milestone lands"


def test_invalid_configuration_is_reported_as_a_message() -> None:
    """An operator running a preflight check reads the problem, not a traceback."""
    result = runner.invoke(app, ["check-config"], env={**REQUIRED_URLS, "SMOKEJUMPER_ENV": "prod"})

    assert result.exit_code == 1
    assert "configuration invalid" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
