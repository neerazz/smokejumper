from __future__ import annotations

import contextlib
import importlib.util
import re
import socket
import subprocess
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "check_host_ports.py"
SPEC = REPO_ROOT / "SPEC.md"

# `127.0.0.1:${VAR:-host}:container` — the only publication form SPEC §11.2 allows.
PUBLICATION = re.compile(r"^127\.0\.0\.1:\$\{(?P<var>[A-Z_]+):-(?P<host>\d+)\}:(?P<container>\d+)$")

# Cells that assert a component is not reachable from the host.
UNPUBLISHED = frozenset({"none", "outbound only"})

COMPONENT_COLUMN = "Component / listener"
PUBLICATION_COLUMN = "Local host publication"


def _load_checker() -> ModuleType:
    """Import the script by path: `scripts/` is deliberately not a package.

    The `sys.modules` registration is required, not tidiness: `@dataclass`
    resolves its own module through `sys.modules[cls.__module__]`, and fails on
    an unregistered module.
    """
    spec = importlib.util.spec_from_file_location("check_host_ports", CHECKER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {CHECKER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


@contextlib.contextmanager
def bound_loopback_port() -> Iterator[int]:
    """Hold a real listening socket on an ephemeral loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind((checker.LOOPBACK, 0))
        holder.listen(1)
        yield holder.getsockname()[1]


def spec_port_table() -> list[dict[str, str]]:
    """Data rows of the SPEC §11.2 port table, keyed by column heading.

    Keying by heading rather than position means reordering the table's columns
    cannot silently change what this gate asserts.
    """
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("### 11.2 ")
    section = text[start : text.index("\n### ", start)]

    def cells(line: str) -> list[str]:
        return [cell.strip().strip("`").strip() for cell in line.strip("|").split("|")]

    lines = [line for line in section.splitlines() if line.startswith("|")]
    if not lines:
        raise AssertionError("SPEC.md §11.2 has no port table")

    def is_separator(row: list[str]) -> bool:
        return all(set(cell) <= {"-", ":"} for cell in row)

    headings = cells(lines[0])
    rows = [
        dict(zip(headings, row, strict=True))
        for row in (cells(line) for line in lines[1:])
        if not is_separator(row)
    ]
    if not rows:
        raise AssertionError("SPEC.md §11.2 port table has no data rows")
    return rows


class ProfileSelectionTest(unittest.TestCase):
    def test_no_profile_checks_only_the_app_port(self) -> None:
        ports = checker.selected_ports(())
        self.assertEqual([port.service for port in ports], ["app"])
        self.assertEqual(ports[0].host_port, 8000)

    def test_lab_adds_prometheus_and_obs_adds_phoenix(self) -> None:
        self.assertEqual(
            [port.service for port in checker.selected_ports(["lab"])], ["app", "prometheus"]
        )
        self.assertEqual(
            [port.service for port in checker.selected_ports(["obs"])], ["app", "phoenix"]
        )

    def test_fixtures_publishes_nothing_of_its_own(self) -> None:
        self.assertEqual(
            checker.selected_ports(["fixtures"]),
            checker.selected_ports(()),
        )

    def test_all_profiles_together_check_every_published_port(self) -> None:
        self.assertEqual(
            checker.selected_ports(checker.SELECTABLE_PROFILES),
            checker.INVENTORY,
        )

    def test_unknown_profile_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            checker.parse_profiles("lab,grafana")
        self.assertIn("grafana", str(caught.exception))

    def test_profile_list_is_whitespace_tolerant(self) -> None:
        self.assertEqual(checker.parse_profiles(" lab , obs "), ("lab", "obs"))


class CollisionLogicTest(unittest.TestCase):
    """Collision selection is pure: the probe is injected, so no sockets bind."""

    def test_collisions_are_the_ports_the_probe_calls_taken(self) -> None:
        taken = {6006}
        collisions = checker.find_collisions(checker.INVENTORY, lambda port: port not in taken)
        self.assertEqual([port.service for port in collisions], ["phoenix"])

    def test_no_collisions_when_everything_is_free(self) -> None:
        self.assertEqual(checker.find_collisions(checker.INVENTORY, lambda _: True), ())

    def test_override_hint_names_the_variable_and_a_replacement_port(self) -> None:
        phoenix = next(port for port in checker.INVENTORY if port.service == "phoenix")
        self.assertEqual(checker.override_hint(phoenix), "PHOENIX_HOST_PORT=16006")


class LoopbackProbeTest(unittest.TestCase):
    def test_a_really_bound_port_is_detected(self) -> None:
        with bound_loopback_port() as port:
            self.assertFalse(checker.probe_loopback(port))

    def test_a_released_port_is_reported_free(self) -> None:
        with bound_loopback_port() as port:
            pass
        self.assertTrue(checker.probe_loopback(port))

    def test_a_bound_port_drives_the_real_collision_path(self) -> None:
        with bound_loopback_port() as port:
            occupied = checker.PublishedPort("obs", "phoenix", 6006, port, "PHOENIX_HOST_PORT")
            collisions = checker.find_collisions([occupied], checker.probe_loopback)
        self.assertEqual(collisions, (occupied,))


class CommandLineTest(unittest.TestCase):
    def test_unknown_profile_exits_two(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECKER), "--profiles", "grafana"],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("unknown profile(s): grafana", result.stdout)


class SpecTableTest(unittest.TestCase):
    """The gate that stops SPEC §11.2 and the script inventory from diverging."""

    def test_published_rows_match_the_script_inventory(self) -> None:
        from_spec = set()
        for row in spec_port_table():
            match = PUBLICATION.match(row[PUBLICATION_COLUMN])
            if match is None:
                continue
            service, _, container_port = row["Bind inside deployment"].partition(":")
            from_spec.add(
                (row["Profile"], service, int(container_port), int(match["host"]), match["var"])
            )
            self.assertEqual(
                int(match["container"]),
                int(container_port),
                f"{row[COMPONENT_COLUMN]}: published container port disagrees with its bind",
            )

        from_script = {
            (port.profile, port.service, port.container_port, port.host_port, port.env_var)
            for port in checker.INVENTORY
        }
        self.assertEqual(from_spec, from_script)

    def test_every_other_row_declares_itself_unpublished(self) -> None:
        for row in spec_port_table():
            publication = row[PUBLICATION_COLUMN]
            if PUBLICATION.match(publication):
                continue
            self.assertIn(
                publication,
                UNPUBLISHED,
                f"{row[COMPONENT_COLUMN]}: host publication must be a 127.0.0.1 mapping, "
                "'none', or 'outbound only' — anything else cannot be preflighted",
            )

    def test_only_the_app_port_is_published_by_default(self) -> None:
        default = [port for port in checker.INVENTORY if port.profile == checker.CORE_PROFILE]
        self.assertEqual([port.service for port in default], ["app"])


if __name__ == "__main__":
    unittest.main()
