"""The hexagonal seam: eight ports and their v1 substitutes (SPEC 5.10).

Each port is a `typing.Protocol` in its own module; `stubs.py` holds the
substitutes. Nothing is re-exported here, so a reader always sees which module a
port came from and no import of this package drags in the others.

Which implementation backs each port is configuration (`settings.ports`), and
`prod` refuses to boot on a security-relevant substitute (SPEC 2d).
"""

from __future__ import annotations
