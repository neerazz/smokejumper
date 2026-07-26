"""The one settings object (SPEC 2d).

Five layers, lowest precedence first: code defaults, ``config/base.yaml``,
``config/<env>.yaml``, ``SMOKEJUMPER__<SECTION>__<KEY>`` environment variables,
explicit CLI flags passed to :func:`load_settings`. ``SMOKEJUMPER_ENV`` selects
the third layer and defaults to ``local``.

This module is the only reader of the process environment. Every other module
takes a ``Settings`` argument, so a misconfiguration surfaces at boot with the
offending key named rather than at minute nine of an incident.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    IPvAnyNetwork,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import ErrorDetails
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

Environment = Literal["local", "dev", "prod"]
ComposeProfile = Literal["lab", "obs"]

ENV_VAR: Final = "SMOKEJUMPER_ENV"
DEFAULT_ENV: Final[Environment] = "local"

# `SMOKEJUMPER__ENV` would also populate the `env` field through the settings
# prefix, but the YAML layer is chosen from `SMOKEJUMPER_ENV` alone. Accepting
# both spellings would let the object claim one environment while loading
# another environment's file, so the ambiguous spelling is refused outright.
_AMBIGUOUS_ENV_VAR: Final = "SMOKEJUMPER__ENV"

# Local-only compose profile: the faultbox exists to break things (SPEC 2c).
# `obs` is absent because Phoenix is safe to run anywhere. The `fixtures`
# profile was removed in the 2026-07-26 subtraction pass: replay is a CLI
# command run from the app container, not a service.
LOCAL_ONLY_PROFILES: Final[frozenset[str]] = frozenset({"lab"})

# The substitute value for each port that `prod` refuses (SPEC 5.10). `tenancy`
# is deliberately absent: `SingleTenant` is the v1 implementation and not a stub,
# so leaving it out makes it unflaggable instead of relying on a special case.
STUB_SELECTIONS: Final[Mapping[str, str]] = {
    "auth": "AllowAll",
    "governance": "NoopGovernance",
    "model": "RecordedModel",
    "platform": "FixturePlatform",
    "channel": "FakeChannel",
    "ticketing": "FixtureTicketing",
    "memory": "InMemoryStore",
}

# Credentials an adapter cannot work without, so a missing one fails boot with
# the variable name instead of during an incident (SPEC 11.3). Keyed by the port
# selection that enables the adapter; the values are attribute path -> variable.
CREDENTIALS_FOR: Final[Mapping[tuple[str, str], Mapping[str, str]]] = {
    ("model", "DirectProvider"): {
        "model.worker": "SMOKEJUMPER__MODEL__WORKER",
        "model.synthesis": "SMOKEJUMPER__MODEL__SYNTHESIS",
        "model.api_key": "SMOKEJUMPER__MODEL__API_KEY",
    },
    ("channel", "Slack"): {
        "slack.bot_token": "SLACK_BOT_TOKEN",
        "slack.app_token": "SLACK_APP_TOKEN",
        "slack.channel_id": "SMOKEJUMPER__SLACK__CHANNEL_ID",
    },
    ("ticketing", "Linear"): {
        "ticketing.api_key": "LINEAR_API_KEY",
        "ticketing.team_id": "SMOKEJUMPER__TICKETING__TEAM_ID",
    },
}

# Three secrets that SPEC 11.3 names without the settings prefix, because they
# are the vendors' own conventional variable names. pydantic-settings honours a
# `validation_alias` only on a top-level field, so they are routed to their
# section here instead of being renamed, which would contradict the spec.
BARE_SECRET_VARS: Final[Mapping[str, tuple[str, str]]] = {
    "SLACK_BOT_TOKEN": ("slack", "bot_token"),
    "SLACK_APP_TOKEN": ("slack", "app_token"),
    "LINEAR_API_KEY": ("ticketing", "api_key"),
}

# `.env` is shared with docker compose, which reads host-port overrides from it
# (SPEC 11.2). Those are compose's settings, not the app's, so they are dropped;
# anything else unrecognized is a typo and fails boot.
COMPOSE_ONLY_SUFFIX: Final = "_host_port"

# `parents[2]` is the repository root for an editable install. The container
# installs the package non-editable into a virtualenv, where that path lands
# inside site-packages and no `config/` exists, so a deployment states the
# directory outright. This is the one environment read that happens at import
# time, because it decides where every other layer is read from.
CONFIG_DIR: Path = Path(
    os.environ.get("SMOKEJUMPER_CONFIG_DIR") or Path(__file__).resolve().parents[2] / "config"
)


# Selections that name code which does not exist yet, mapped to the milestone
# that builds each. `check-config` refuses them rather than answering "valid"
# for a stack that cannot boot, which is the same discipline `cli.py` applies to
# subcommands: a thing that exists and does nothing is worse than a missing one.
PLANNED_SELECTIONS: Final[Mapping[str, str]] = {
    "HostVerifier": "a host-supplied adapter (SPEC 11.5.2)",
    "HostPolicy": "a host-supplied adapter (SPEC 11.5.2)",
    "HostPlatform": "a host-supplied adapter (SPEC 11.5.2)",
    "DirectProvider": "M2",
    "Slack": "M2",
    "Linear": "M2",
    "Postgres": "M3",
}


class ConfigError(ValueError):
    """Boot-time configuration failure, phrased so an operator knows the next action.

    Subclasses `ValueError` because it reports an invalid value, and because a
    caller guarding a boundary with `except ValueError` — `smokejumper
    check-config` among them — then reports it as a message instead of letting a
    traceback reach an operator running a preflight check.
    """


class _Section(BaseModel):
    """Base for every settings section.

    `extra="forbid"` must be repeated here rather than inherited from `Settings`:
    pydantic does not propagate model config into nested models, so without it a
    typo *inside* a section is silently discarded and the operator finds out at
    M3 that the embedding model they set was never read.
    """

    model_config = ConfigDict(extra="forbid")


class DatabaseSettings(_Section):
    """Postgres. The URL carries credentials, so it is never committed to YAML."""

    url: PostgresDsn


class RedisSettings(_Section):
    url: RedisDsn


class ModelSettings(_Section):
    """Role -> provider model name.

    The role strings have no defaults because no provider is chosen before M2
    (SPEC 11.3/11.4); inventing a model name here would be a fabricated fact.
    """

    worker: str | None = None
    synthesis: str | None = None
    api_key: SecretStr | None = None


class EmbeddingSettings(_Section):
    """Embedding model and its vector width.

    Changing `dimension` after the pgvector column exists requires a migration
    (SPEC 11.3), so it is chosen once, before M3, and then left alone.
    """

    model: str | None = None
    dimension: int | None = Field(default=None, gt=0)


class BudgetSettings(_Section):
    """Spend ceiling. Decimal, because a USD ledger must not accumulate float error."""

    max_usd_per_run: Decimal | None = Field(default=None, gt=0)


class SlackSettings(_Section):
    """Socket Mode credentials (SPEC 11.3). No signing secret: v1 has no HTTP endpoint.

    There is no `enabled` flag; `ports.channel` is the only switch, so the two
    cannot disagree about whether Slack is on.
    """

    bot_token: SecretStr | None = None
    app_token: SecretStr | None = None
    channel_id: str | None = None


class TicketingSettings(_Section):
    provider: Literal["linear"] = "linear"
    api_key: SecretStr | None = None
    team_id: str | None = None
    project_id: str | None = None


class ToolsSettings(_Section):
    """Read-tier tool backends (SPEC 2c). Absent locally unless the lab is running."""

    prometheus_url: HttpUrl | None = None
    loki_url: HttpUrl | None = None


class WebhookSource(_Section):
    """One alert source's shared secret: `SMOKEJUMPER__WEBHOOKS__<SOURCE>__SECRET`."""

    secret: SecretStr | None = None


