"""Renders the dashboard's Plotly figures to PNG bytes for Telegram photo messages.

Telegram has no notion of an interactive chart, so every figure is rasterized
with `kaleido` before being sent via `bot.send_photo`.
"""
import io

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from quant_backtest.backtester import BacktestResult


def _fig_to_png_bytes(fig: go.Figure, width: int = 1000, height: int = 560) -> io.BytesIO:
    png_bytes = fig.to_image(format="png", width=width, height=height, scale=2)
    buf = io.BytesIO(png_bytes)
    buf.name = "chart.png"
    buf.seek(0)
    return buf


def price_sentiment_chart(signal_df: pd.DataFrame, ticker: str, window_label: str) -> io.BytesIO | None:
    ticker_df = signal_df[signal_df["ticker"] == ticker].sort_values("timestamp")
    if ticker_df.empty:
        return None

    roll_col = f"sentiment_roll_{window_label}"
    sentiment_series = ticker_df[roll_col] if roll_col in ticker_df.columns else ticker_df["avg_sentiment"]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(x=ticker_df["timestamp"], y=ticker_df["close"], name=f"{ticker} price", line=dict(color="#1f77b4", width=2)),
        secondary_y=False,
    )
    bar_colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in sentiment_series.fillna(0)]
    fig.add_trace(
        go.Bar(
            x=ticker_df["timestamp"],
            y=sentiment_series,
            name=f"Net sentiment ({window_label} rolling)",
            marker_color=bar_colors,
            opacity=0.55,
        ),
        secondary_y=True,
    )
    fig.update_layout(
        title=f"{ticker}: Price vs. Net Sentiment",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=20),
        template="plotly_white",
    )
    fig.update_yaxes(title_text="Price ($)", secondary_y=False)
    fig.update_yaxes(title_text="Sentiment score", range=[-1, 1], secondary_y=True)
    return _fig_to_png_bytes(fig)


def backtest_chart(result: BacktestResult) -> io.BytesIO:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=result.cumulative_returns.index,
            y=result.cumulative_returns * 100,
            name="Sentiment strategy",
            line=dict(color="#2ecc71", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=result.benchmark_cumulative_returns.index,
            y=result.benchmark_cumulative_returns * 100,
            name="Buy & hold",
            line=dict(color="#7f8c8d", width=2, dash="dash"),
        )
    )
    fig.update_layout(
        title=f"{result.ticker}: Strategy vs. Buy & Hold Cumulative Return",
        yaxis_title="Cumulative return (%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=20),
        template="plotly_white",
    )
    return _fig_to_png_bytes(fig)
