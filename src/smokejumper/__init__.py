"""Smokejumper: an agentic SRE that parachutes into incidents.

The package root stays deliberately empty. Importing `smokejumper` must never
pull in FastAPI, a database driver, or a model client, because the dependency
rules in `tests/architecture/test_dependency_rules.py` are enforced by import
inspection and a convenience re-export here would defeat them.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
