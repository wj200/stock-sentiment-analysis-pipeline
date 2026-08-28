"""Live market quotes and price-move detection (Feature 2).

`quotes.py` fetches real prices (yfinance keyless by default, Alpaca when keyed)
and exposes a pure `evaluate_move` used by both the price monitor and the
on-demand `/why` command.
"""
