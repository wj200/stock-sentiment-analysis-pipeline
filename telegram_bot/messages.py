"""HTML message formatting for Feature 2/3 alerts (shared by /why and dispatcher).

Every event message ends with the not-advice disclaimer (GUARD-2).
"""
from __future__ import annotations

import html

from explain import DISCLAIMER
from explain.explainer import Explanation


def _arrow(direction: str) -> str:
    return "🔺" if direction == "up" else "🔻"


def format_price_move(ticker: str, pct: float, session: str, ref_price: float,
                      last: float, explanation: Explanation) -> str:
    head = (
        f"{_arrow('up' if pct >= 0 else 'down')} <b>${html.escape(ticker)}</b> "
        f"{pct:+.1f}% {html.escape(session)}-market "
        f"(ref {ref_price:.2f} → {last:.2f})"
    )
    why = html.escape(explanation.text)
    lines = [head, f"Why: {why}"]
    src = explanation.source_line()
    if src:
        lines.append(f"Sources: {html.escape(src)}")
    lines.append(f"<i>{DISCLAIMER}</i>")
    return "\n".join(lines)


def format_macro(label: str, actual, consensus, prior, explanation: Explanation) -> str:
    cons = "n/a" if consensus is None else consensus
    head = f"🏛️ <b>{html.escape(label)}</b> — actual <b>{actual}</b> (cons {cons}, prior {prior})"
    lines = [head, f"{html.escape(explanation.text)}"]
    src = explanation.source_line()
    if src:
        lines.append(f"Sources: {html.escape(src)}")
    lines.append(f"<i>{DISCLAIMER}</i>")
    return "\n".join(lines)
