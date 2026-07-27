#!/usr/bin/env python3
"""Enforce SPEC.md as Smokejumper's only normative v1 document."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REQUIRED_SPEC_HEADINGS = (
    "## 0. Documentation contract",
    "## 11. Build prerequisites and operator inputs",
    "## 12. Executable implementation plan",
)

README_FORBIDDEN_TOKENS = (
    "```",
    "docker compose",
    "SMOKEJUMPER__",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "LINEAR_API_KEY",
    "localhost:",
)
README_STATUS_PATTERN = re.compile(
    r"\b(?:implemented|landed|outstanding)\b|\bnot yet\b|status:", re.I
)

MARKDOWN_LINK = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")

# Directories whose markdown is not ours to validate. Without this the gate fails
# as soon as dependencies are installed, because vendored packages ship their own
# READMEs with links that are broken relative to this repository.
EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".artifacts",
        "node_modules",
        "build",
        "dist",
        ".pytest_cache",
        ".ruff_cache",
        ".uv-cache",
        ".mypy_cache",
    }
)


def _is_ours(path: Path, root: Path) -> bool:
    """True when `path` is repository-authored markdown rather than vendored."""
    return not any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts)


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    readme_path = root / "README.md"
    spec_path = root / "SPEC.md"

    if not readme_path.is_file():
        errors.append("README.md is missing")
    if not spec_path.is_file():
        errors.append("SPEC.md is missing")
    if errors:
        return errors

    readme = readme_path.read_text(encoding="utf-8")
    spec = spec_path.read_text(encoding="utf-8")

    for token in README_FORBIDDEN_TOKENS:
        if token in readme:
            errors.append(
                f"README.md contains forbidden normative token {token!r}; link to SPEC.md instead"
            )

    status_claim = README_STATUS_PATTERN.search(readme)
    if status_claim:
        errors.append(
            "README.md contains implementation-status language "
            f"{status_claim.group(0)!r}; link to SPEC.md §12 instead"
        )

    for heading in REQUIRED_SPEC_HEADINGS:
        if heading not in spec:
            errors.append(f"SPEC.md is missing required heading: {heading}")

    for markdown_path in sorted(root.rglob("*.md")):
        if not _is_ours(markdown_path, root):
            continue
        text = markdown_path.read_text(encoding="utf-8")
        if text.count("```") % 2:
            errors.append(f"{markdown_path.relative_to(root)} has unbalanced code fences")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().split()[0].strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_part = target.split("#", 1)[0]
            if path_part and not (markdown_path.parent / path_part).exists():
                errors.append(
                    f"{markdown_path.relative_to(root)} has missing local link target: {target}"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"documentation contract: FAIL ({len(errors)} error(s))")
        return 1
    print("documentation contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
