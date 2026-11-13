"""Dependency-free SVG plots for showcase benchmark reports (issue #198).

Plots are rendered from the JSON report (the source of truth), never from
hand-typed numbers, so a published figure always matches the committed report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Mapping, Optional
from xml.sax.saxutils import escape

ACCENT = "#0b6bcb"
MUTED = "#8a94a6"
GRID = "#d7dde8"
INK = "#1f2733"
BACKGROUND = "#ffffff"
PADDING = 12

_STYLE = (
    f"font-family='-apple-system,Segoe UI,Helvetica,Arial,sans-serif' "
    f"font-size='12' fill='{INK}'"
)


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _rows(report: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [row for row in (report.get("rows") or []) if isinstance(row, Mapping)]


def _title(report: Mapping[str, Any]) -> str:
    suite = report.get("suite") or {}
    name = suite.get("suite") if isinstance(suite, Mapping) else None
    return f"Showcase benchmark: {name or 'suite'}"


def _empty_svg(width: int, height: int, message: str) -> str:
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' role='img'>"
        f"<rect width='{width}' height='{height}' fill='{BACKGROUND}'/>"
        f"<text x='{width // 2}' y='{height // 2}' text-anchor='middle' {_STYLE}>"
        f"{escape(message)}</text></svg>"
    )


def render_pareto_svg(report: Mapping[str, Any]) -> str:
    """Scatter of quality vs cost per combination, highlighting the Pareto set."""
    rows = _rows(report)
    width, height = 760, 420
    if not rows:
        return _empty_svg(width, height, "No combinations in report")

    left, right, top, bottom = 78, 36, 56, 74
    plot_w = width - left - right
    plot_h = height - top - bottom
    frontier = set(report.get("pareto_frontier") or [])

    costs = [max(0.0, _num(row.get("cost_usd"))) for row in rows]
    quality = [_num(row.get("quality")) for row in rows]
    max_cost = max(costs) or 1.0
    max_quality = max(1.0, max(quality) or 1.0)

    parts: List[str] = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' role='img'>",
        f"<rect width='{width}' height='{height}' fill='{BACKGROUND}'/>",
        f"<text x='{left}' y='26' font-size='15' font-weight='600' {_STYLE}>"
        f"{escape(_title(report))} - quality vs cost</text>",
        f"<text x='{left}' y='44' {_STYLE} fill='{MUTED}'>"
        "Filled points are on the Pareto frontier; reference CPU numbers.</text>",
    ]

    for step in range(5):
        y = top + plot_h * step / 4
        value = max_quality * (1 - step / 4)
        parts.append(
            f"<line x1='{left}' y1='{y:.1f}' x2='{left + plot_w}' y2='{y:.1f}' "
            f"stroke='{GRID}' stroke-width='1'/>"
        )
        parts.append(
            f"<text x='{left - 10}' y='{y + 4:.1f}' text-anchor='end' {_STYLE} "
            f"fill='{MUTED}'>{value:.2f}</text>"
        )
    for step in range(5):
        x = left + plot_w * step / 4
        value = max_cost * step / 4
        parts.append(
            f"<line x1='{x:.1f}' y1='{top}' x2='{x:.1f}' y2='{top + plot_h}' "
            f"stroke='{GRID}' stroke-width='1'/>"
        )
        parts.append(
            f"<text x='{x:.1f}' y='{top + plot_h + 18}' text-anchor='middle' {_STYLE} "
            f"fill='{MUTED}'>${value:.6f}</text>"
        )

    parts.append(
        f"<line x1='{left}' y1='{top + plot_h}' x2='{left + plot_w}' "
        f"y2='{top + plot_h}' stroke='{INK}' stroke-width='1'/>"
    )
    parts.append(
        f"<line x1='{left}' y1='{top}' x2='{left}' y2='{top + plot_h}' "
        f"stroke='{INK}' stroke-width='1'/>"
    )
    parts.append(
        f"<text x='{left + plot_w / 2:.1f}' y='{height - 16}' text-anchor='middle' "
        f"{_STYLE}>Cost per request (USD)</text>"
    )
    parts.append(
        f"<text x='18' y='{top + plot_h / 2:.1f}' text-anchor='middle' {_STYLE} "
        f"transform='rotate(-90 18 {top + plot_h / 2:.1f})'>Quality</text>"
    )

    for row, cost, qual in zip(rows, costs, quality):
        x = left + (cost / max_cost) * plot_w
        y = top + (1 - (qual / max_quality)) * plot_h
        combo = str(row.get("combination_id"))
        on_frontier = combo in frontier
        radius = 7 if on_frontier else 5
        fill = ACCENT if on_frontier else BACKGROUND
        parts.append(
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{radius}' fill='{fill}' "
            f"stroke='{ACCENT}' stroke-width='2'><title>{escape(combo)}: "
            f"quality {qual:.4f}, cost ${cost:.6f}</title></circle>"
        )
        parts.append(
            f"<text x='{x + 10:.1f}' y='{y - 8:.1f}' {_STYLE} fill='{INK}'>"
            f"{escape(combo)}</text>"
        )

    parts.append(
        f"<text x='{left + plot_w - 4}' y='{top + 16}' text-anchor='end' {_STYLE} "
        f"fill='{MUTED}'>frontier: {len(frontier)} of {len(rows)} combinations</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def render_latency_svg(report: Mapping[str, Any]) -> str:
    """Grouped bars of mean and p95 latency per combination."""
    rows = _rows(report)
    width, height = 760, 400
    if not rows:
        return _empty_svg(width, height, "No combinations in report")

    left, right, top, bottom = 78, 36, 56, 74
    plot_w = width - left - right
    plot_h = height - top - bottom

    mean = [_num(row.get("latency_ms")) for row in rows]
    p95 = [_num(row.get("p95_latency_ms")) for row in rows]
    max_ms = max(mean + p95) or 1.0

    parts: List[str] = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' role='img'>",
        f"<rect width='{width}' height='{height}' fill='{BACKGROUND}'/>",
        f"<text x='{left}' y='26' font-size='15' font-weight='600' {_STYLE}>"
        f"{escape(_title(report))} - latency by combination</text>",
        f"<text x='{left}' y='44' {_STYLE} fill='{MUTED}'>"
        "Client-observed pipeline latency; reference CPU numbers.</text>",
    ]

    for step in range(5):
        y = top + plot_h * step / 4
        value = max_ms * (1 - step / 4)
        parts.append(
            f"<line x1='{left}' y1='{y:.1f}' x2='{left + plot_w}' y2='{y:.1f}' "
            f"stroke='{GRID}' stroke-width='1'/>"
        )
        parts.append(
            f"<text x='{left - 10}' y='{y + 4:.1f}' text-anchor='end' {_STYLE} "
            f"fill='{MUTED}'>{value:.0f}</text>"
        )

    group_w = plot_w / len(rows)
    bar_w = min(28.0, group_w * 0.32)
    for index, row in enumerate(rows):
        center = left + group_w * (index + 0.5)
        combo = str(row.get("combination_id"))
        for offset, value, color in (
            (-bar_w * 0.6, mean[index], ACCENT),
            (bar_w * 0.6, p95[index], MUTED),
        ):
            bar_h = (value / max_ms) * plot_h if max_ms else 0.0
            x = center + offset - bar_w / 2
            y = top + plot_h - bar_h
            parts.append(
                f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_w:.1f}' "
                f"height='{bar_h:.1f}' fill='{color}'><title>{escape(combo)}: "
                f"{value:.1f} ms</title></rect>"
            )
        parts.append(
            f"<text x='{center:.1f}' y='{top + plot_h + 18}' text-anchor='middle' "
            f"{_STYLE}>{escape(combo)}</text>"
        )

    parts.append(
        f"<line x1='{left}' y1='{top + plot_h}' x2='{left + plot_w}' "
        f"y2='{top + plot_h}' stroke='{INK}' stroke-width='1'/>"
    )
    parts.append(
        f"<text x='18' y='{top + plot_h / 2:.1f}' text-anchor='middle' {_STYLE} "
        f"transform='rotate(-90 18 {top + plot_h / 2:.1f})'>Latency (ms)</text>"
    )
    legend_y = height - 24
    parts.append(
        f"<rect x='{left}' y='{legend_y - 10}' width='12' height='12' fill='{ACCENT}'/>"
        f"<text x='{left + 18}' y='{legend_y}' {_STYLE}>mean</text>"
    )
    parts.append(
        f"<rect x='{left + 76}' y='{legend_y - 10}' width='12' height='12' fill='{MUTED}'/>"
        f"<text x='{left + 94}' y='{legend_y}' {_STYLE}>p95</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def write_plots(
    report: Mapping[str, Any],
    svg_dir: str | Path,
    *,
    stem: str = "report",
) -> List[Path]:
    """Write ``<stem>-pareto.svg`` and ``<stem>-latency.svg``; return the paths."""
    target = Path(svg_dir)
    target.mkdir(parents=True, exist_ok=True)
    pareto = target / f"{stem}-pareto.svg"
    latency = target / f"{stem}-latency.svg"
    pareto.write_text(render_pareto_svg(report), encoding="utf-8")
    latency.write_text(render_latency_svg(report), encoding="utf-8")
    return [pareto, latency]


def plot_stem_for(report_path: Optional[str | Path], fallback: str = "report") -> str:
    if not report_path:
        return fallback
    return Path(report_path).stem
