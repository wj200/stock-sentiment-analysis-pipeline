"""H1: no-advice guardrail precision + A6 validation report assembly."""
from types import SimpleNamespace

from explain import DISCLAIMER
from explain.prompts import validate
from quant_backtest.validation import build_report


def test_disclaimer_present():
    assert DISCLAIMER and "advice" in DISCLAIMER.lower()


# The advice guardrail must catch recommendations WITHOUT tripping on ordinary
# financial vocabulary that legitimately appears in factual explanations.
def test_advice_phrases_rejected():
    for bad in [
        "You should buy now [1].",
        "Analysts issued a strong buy [1].",
        "We recommend buying the dip [1].",
        "Raised price target to $200 [1].",
        "Load up the stock here [1].",
    ]:
        ok, reason = validate(bad, had_sources=True)
        assert ok is False, f"should reject: {bad}"
        assert reason == "trading_advice"


def test_factual_finance_words_not_flagged():
    for good in [
        "The company announced a buyback [1].",
        "Shares fell in a broad sell-off [1].",
        "A big seller pressured the stock [1].",
        "Guidance was cut below consensus [1].",
    ]:
        ok, _ = validate(good, had_sources=True)
        assert ok is True, f"should accept: {good}"


def _fake(ticker, strat, bench, sharpe=1.0, dd=-5.0):
    return SimpleNamespace(
        ticker=ticker, total_return_pct=strat, sharpe_ratio=sharpe, max_drawdown_pct=dd,
        benchmark_total_return_pct=bench, benchmark_sharpe_ratio=0.8,
    )


def test_build_report_ranks_by_edge_over_benchmark():
    results = {
        "AAPL": _fake("AAPL", 5.0, 10.0),   # underperforms by 5pp
        "NVDA": _fake("NVDA", 20.0, 8.0),   # beats by 12pp
    }
    report = build_report(results)
    assert report["tickers"][0]["ticker"] == "NVDA"       # best edge first
    assert report["tickers"][0]["beat_benchmark_pp"] == 12.0
    assert report["tickers"][1]["beat_benchmark_pp"] == -5.0  # honest about underperformance
    assert "generated_at" in report
