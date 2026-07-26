"""Tests for the one settings object (SPEC 2d).

Each test drives `load_settings`, the same entry point boot uses, so a passing
test means boot behaves that way — not that an internal helper does.
"""

from __future__ import annotations

import os
import re
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from smokejumper import config
from smokejumper.config import ConfigError, load_settings

DB_URL = "postgresql+psycopg://smokejumper:pw@postgres:5432/smokejumper"
REDIS_URL = "redis://redis:6379/0"

# Values that satisfy every credential gate, for tests about something else.
REAL_PORTS = {
    "auth": "HostVerifier",
    "governance": "HostPolicy",
    "tenancy": "SingleTenant",
    "model": "DirectProvider",
    "platform": "HostPlatform",
    "channel": "Slack",
    "ticketing": "Linear",
    "memory": "Postgres",
}
CREDENTIALS = {
    "SMOKEJUMPER__MODEL__WORKER": "worker-model",
    "SMOKEJUMPER__MODEL__SYNTHESIS": "synthesis-model",
    "SMOKEJUMPER__MODEL__API_KEY": "provider-key",
    "SLACK_BOT_TOKEN": "xoxb-test",
    "SLACK_APP_TOKEN": "xapp-test",
    "SMOKEJUMPER__SLACK__CHANNEL_ID": "C0000000000",
    "LINEAR_API_KEY": "lin_api_test",
    "SMOKEJUMPER__TICKETING__TEAM_ID": "team-uuid",
}


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Remove ambient configuration so a developer's own `.env` cannot skew a test."""
    for name in list(os.environ):
        if name.startswith(("SMOKEJUMPER", "SLACK_", "LINEAR_", "COMPOSE_")):
            monkeypatch.delenv(name, raising=False)
    # `.env` is resolved relative to the working directory.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SMOKEJUMPER__DATABASE__URL", DB_URL)
    monkeypatch.setenv("SMOKEJUMPER__REDIS__URL", REDIS_URL)


@pytest.fixture
def config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A throwaway `config/` so YAML-layer tests do not depend on committed values."""
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "base.yaml").write_text("", encoding="utf-8")
    for env in ("local", "dev", "prod"):
        (directory / f"{env}.yaml").write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_DIR", directory)
    return directory


def test_layers_apply_in_precedence_order(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each layer overrides the one below it, and only that one (SPEC 2d)."""
    assert load_settings().budget.max_usd_per_run is None  # 1. code default

    (config_dir / "base.yaml").write_text('budget:\n  max_usd_per_run: "1"\n', encoding="utf-8")
    assert load_settings().budget.max_usd_per_run == Decimal("1")  # 2. base.yaml

    (config_dir / "local.yaml").write_text('budget:\n  max_usd_per_run: "2"\n', encoding="utf-8")
    assert load_settings().budget.max_usd_per_run == Decimal("2")  # 3. <env>.yaml

    monkeypatch.setenv("SMOKEJUMPER__BUDGET__MAX_USD_PER_RUN", "3")
    assert load_settings().budget.max_usd_per_run == Decimal("3")  # 4. environment

    flagged = load_settings(budget={"max_usd_per_run": "4"})  # 5. CLI flag
    assert flagged.budget.max_usd_per_run == Decimal("4")


