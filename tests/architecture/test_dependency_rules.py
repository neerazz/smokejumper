"""SPEC §3's dependency rules, enforced mechanically.

Four sentences hold the architecture up: `contracts` imports nothing internal,
`ports/model.py` is the only place a provider SDK appears, `receiver` and
`actions` never reach a model, and only `mcp/` speaks MCP. Everything else in the
design leans on them — deterministic replay, the tiering seam, "nothing
downstream of B6 calls a model" — and prose has never once stopped an import.

The tree is parsed with `ast`, never imported. Most of the packages these rules
protect do not exist yet, so an import-based checker would pass vacuously today
and only begin working after the erosion it exists to prevent became possible.
Parsing also catches an import of something that is not installed, which is
exactly the shape a first violation takes.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

CONTRACTS_IS_LEAF = "contracts must import nothing else from smokejumper"
MODEL_SDK_CONFINED = "a model/provider SDK may be imported only in ports/model.py"
NO_MODEL_DOWNSTREAM = "receiver/ and actions/ must not reach a model"
MCP_CONFINED = "only mcp/ may speak MCP"

PROVIDER_SDKS = frozenset(
    {
        "anthropic",
        "openai",
        "google.generativeai",
        "google.genai",
        "litellm",
        "cohere",
        "mistralai",
        "vertexai",
        "ollama",
        "groq",
    }
)
MCP_LIBRARIES = frozenset({"mcp", "fastmcp", "langchain_mcp_adapters"})
CONTRACTS_PACKAGE = "smokejumper.contracts"
MODEL_PORT = "smokejumper.ports.model"

CONTRACTS_DIR = Path("contracts")
MCP_DIR = Path("mcp")
MODEL_SEAM = Path("ports/model.py")
MODEL_FREE_DIRS = (Path("receiver"), Path("actions"))


@dataclass(frozen=True)
class Violation:
    rule: str
    module: str
    line: int
    imported: str

    def __str__(self) -> str:
        return f"{self.module}:{self.line} imports {self.imported} — {self.rule}"


def check_dependency_rules(package_root: Path) -> list[Violation]:
    """Every dependency-rule breach under `package_root` (e.g. `src/smokejumper`)."""
    violations: list[Violation] = []
    seen: set[tuple[str, str, int]] = set()
    for path in sorted(package_root.rglob("*.py")):
        module = path.relative_to(package_root)
        for line, imported in _imports(path, package_root):
            for violation in _breaches(module, line, imported):
                key = (violation.rule, violation.module, violation.line)
                if key not in seen:
                    seen.add(key)
                    violations.append(violation)
    return violations


def _breaches(module: Path, line: int, imported: str) -> Iterator[Violation]:
    location = module.as_posix()

    if (
        module.is_relative_to(CONTRACTS_DIR)
        and _matches(imported, ["smokejumper"])
        and not _matches(imported, [CONTRACTS_PACKAGE])
    ):
        yield Violation(CONTRACTS_IS_LEAF, location, line, imported)

    if _matches(imported, PROVIDER_SDKS) and module != MODEL_SEAM:
        yield Violation(MODEL_SDK_CONFINED, location, line, imported)

    # Provider SDKs anywhere are already caught above; this rule is about the
    # remaining route to a model — our own model port.
    if any(module.is_relative_to(directory) for directory in MODEL_FREE_DIRS) and _matches(
        imported, [MODEL_PORT]
    ):
        yield Violation(NO_MODEL_DOWNSTREAM, location, line, imported)

    # Constructing an MCP client requires importing one, so the import is the
    # earlier and statically checkable signal.
    if _matches(imported, MCP_LIBRARIES) and not module.is_relative_to(MCP_DIR):
        yield Violation(MCP_CONFINED, location, line, imported)


def _matches(imported: str, prefixes: Iterable[str]) -> bool:
    return any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in prefixes)


def _imports(path: Path, package_root: Path) -> Iterator[tuple[int, str]]:
    """Every module name the file imports, with relative imports resolved absolute."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parts = [package_root.name, *path.relative_to(package_root).with_suffix("").parts]
    package = parts[:-1]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_base(node, package)
            if base:
                yield node.lineno, base
            for alias in node.names:
                yield node.lineno, f"{base}.{alias.name}" if base else alias.name


