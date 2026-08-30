# ruff: noqa
"""Hand-laid swimlane renderer for user journeys and incident scenarios.

Explicit grid, no auto-layout: lanes are rows, time is columns. Each step is a card at
(lane, column); edges are drawn between card centres. Palette matches system/c2-components.svg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path

PALETTE = {
    "core": ("#e3f3f6", "#0b7285", "#0b3a42"),
    "files": ("#e6f4ea", "#2b8a3e", "#1b4d24"),
    "port": ("#f1f3f5", "#5b6b7a", "#3d4852"),
    "gate": ("#fbf0da", "#9a6700", "#5c3d00"),
    "audit": ("#efeafb", "#6741b8", "#2f1e5c"),
    "store": ("#eef2fb", "#3f5b9a", "#1f2d4a"),
    "human": ("#fff4e6", "#d9480f", "#6b2a00"),
    "signal": ("#fff0f0", "#c92a2a", "#5c0d0d"),
    "ok": ("#e6f4ea", "#2b8a3e", "#1b4d24"),
}
GREY = "#5b6b7a"
INK = "#10334a"
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


@dataclass
class Step:
    lane: int
    col: int
    title: str
    lines: list[str] = field(default_factory=list)
    kind: str = "core"
    span: int = 1  # columns spanned
    badge: str | None = None  # small right-aligned label, e.g. "B8 tool_call" or "t+4m"


@dataclass
class Diagram:
    title: str
    subtitle: str
    lanes: list[str]
    columns: list[str]
    steps: list[Step]
    edges: list[tuple[int, int, str | None]] = field(
        default_factory=list
    )  # step index → step index
    footer: list[str] = field(default_factory=list)  # lines under the grid
    legend: list[tuple[str, str]] = field(default_factory=list)  # (kind, label)
    lane_w: int = 170
    col_w: int = 236
    card_w: int = 222
    line_h: int = 14
    pad: int = 60


def _text(out, x, y, s, size=12, weight=None, fill=INK, anchor="start"):
    a = f'x="{x}" y="{y}" font-size="{size}" fill="{fill}"'
    if weight:
        a += f' font-weight="{weight}"'
    if anchor != "start":
        a += f' text-anchor="{anchor}"'
    out.append(f"  <text {a}>{escape(s)}</text>")


def render(d: Diagram, path: Path) -> None:
    out: list[str] = []
    P = out.append
    # lane heights from tallest card in lane
    lane_h: list[int] = []
    for li in range(len(d.lanes)):
        tallest = 0
        for s in d.steps:
            if s.lane == li:
                tallest = max(tallest, 40 + d.line_h * len(s.lines) + (14 if s.badge else 0))
        lane_h.append(max(72, tallest + 24))
    grid_x = d.pad + d.lane_w
    grid_y = 150
    W = grid_x + d.col_w * len(d.columns) + d.pad
    grid_h = sum(lane_h)
    footer_h = 30 + 16 * len(d.footer) if d.footer else 0
    H = grid_y + grid_h + 40 + footer_h + d.pad

    P(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="{FONT}" role="img" aria-labelledby="t d">'
    )
    P(f'  <title id="t">{escape(d.title)}</title>')
    P(f'  <desc id="d">{escape(d.subtitle)}</desc>')
    P(
        '  <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#3d4852"/></marker></defs>'
    )
    P(f'  <rect width="{W}" height="{H}" fill="#ffffff"/>')
    _text(out, d.pad, 62, d.title, 26, "700", INK)
    _text(out, d.pad, 88, d.subtitle, 12.5, None, GREY)
    # legend
    lx = d.pad
    for kind, lab in d.legend:
        fill, stroke, _ = PALETTE[kind]
        P(
            f'  <rect x="{lx}" y="104" width="22" height="14" rx="3" fill="{fill}" stroke="{stroke}"/>'
        )
        _text(out, lx + 28, 116, lab, 11, None, GREY)
        lx += 28 + 6.3 * len(lab) + 26

    # column headers
    for ci, c in enumerate(d.columns):
        cx = grid_x + ci * d.col_w
        P(
            f'  <rect x="{cx}" y="{grid_y - 24}" width="{d.col_w}" height="24" fill="#f8f9fa" stroke="#d5dde5"/>'
        )
        _text(out, cx + d.col_w / 2, grid_y - 8, c, 11.5, "700", GREY, "middle")
    # lanes
    y = grid_y
    lane_y: list[int] = []
    for li, name in enumerate(d.lanes):
        lane_y.append(y)
        fill = "#ffffff" if li % 2 == 0 else "#fbfbfc"
        P(
            f'  <rect x="{d.pad}" y="{y}" width="{W - 2 * d.pad}" height="{lane_h[li]}" fill="{fill}" stroke="#d5dde5"/>'
        )
        P(
            f'  <rect x="{d.pad}" y="{y}" width="{d.lane_w}" height="{lane_h[li]}" fill="#f1f3f5" stroke="#d5dde5"/>'
        )
        parts = name.split("\n")
        ty = y + lane_h[li] / 2 - 7 * (len(parts) - 1)
        for part in parts:
            _text(out, d.pad + d.lane_w / 2, ty + 5, part, 12.5, "700", "#3d4852", "middle")
            ty += 15
        y += lane_h[li]
    # column separators
    for ci in range(len(d.columns) + 1):
        cx = grid_x + ci * d.col_w
        P(f'  <line x1="{cx}" y1="{grid_y}" x2="{cx}" y2="{grid_y + grid_h}" stroke="#e9ecef"/>')

    # cards
    centres: list[tuple[float, float]] = []
    for s in d.steps:
        fill, stroke, ink = PALETTE[s.kind]
        w = d.card_w + (s.span - 1) * d.col_w
        h = 34 + d.line_h * len(s.lines) + 6 + (14 if s.badge else 0)
        x = grid_x + s.col * d.col_w + (d.col_w - d.card_w) / 2
        yy = lane_y[s.lane] + (lane_h[s.lane] - h) / 2
        P(
            f'  <rect x="{x}" y="{yy}" width="{w}" height="{h}" rx="7" fill="{fill}" stroke="{stroke}"/>'
        )
        _text(out, x + 10, yy + 18, s.title, 11.5, "700", ink)
        if s.badge:
            bw = 5.4 * len(s.badge) + 10
            P(
                f'  <rect x="{x + w - bw - 6}" y="{yy + h - 17}" width="{bw}" height="13" rx="6" fill="#ffffff" stroke="{stroke}" stroke-width="0.8"/>'
            )
            _text(out, x + w - 6 - bw / 2, yy + h - 7.5, s.badge, 8.5, "700", stroke, "middle")
        ty = yy + 33
        for ln in s.lines:
            _text(out, x + 10, ty, ln, 10.5, None, ink)
            ty += d.line_h
        centres.append((x + w / 2, yy + h / 2))
        # store card bbox for edge anchoring
        s._bbox = (x, yy, w, h)  # type: ignore[attr-defined]

    # edges: leave from right/bottom edge, arrive at left/top edge
    for a, b, label in d.edges:
        ax, ay, aw, ah = d.steps[a]._bbox  # type: ignore[attr-defined]
        bx, by, bw, bh = d.steps[b]._bbox  # type: ignore[attr-defined]
        if d.steps[a].col == d.steps[b].col:
            # vertical within a column
            if ay < by:
                x1, y1, x2, y2 = ax + aw / 2, ay + ah, bx + bw / 2, by
            else:
                x1, y1, x2, y2 = ax + aw / 2, ay, bx + bw / 2, by + bh
            P(
                f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#3d4852" stroke-width="1.3" marker-end="url(#arrow)"/>'
            )
            if label:
                _text(out, x1 + 6, (y1 + y2) / 2 + 3, label, 9.5, None, GREY)
        else:
            x1, y1 = ax + aw, ay + ah / 2
            x2, y2 = bx, by + bh / 2
            mx = (x1 + x2) / 2
            P(
                f'  <path d="M{x1} {y1} L{mx} {y1} L{mx} {y2} L{x2} {y2}" fill="none" stroke="#3d4852" stroke-width="1.3" marker-end="url(#arrow)"/>'
            )
            if label:
                _text(
                    out,
                    mx,
                    min(y1, y2) - 4 if y1 != y2 else y1 - 6,
                    label,
                    9.5,
                    None,
                    GREY,
                    "middle",
                )

    if d.footer:
        fy = grid_y + grid_h + 28
        P(
            f'  <rect x="{d.pad}" y="{fy - 18}" width="{W - 2 * d.pad}" height="{footer_h}" rx="8" fill="#fbfaff" stroke="#6741b8" stroke-width="1"/>'
        )
        for ln in d.footer:
            _text(out, d.pad + 14, fy, ln, 11, None, "#2f1e5c")
            fy += 16
    P("</svg>")
    path.write_text("\n".join(out), encoding="utf-8")