def test_env_selects_the_yaml_layer_and_defaults_to_local(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (config_dir / "local.yaml").write_text("embedding:\n  dimension: 8\n", encoding="utf-8")
    (config_dir / "dev.yaml").write_text("embedding:\n  dimension: 16\n", encoding="utf-8")

    assert load_settings().env == "local"
    assert load_settings().embedding.dimension == 8

    monkeypatch.setenv("SMOKEJUMPER_ENV", "dev")
    assert load_settings().embedding.dimension == 16

    # An explicit flag outranks the variable, and selects the file too.
    assert load_settings(env="local").embedding.dimension == 8


def test_dotenv_supplies_environment_variables(config_dir: Path, tmp_path: Path) -> None:
    """`.env` is how local development supplies variables, not a sixth layer."""
    (tmp_path / ".env").write_text("SMOKEJUMPER__EMBEDDING__DIMENSION=1536\n", encoding="utf-8")
    assert load_settings().embedding.dimension == 1536


def test_double_underscore_env_spelling_is_refused(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`SMOKEJUMPER__ENV` would set the field without selecting its config file."""
    monkeypatch.setenv("SMOKEJUMPER__ENV", "prod")
    with pytest.raises(ConfigError, match="Use SMOKEJUMPER_ENV instead"):
        load_settings()


def test_missing_required_value_names_its_variable(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SMOKEJUMPER__DATABASE__URL")
    with pytest.raises(ConfigError, match=r"SMOKEJUMPER__DATABASE__URL: Field required"):
        load_settings()


def test_malformed_value_names_its_variable(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMOKEJUMPER__REDIS__URL", "postgresql://nope/0")
    with pytest.raises(ConfigError, match=r"SMOKEJUMPER__REDIS__URL: URL scheme"):
        load_settings()


def test_unknown_key_is_refused(config_dir: Path) -> None:
    """A typo must fail boot rather than be silently ignored."""
    (config_dir / "local.yaml").write_text("budgets:\n  max_usd: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"SMOKEJUMPER__BUDGETS: Extra inputs"):
        load_settings()


def test_bare_vendor_variables_reach_their_section(
    config_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC 11.3 names three secrets without the prefix; both delivery paths work."""
    (tmp_path / ".env").write_text(
        "SLACK_APP_TOKEN=xapp-from-dotenv\nLINEAR_API_KEY=lin_api_from_dotenv\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-from-environ")
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_from_environ")

    settings = load_settings()

    assert settings.slack.bot_token is not None
    assert settings.slack.bot_token.get_secret_value() == "xoxb-from-environ"
    assert settings.slack.app_token is not None
    assert settings.slack.app_token.get_secret_value() == "xapp-from-dotenv"
    # The process environment outranks `.env`.
    assert settings.ticketing.api_key is not None
    assert settings.ticketing.api_key.get_secret_value() == "lin_api_from_environ"


def test_composes_own_env_keys_are_ignored(config_dir: Path, tmp_path: Path) -> None:
    """`.env` is shared with compose (SPEC 11.2), so its keys must not break boot."""
    (tmp_path / ".env").write_text(
        "APP_HOST_PORT=8001\nPOSTGRES_HOST_PORT=5433\nCOMPOSE_PROFILES=lab\n",
        encoding="utf-8",
    )
    settings = load_settings()

    assert settings.env == "local"
    assert settings.compose_profiles == frozenset({"lab"})


def test_prod_refuses_stub_ports(config_dir: Path) -> None:
    """A log line is not a control: prod fails closed (SPEC 2d, 5.10)."""
    with pytest.raises(ConfigError) as raised:
        load_settings(env="prod", budget={"max_usd_per_run": "5"})

    message = str(raised.value)
    assert "prod refuses to boot with stub ports" in message
    for port in ("auth", "governance", "model", "platform", "channel", "ticketing", "memory"):
        assert f"SMOKEJUMPER__PORTS__{port.upper()}" in message
    assert "auth=AllowAll" in message


def test_prod_allows_single_tenant(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`SingleTenant` is the v1 implementation, not a stub (SPEC 5.10)."""
    for name, value in CREDENTIALS.items():
        monkeypatch.setenv(name, value)

    settings = load_settings(env="prod", ports=REAL_PORTS, budget={"max_usd_per_run": "5"})

    assert settings.ports.tenancy == "SingleTenant"
    assert settings.ports.stubbed() == ()
    assert "tenancy" not in config.STUB_SELECTIONS


def test_prod_requires_an_explicit_spend_ceiling(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in CREDENTIALS.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError) as raised:
        load_settings(env="prod", ports=REAL_PORTS)

    message = str(raised.value)
    assert "SMOKEJUMPER__BUDGET__MAX_USD_PER_RUN" in message
    assert "rather than defaulting to unlimited" in message


def test_lab_and_fixtures_profiles_are_local_only(config_dir: Path) -> None:
    for env in ("dev", "prod"):
        with pytest.raises(ConfigError) as raised:
            load_settings(env=env, compose_profiles="lab,fixtures")
        message = str(raised.value)
        assert "fixtures, lab are local-only" in message
        assert "COMPOSE_PROFILES" in message
        assert f"SMOKEJUMPER_ENV={env}" in message

    assert load_settings(compose_profiles="lab,fixtures").compose_profiles == frozenset(
        {"lab", "fixtures"}
    )


def test_obs_profile_is_allowed_outside_local(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the lab and its fault injection are local-only (SPEC 2c)."""
    for name, value in CREDENTIALS.items():
        monkeypatch.setenv(name, value)

    settings = load_settings(
        env="prod",
        ports=REAL_PORTS,
        budget={"max_usd_per_run": "5"},
        compose_profiles="obs",
    )

    assert settings.compose_profiles == frozenset({"obs"})


def test_compose_profiles_read_dockers_own_variable(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One variable for compose and the app, so they cannot disagree."""
    monkeypatch.setenv("COMPOSE_PROFILES", "lab, fixtures")
    assert load_settings().compose_profiles == frozenset({"lab", "fixtures"})


def test_enabled_adapter_without_its_credential_fails_boot(config_dir: Path) -> None:
    """Fail at boot with the variable name, never during an incident (SPEC 11.3)."""
    with pytest.raises(ConfigError) as raised:
        load_settings(ports={**REAL_PORTS, "auth": "AllowAll"})

    message = str(raised.value)
    assert "ticketing=Linear is enabled but unset" in message
    assert "LINEAR_API_KEY" in message
    assert "SMOKEJUMPER__TICKETING__TEAM_ID" in message
    assert "select FixtureTicketing" in message


def test_blank_credential_counts_as_unset(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in CREDENTIALS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("LINEAR_API_KEY", "   ")

    with pytest.raises(ConfigError, match="LINEAR_API_KEY"):
        load_settings(ports=REAL_PORTS)


def test_every_problem_is_reported_at_once(config_dir: Path) -> None:
    """Two mistakes should cost one restart, not two."""
    with pytest.raises(ConfigError) as raised:
        load_settings(env="prod", compose_profiles="lab")

    message = str(raised.value)
    assert "stub ports" in message
    assert "SMOKEJUMPER__BUDGET__MAX_USD_PER_RUN" in message
    assert "local-only" in message


# --- The committed config/ files -------------------------------------------

SECRET_SHAPED_KEY = re.compile(
    r"^\s*[\w.-]*(secret|token|password|passwd|api_?key|credential|private_key)"
    r"[\w.-]*\s*:\s*\S",
    re.IGNORECASE | re.MULTILINE,
)
SECRET_SHAPED_VALUE = re.compile(r"xoxb-|xapp-|lin_api_|sk-[A-Za-z0-9]|://[^/\s:]+:[^/\s@]+@")


@pytest.mark.parametrize("name", ["base.yaml", "local.yaml", "dev.yaml", "prod.yaml"])
def test_committed_yaml_holds_no_secrets(repo_root: Path, name: str) -> None:
    """`config/` is committed, so it holds references and never values (SPEC 2d)."""
    text = (repo_root / "config" / name).read_text(encoding="utf-8")

    assert SECRET_SHAPED_KEY.search(text) is None, f"{name} has a secret-shaped key"
    assert SECRET_SHAPED_VALUE.search(text) is None, f"{name} has a secret-shaped value"


@pytest.mark.parametrize("name", ["base.yaml", "local.yaml", "dev.yaml", "prod.yaml"])
def test_committed_yaml_never_sets_env(repo_root: Path, name: str) -> None:
    """`SMOKEJUMPER_ENV` picks the file; a file that picks the environment is a loop."""
    document = yaml.safe_load((repo_root / "config" / name).read_text(encoding="utf-8"))

    assert document is None or "env" not in document


def test_committed_local_config_boots() -> None:
    """The real config/local.yaml is valid, with only the two required variables set."""
    settings = load_settings()

    assert settings.env == "local"
    assert settings.ports.auth == "AllowAll"
    assert settings.budget.max_usd_per_run == Decimal("1.00")
    assert str(settings.tools.prometheus_url) == "http://prometheus:9090/"


def test_committed_dev_config_boots(monkeypatch: pytest.MonkeyPatch) -> None:
    """dev selects real Slack/Linear/model, so it needs their credentials."""
    for name, value in CREDENTIALS.items():
        monkeypatch.setenv(name, value)

    settings = load_settings(env="dev")

    assert settings.budget.max_usd_per_run == Decimal("2.00")
    assert settings.ports.ticketing == "Linear"


def test_committed_prod_config_has_no_stub_and_no_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """prod.yaml selects only real ports, and deliberately supplies no ceiling."""
    for name, value in CREDENTIALS.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError) as raised:
        load_settings(env="prod")
    assert "SMOKEJUMPER__BUDGET__MAX_USD_PER_RUN" in str(raised.value)
    assert "stub ports" not in str(raised.value)

    monkeypatch.setenv("SMOKEJUMPER__BUDGET__MAX_USD_PER_RUN", "25")
    assert load_settings(env="prod").ports.stubbed() == ()


def test_env_example_boots_when_copied(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Copying the template to `.env` must produce a bootable configuration."""
    monkeypatch.delenv("SMOKEJUMPER__DATABASE__URL")
    monkeypatch.delenv("SMOKEJUMPER__REDIS__URL")
    (tmp_path / ".env").write_text(
        (repo_root / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
    )

    settings = load_settings()

    assert settings.env == "local"
    assert settings.compose_profiles == frozenset()
    assert str(settings.database.url).endswith("@postgres:5432/smokejumper")


def test_env_example_documents_every_variable(repo_root: Path) -> None:
    """A template that has drifted is worse than none: it teaches the wrong name."""
    text = (repo_root / ".env.example").read_text(encoding="utf-8")

    required = {
        "SMOKEJUMPER_ENV",
        "COMPOSE_PROFILES",
        "SMOKEJUMPER__DATABASE__URL",
        "SMOKEJUMPER__REDIS__URL",
        "SMOKEJUMPER_LOG_DIR",
        *CREDENTIALS,
        *(var for mapping in config.CREDENTIALS_FOR.values() for var in mapping.values()),
    }

    missing = sorted(name for name in required if name not in text)
    assert not missing