def _absolute_base(node: ast.ImportFrom, package: list[str]) -> str:
    if not node.level:
        return node.module or ""
    ascended = package[: len(package) - (node.level - 1)]
    return ".".join([*ascended, *(node.module.split(".") if node.module else [])])


def _write(package_root: Path, module: str, source: str) -> None:
    path = package_root / module
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_the_repository_satisfies_every_dependency_rule(src_root: Path) -> None:
    assert [str(violation) for violation in check_dependency_rules(src_root)] == []


def test_packages_that_do_not_exist_yet_are_not_an_error(tmp_path: Path) -> None:
    """The rules must be checkable while most of the tree is still unwritten."""
    package_root = tmp_path / "smokejumper"
    package_root.mkdir()
    assert check_dependency_rules(package_root) == []


@pytest.mark.parametrize(
    ("module", "source", "rule"),
    [
        ("contracts/events.py", "from smokejumper.config import Settings\n", CONTRACTS_IS_LEAF),
        ("contracts/leak.py", "from ..persistence import database\n", CONTRACTS_IS_LEAF),
        ("contracts/root.py", "import smokejumper\n", CONTRACTS_IS_LEAF),
        ("intelligence/supervisor.py", "import anthropic\n", MODEL_SDK_CONFINED),
        (
            "knowledge/embed.py",
            "from google.generativeai import embed_content\n",
            MODEL_SDK_CONFINED,
        ),
        ("ports/governance.py", "import litellm\n", MODEL_SDK_CONFINED),
        (
            "actions/linear.py",
            "from smokejumper.ports.model import ModelProvider\n",
            NO_MODEL_DOWNSTREAM,
        ),
        ("receiver/normalize.py", "from smokejumper.ports import model\n", NO_MODEL_DOWNSTREAM),
        ("knowledge/facade.py", "import fastmcp\n", MCP_CONFINED),
        (
            "intelligence/tools.py",
            "from langchain_mcp_adapters.client import MultiServerMCPClient\n",
            MCP_CONFINED,
        ),
    ],
)
def test_the_checker_catches_a_deliberate_breach(
    tmp_path: Path, module: str, source: str, rule: str
) -> None:
    """Proof the checker is not vacuous: each rule is broken on purpose in a
    synthetic tree, once, and must be reported exactly once."""
    package_root = tmp_path / "smokejumper"
    _write(package_root, module, source)
    assert [violation.rule for violation in check_dependency_rules(package_root)] == [rule]


def test_a_violation_names_the_file_line_and_import(tmp_path: Path) -> None:
    package_root = tmp_path / "smokejumper"
    _write(package_root, "actions/slack.py", "import json\nimport anthropic\n")
    (violation,) = check_dependency_rules(package_root)
    assert (violation.module, violation.line, violation.imported) == (
        "actions/slack.py",
        2,
        "anthropic",
    )


def test_permitted_imports_are_not_flagged(tmp_path: Path) -> None:
    """The rules must stay silent on the legitimate shape of the same imports,
    or they will be deleted the first time they cry wolf."""
    package_root = tmp_path / "smokejumper"
    _write(
        package_root,
        "contracts/__init__.py",
        "from .events import AgentEvent\nfrom smokejumper.contracts.base import Contract\n",
    )
    _write(package_root, "contracts/events.py", "from pydantic import BaseModel\n")
    _write(package_root, "ports/model.py", "import anthropic\nfrom openai import AsyncOpenAI\n")
    _write(package_root, "mcp/gateway.py", "from fastmcp import Client\n")
    _write(package_root, "mcp/servers/metrics/server.py", "import mcp\n")
    _write(package_root, "actions/linear.py", "from smokejumper.contracts import Conclusion\n")
    _write(
        package_root,
        "receiver/routes.py",
        "import fastapi\nfrom smokejumper.contracts import AgentEvent\n",
    )
    assert check_dependency_rules(package_root) == []
