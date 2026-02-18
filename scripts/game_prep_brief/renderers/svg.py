from __future__ import annotations


def _safe_max(values: list[float]) -> float:
    return max([v for v in values if v is not None] or [0.0])


def horizontal_bar(
    value: float,
    max_val: float,
    width: int = 200,
    height: int = 16,
    color: str = "#2563eb",
) -> str:
    """Returns inline SVG string for a horizontal progress bar."""
    max_val = max(max_val, 1)
    val = max(0.0, min(float(value), float(max_val)))
    filled = int((val / max_val) * width)

    return (
        f"<svg width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\" "
        f"xmlns=\"http://www.w3.org/2000/svg\">"
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" rx=\"{height//2}\" fill=\"#e5e7eb\"/>"
        f"<rect x=\"0\" y=\"0\" width=\"{filled}\" height=\"{height}\" rx=\"{height//2}\" fill=\"{color}\"/>"
        f"</svg>"
    )


def comparison_bars(
    label: str,
    val1: float,
    val2: float,
    color1: str,
    color2: str,
    width: int = 300,
) -> str:
    """Returns inline SVG showing two teams side by side for a metric."""
    height = 44
    bar_height = 10
    gutter = 8
    label_y = 14
    bar_y1 = 22
    bar_y2 = 34
    max_val = _safe_max([val1, val2, 1])

    def bar_width(val: float) -> int:
        return int((max(0.0, val) / max_val) * width)

    w1 = bar_width(val1)
    w2 = bar_width(val2)

    return (
        f"<svg width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\" "
        f"xmlns=\"http://www.w3.org/2000/svg\">"
        f"<text x=\"0\" y=\"{label_y}\" font-size=\"10\" fill=\"#374151\">{label}</text>"
        f"<rect x=\"0\" y=\"{bar_y1}\" width=\"{width}\" height=\"{bar_height}\" fill=\"#e5e7eb\"/>"
        f"<rect x=\"0\" y=\"{bar_y1}\" width=\"{w1}\" height=\"{bar_height}\" fill=\"{color1}\"/>"
        f"<rect x=\"0\" y=\"{bar_y2}\" width=\"{width}\" height=\"{bar_height}\" fill=\"#e5e7eb\"/>"
        f"<rect x=\"0\" y=\"{bar_y2}\" width=\"{w2}\" height=\"{bar_height}\" fill=\"{color2}\"/>"
        f"</svg>"
    )