class WebhookSettings(_Section):
    grafana: WebhookSource = WebhookSource()
    datadog: WebhookSource = WebhookSource()
    pagerduty: WebhookSource = WebhookSource()
    generic: WebhookSource = WebhookSource()
    # Alertmanager signs nothing, so the network is the only available control
    # (SPEC 5.1). An empty allowlist accepts no Alertmanager payload at all.
    alertmanager_allowlist: tuple[IPvAnyNetwork, ...] = ()


class PortSelection(_Section):
    """Which implementation backs each port (SPEC 5.10).

    Defaults are the substitutes, so a forgotten value is loud in `prod` instead
    of silently plausible. The non-substitute values are the target contract and
    are accepted by the type; `PLANNED_SELECTIONS` is what refuses the ones with
    no implementation yet, so the error names the milestone instead of failing
    later with an import error.
    """

    auth: Literal["AllowAll", "HostVerifier"] = "AllowAll"
    governance: Literal["NoopGovernance", "HostPolicy"] = "NoopGovernance"
    tenancy: Literal["SingleTenant"] = "SingleTenant"
    model: Literal["RecordedModel", "DirectProvider"] = "RecordedModel"
    platform: Literal["FixturePlatform", "HostPlatform"] = "FixturePlatform"
    channel: Literal["FakeChannel", "Slack"] = "FakeChannel"
    ticketing: Literal["FixtureTicketing", "Linear"] = "FixtureTicketing"
    memory: Literal["InMemoryStore", "Postgres"] = "InMemoryStore"

    def stubbed(self) -> tuple[str, ...]:
        """Names of ports currently backed by a substitute."""
        return tuple(port for port, stub in STUB_SELECTIONS.items() if getattr(self, port) == stub)

    def unimplemented(self) -> tuple[tuple[str, str, str], ...]:
        """`(port, selection, milestone)` for each selection with no code behind it."""
        return tuple(
            (port, value, PLANNED_SELECTIONS[value])
            for port in type(self).model_fields
            if (value := getattr(self, port)) in PLANNED_SELECTIONS
        )


