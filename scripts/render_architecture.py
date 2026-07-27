#!/usr/bin/env python3
"""Render the canonical Mermaid architecture SVG portably.

Mermaid's native-label SVG writes each word in a separate ``tspan`` with a
leading space. SVG viewers such as librsvg discard those leading spaces unless
``xml:space=preserve`` is set on the root. The post-processing below is part of
the render contract, not a cosmetic hand edit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from shutil import which

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "architecture" / "smokejumper-architecture.mmd"
OUTPUT = ROOT / "architecture" / "smokejumper-architecture.svg"


def main() -> int:
    npx = which("npx")
    if npx is None:
        raise RuntimeError("npx is required to render the Mermaid architecture")
    subprocess.run(  # noqa: S603 - executable is resolved locally; arguments are static repo paths
        [
            npx,
            "-y",
            "@mermaid-js/mermaid-cli",
            "-i",
            str(SOURCE),
            "-o",
            str(OUTPUT),
            "-b",
            "white",
        ],
        cwd=ROOT,
        check=True,
    )
    rendered = OUTPUT.read_text(encoding="utf-8")
    marker = '<svg id="my-svg"'
    if marker not in rendered:
        raise RuntimeError("Mermaid output root changed; refusing an unverified post-process")
    rendered = rendered.replace(marker, '<svg xml:space="preserve" id="my-svg"', 1)
    root_end = rendered.index(">") + 1
    background = '<rect width="100%" height="100%" fill="#fff"/>'
    rendered = rendered[:root_end] + background + rendered[root_end:]
    if not rendered.rstrip().endswith("</svg>"):
        raise RuntimeError("Mermaid output is not a complete SVG document")
    OUTPUT.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
