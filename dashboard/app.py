"""Interactive Streamlit dashboard for the stock news/forum sentiment pipeline.

Reads scored sentiment + market price Delta tables (written by
`data_pipeline/spark_streaming.py`), aligns them point-in-time, generates
sentiment-crossing trade signals, backtests them with vectorbt, and renders:

  1. Dual-axis price + net-sentiment chart
  2. Strategy vs. buy & hold cumulative returns chart
  3. Recent raw posts table, color-coded by FinBERT sentiment score
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from config import settings
from data_pipeline.data_alignment import align_sentiment_with_price, fetch_market_data
from data_pipeline.delta_writer import get_spark, read_table
from quant_backtest.backtester import run_backtest, summarize
from quant_backtest.signal_generator import build_signal_frame

st.set_page_config(page_title="Stock Sentiment Pipeline", layout="wide", page_icon="📈")


@st.cache_resource(show_spinner=False)
def _spark_session():
    return get_spark("streamlit-dashboard")


@st.cache_data(ttl=settings.STREAMLIT_REFRESH_SECONDS, show_spinner="Loading scored sentiment from Delta Lake...")
def _load_scored_sentiment() -> pd.DataFrame:
    spark = _spark_session()
    try:
        df = read_table(spark, settings.SCORED_SENTIMENT_TABLE).toPandas()
    except Exception:
        return pd.DataFrame(
            columns=["id", "ticker", "timestamp", "source", "text", "positive", "neutral", "negative", "sentiment_score"]
        )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


@st.cache_data(ttl=settings.STREAMLIT_REFRESH_SECONDS, show_spinner="Fetching market prices...")
def _load_market_prices(tickers: tuple[str, ...], interval: str) -> pd.DataFrame:
    return fetch_market_data(list(tickers), period="60d", interval=interval)


WINDOW_TO_YF_INTERVAL = {"15m": "15m", "1h": "1h", "4h": "1h", "24h": "1d"}


def _sentiment_color(score: float) -> str:
    if score > 0.2:
        return "background-color: rgba(46, 204, 113, 0.35)"
    if score < -0.2:
        return "background-color: rgba(231, 76, 60, 0.35)"
    return "background-color: rgba(241, 196, 15, 0.25)"


def render_sidebar() -> tuple[str, str]:
    st.sidebar.title("Controls")
    ticker = st.sidebar.selectbox("Ticker", settings.TICKERS, index=0)
    window_label = st.sidebar.selectbox("Rolling sentiment window", list(settings.ROLLING_WINDOWS.keys()), index=1)
    st.sidebar.caption(
        f"Entry when sentiment > {settings.ENTRY_SENTIMENT_THRESHOLD:+.1f}, "
        f"exit when sentiment < {settings.EXIT_SENTIMENT_THRESHOLD:+.1f}"
    )
    if st.sidebar.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()
    return ticker, window_label


def render_price_sentiment_chart(aligned_df: pd.DataFrame, ticker: str, window_label: str) -> None:
    ticker_df = aligned_df[aligned_df["ticker"] == ticker].sort_values("timestamp")
    if ticker_df.empty:
        st.warning(f"No aligned price/sentiment data available for {ticker} yet.")
        return

    roll_col = f"sentiment_roll_{window_label}"
    sentiment_series = ticker_df[roll_col] if roll_col in ticker_df.columns else ticker_df["avg_sentiment"]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=ticker_df["timestamp"],
            y=ticker_df["close"],
            name=f"{ticker} price",
            line=dict(color="#1f77b4", width=2),
        ),
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
        height=480,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=20),
    )
    fig.update_yaxes(title_text="Price ($)", secondary_y=False)
    fig.update_yaxes(title_text="Sentiment score", range=[-1, 1], secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)


def render_backtest_chart(signal_df: pd.DataFrame, ticker: str) -> None:
    try:
        result = run_backtest(signal_df, ticker)
    except ValueError as exc:
        st.warning(str(exc))
        return

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
        title=f"{ticker}: Strategy vs. Buy & Hold Cumulative Return",
        yaxis_title="Cumulative return (%)",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    stats = summarize(result)
    cols = st.columns(4)
    cols[0].metric("Total Return", f"{stats['total_return_pct']}%", f"{stats['total_return_pct'] - stats['benchmark_total_return_pct']:+.2f} pp vs B&H")
    cols[1].metric("Sharpe Ratio", stats["sharpe_ratio"])
    cols[2].metric("Max Drawdown", f"{stats['max_drawdown_pct']}%")
    cols[3].metric("Buy & Hold Return", f"{stats['benchmark_total_return_pct']}%")


def render_recent_posts_table(scored_df: pd.DataFrame, ticker: str) -> None:
    recent = (
        scored_df[scored_df["ticker"] == ticker]
        .sort_values("timestamp", ascending=False)
        .head(50)[["timestamp", "source", "text", "positive", "neutral", "negative", "sentiment_score"]]
    )
    if recent.empty:
        st.info("No recent posts scored yet for this ticker.")
        return

    styled = recent.style.applymap(lambda v: _sentiment_color(v) if isinstance(v, float) else "", subset=["sentiment_score"])
    st.dataframe(styled, use_container_width=True, height=400)


def main() -> None:
    st.title("📈 Stock News & Forum Sentiment Pipeline")
    ticker, window_label = render_sidebar()

    scored_df = _load_scored_sentiment()
    market_df = _load_market_prices(tuple(settings.TICKERS), WINDOW_TO_YF_INTERVAL[window_label])

    if scored_df.empty or market_df.empty:
        st.info(
            "No scored sentiment or market data found yet. Start the ingestion producer and "
            "the Spark streaming job (see docker-compose.yml), or run a backfill, then refresh."
        )
        return

    aligned_df = align_sentiment_with_price(scored_df, market_df, window=settings.ROLLING_WINDOWS["15m"])
    signal_df = build_signal_frame(aligned_df, signal_window_label=window_label)

    render_price_sentiment_chart(signal_df, ticker, window_label)
    st.divider()
    render_backtest_chart(signal_df, ticker)
    st.divider()
    st.subheader("Recent forum/news posts")
    render_recent_posts_table(scored_df, ticker)


if __name__ == "__main__":
    main()