class Settings(BaseSettings):
    """The whole validated configuration. Assembled once, at boot."""

    model_config = SettingsConfigDict(
        env_prefix="SMOKEJUMPER__",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        # Lets CLI flags reach fields whose environment name is an alias.
        populate_by_name=True,
    )

    env: Environment = Field(default=DEFAULT_ENV, validation_alias=ENV_VAR)
    # Docker's own variable is the single source of truth for active profiles, so
    # compose and the app cannot disagree about whether the lab is running.
    compose_profiles: Annotated[frozenset[ComposeProfile], NoDecode] = Field(
        default=frozenset(),
        validation_alias=AliasChoices("SMOKEJUMPER__COMPOSE_PROFILES", "COMPOSE_PROFILES"),
    )
    log_dir: Path = Field(default=Path("logs"), validation_alias="SMOKEJUMPER_LOG_DIR")

    database: DatabaseSettings
    redis: RedisSettings
    ports: PortSelection = PortSelection()
    model: ModelSettings = ModelSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    budget: BudgetSettings = BudgetSettings()
    slack: SlackSettings = SlackSettings()
    ticketing: TicketingSettings = TicketingSettings()
    tools: ToolsSettings = ToolsSettings()
    webhooks: WebhookSettings = WebhookSettings()

    @field_validator("compose_profiles", mode="before")
    @classmethod
    def _split_profiles(cls, value: object) -> object:
        """Parse Docker's comma-separated `COMPOSE_PROFILES` spelling.

        `NoDecode` on the field turns off JSON parsing, which would otherwise
        reject the only format Docker itself accepts.
        """
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="before")
    @classmethod
    def _reconcile_shared_env(cls, data: Any) -> Any:
        """Reconcile this object with the two things that share its environment.

        SPEC 11.3 names three secrets without the settings prefix, and SPEC 11.2
        puts compose's host-port overrides in the same `.env`. Both are handled
        here so `extra="forbid"` can keep catching real typos.
        """
        if not isinstance(data, dict):
            return data
        data = {
            key: value
            for key, value in data.items()
            if not str(key).lower().endswith(COMPOSE_ONLY_SUFFIX)
        }
        for variable, (section, key) in BARE_SECRET_VARS.items():
            # Always consume the `.env` spelling, even when the process
            # environment wins, or it is left behind and read as a typo.
            from_dotenv = data.pop(variable.lower(), None)
            value = os.environ.get(variable) or from_dotenv
            existing = data.get(section)
            if value is None or (existing is not None and not isinstance(existing, dict)):
                continue
            data[section] = {key: value, **(existing or {})}
        return data

    @model_validator(mode="after")
    def _fail_closed(self) -> Settings:
        """Refuse to boot on the environment-gated safety rules (SPEC 2d).

        All problems are reported together: an operator who has two of these
        wrong should learn that in one attempt, not in two restarts.
        """
        problems: list[str] = []

        if self.env == "prod":
            stubbed = self.ports.stubbed()
            if stubbed:
                selected = ", ".join(f"{port}={getattr(self.ports, port)}" for port in stubbed)
                keys = ", ".join(f"SMOKEJUMPER__PORTS__{port.upper()}" for port in stubbed)
                problems.append(
                    f"prod refuses to boot with stub ports (SPEC 5.10): {selected}. "
                    f"Set {keys} to a real implementation, or run with {ENV_VAR}=local."
                )
            if self.budget.max_usd_per_run is None:
                problems.append(
                    "prod requires an explicit spend ceiling (SPEC 2d): set "
                    "SMOKEJUMPER__BUDGET__MAX_USD_PER_RUN to a positive USD amount. "
                    "Boot fails rather than defaulting to unlimited."
                )

        unimplemented = self.ports.unimplemented()
        if unimplemented:
            detail = ", ".join(
                f"{port}={value} (arrives with {when})" for port, value, when in unimplemented
            )
            keys = ", ".join(f"SMOKEJUMPER__PORTS__{port.upper()}" for port, _, _ in unimplemented)
            problems.append(
                f"these port selections have no implementation yet: {detail}. "
                f"Set {keys} to a substitute, or wait for the milestone that builds it. "
                "Boot fails here rather than reporting a usable configuration."
            )

        local_only = sorted(self.compose_profiles & LOCAL_ONLY_PROFILES)
        if local_only and self.env != "local":
            problems.append(
                f"compose profiles {', '.join(local_only)} are local-only (SPEC 2c) but "
                f"{ENV_VAR}={self.env}. Remove them from COMPOSE_PROFILES, or run with "
                f"{ENV_VAR}=local."
            )

        for (port, selection), credentials in CREDENTIALS_FOR.items():
            if getattr(self.ports, port) != selection:
                continue
            missing = sorted(
                var for path, var in credentials.items() if not _present(self._at(path))
            )
            if missing:
                problems.append(
                    f"{port}={selection} is enabled but unset: {', '.join(missing)}. "
                    f"Supply them, or select {STUB_SELECTIONS[port]} via "
                    f"SMOKEJUMPER__PORTS__{port.upper()}."
                )

        if problems:
            raise ValueError("\n  ".join(problems))
        return self

    def _at(self, path: str) -> object:
        value: object = self
        for attribute in path.split("."):
            value = getattr(value, attribute)
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Highest precedence first (SPEC 2d).

        `.env` sits with the environment variables it stands in for: it is how
        local development supplies them, not a sixth layer. `file_secret_settings`
        is dropped because nothing mounts secrets as files.
        """
        env = _resolve_env(getattr(init_settings, "init_kwargs", {}))
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=CONFIG_DIR / f"{env}.yaml"),
            YamlConfigSettingsSource(settings_cls, yaml_file=CONFIG_DIR / "base.yaml"),
        )


def _present(value: object) -> bool:
    """Whether a credential was actually supplied.

    `FOO=` in a `.env` file yields an empty string, and an empty API key is not a
    credential — treating it as one is how a fail-closed gate quietly stops
    working.
    """
    if value is None:
        return False
    if isinstance(value, SecretStr):
        return bool(value.get_secret_value().strip())
    return bool(str(value).strip())


def _resolve_env(init_kwargs: Mapping[str, Any]) -> str:
    """Pick the environment whose YAML file is layered in.

    Precedence matches the settings object itself: an explicit flag beats the
    environment variable, which beats the default.
    """
    if _AMBIGUOUS_ENV_VAR in os.environ:
        raise ConfigError(
            f"{_AMBIGUOUS_ENV_VAR} is not a supported spelling; it would select an "
            f"environment without selecting its config file. Use {ENV_VAR} instead."
        )
    # pydantic-settings rewrites an init keyword to the field's validation alias,
    # so an explicit `env=` flag arrives under either name depending on version.
    flag = init_kwargs.get(ENV_VAR) or init_kwargs.get("env")
    if isinstance(flag, str):
        return flag
    return os.environ.get(ENV_VAR) or DEFAULT_ENV


def _env_var_for(loc: tuple[int | str, ...]) -> str:
    """The environment variable an operator would set to fix `loc`."""
    head = str(loc[0])
    if head.startswith("SMOKEJUMPER"):  # already an alias, e.g. SMOKEJUMPER_ENV
        return head
    return "SMOKEJUMPER__" + "__".join(str(part) for part in loc).upper()


def _env_vars_for(detail: ErrorDetails) -> list[str]:
    """Every variable an operator must set to clear one validation error.

    A whole section missing is reported by pydantic against the section, which
    names no key to fix, so it is expanded into the section's required keys.
    """
    loc = detail["loc"]
    if detail["type"] == "missing" and len(loc) == 1:
        fields = getattr(Settings.model_fields[str(loc[0])].annotation, "model_fields", {})
        required = [name for name, field in fields.items() if field.is_required()]
        if required:
            return [_env_var_for((*loc, name)) for name in required]
    return [_env_var_for(loc)]


def _describe(error: ValidationError) -> str:
    lines = []
    for detail in error.errors():
        message = detail["msg"].removeprefix("Value error, ")
        if detail["loc"]:
            message = f"{', '.join(_env_vars_for(detail))}: {message}"
        lines.append(message)
    return "configuration is invalid:\n  " + "\n  ".join(lines)


def load_settings(**flags: Any) -> Settings:
    """Assemble and validate the whole settings object, or fail with the key named.

    `flags` are explicit CLI flags — the highest-precedence layer. Nested
    sections take a mapping, e.g. ``load_settings(budget={"max_usd_per_run": 5})``.
    """
    try:
        return Settings(**flags)
    except ValidationError as error:
        raise ConfigError(_describe(error)) from error
