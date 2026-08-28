"""Extract ticker symbols from free text, scoped to the tracked universe.

Two signals, both constrained to `universe` so we never ingest chatter about
symbols we don't track and never guess a bare English word into a ticker:

  1. Cashtags: `$NVDA` — high precision, any length, matched against the universe.
  2. Bare symbols: `NVDA` as a standalone token — only for symbols of length >= 3
     (so short/common tickers like `A`, `IT`, `ON` can't false-positive off prose;
     those still work via cashtag).
"""
from __future__ import annotations

import re

_CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,5})(?![A-Za-z])")


def extract_tickers(text: str | None, universe: list[str]) -> list[str]:
    if not text:
        return []
    uni = {t.upper() for t in universe}
    found: set[str] = set()

    for m in _CASHTAG_RE.finditer(text):
        sym = m.group(1).upper()
        if sym in uni:
            found.add(sym)

    upper = text.upper()
    for sym in uni:
        if len(sym) < 3:
            continue  # bare-token match only for >=3 chars; use $CASHTAG for the rest
        # word-boundary that also treats '.'/digits as boundaries (BRK.B etc. still ok)
        if re.search(rf"(?<![A-Z0-9]){re.escape(sym)}(?![A-Z0-9])", upper):
            found.add(sym)

    return sorted(found)
