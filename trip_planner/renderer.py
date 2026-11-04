"""Render validated saved plans as portable, escaped, offline HTML."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import webbrowser

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .models import SavedPlan


PACKAGE_DIR = Path(__file__).resolve().parent


def _money(value: float | None, currency: str) -> str:
    if value is None:
        return "Unknown"
    return f"{currency} {value:,.2f}"


def _timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    except ValueError:
        return value


def render_plan(plan: SavedPlan, path: Path) -> Path:
    """Atomically replace a standalone page without modifying its source plan.

    The only trusted markup is this package's CSS. All itinerary content goes
    through Jinja's HTML autoescaping, including model-generated text.
    """
    path = Path(path).expanduser().resolve()
    environment = Environment(
        loader=FileSystemLoader(PACKAGE_DIR / "templates"),
        autoescape=select_autoescape(default_for_string=True, default=True),
    )
    environment.filters["money"] = _money
    environment.filters["timestamp"] = _timestamp
    categories = plan.budget_summary.category_totals
    category_max = max(categories.values(), default=0) or 1
    category_bars = [
        {"name": name, "amount": amount, "width": round(amount / category_max * 100, 2)}
        for name, amount in categories.items()
    ]
    budget = plan.budget_summary
    budget_used = None
    if budget.budget_limit:
        budget_used = round(min(budget.estimated_total / budget.budget_limit * 100, 100), 2)
    page = environment.get_template("itinerary.html.j2").render(
        plan=plan,
        css=Markup((PACKAGE_DIR / "static" / "styles.css").read_text(encoding="utf-8")),
        category_bars=category_bars,
        budget_used=budget_used,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".itinerary-", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(page)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


def open_plan(path: Path) -> bool:
    """Ask the system browser to open an existing page; callers report failure."""
    return webbrowser.open(Path(path).expanduser().resolve().as_uri())
