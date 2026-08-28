"""Bot state watches/macro (B1/C1) + event message formatting (guardrail footer)."""
from explain.explainer import Explanation
from explain.news_retrieval import NewsItem
from telegram_bot.messages import format_macro, format_price_move
from telegram_bot.state import StateStore


def test_watch_add_remove_and_persist(tmp_path):
    path = tmp_path / "state.json"
    s = StateStore(path=path)
    s.add_watch(1, "nvda")
    s.add_watch(2, "NVDA")
    assert set(s.watchers_for("NVDA")) == {1, 2}
    s.remove_watch(1, "NVDA")
    assert s.watchers_for("NVDA") == [2]
    # de-dup: adding twice keeps one
    s.add_watch(2, "NVDA")
    assert s.get(2).watched_tickers.count("NVDA") == 1
    # reload from disk keeps state
    s2 = StateStore(path=path)
    assert s2.watchers_for("NVDA") == [2]


def test_macro_opt_in(tmp_path):
    s = StateStore(path=tmp_path / "state.json")
    s.set_macro(7, True)
    assert s.macro_opt_in_chat_ids() == [7]
    s.set_macro(7, False)
    assert s.macro_opt_in_chat_ids() == []


def test_format_price_move_has_disclaimer_and_sources():
    exp = Explanation(
        text="Guidance cut below consensus [1].",
        sources=[NewsItem("h", "Reuters", "http://x", "2024-07-15T13:00:00+00:00")],
        grounded=True,
    )
    msg = format_price_move("NVDA", -6.1, "pre", 118.2, 110.98, exp)
    assert "$NVDA" in msg
    assert "-6.1%" in msg
    assert "Not financial advice" in msg
    assert "Sources:" in msg


def test_format_macro_has_disclaimer():
    exp = Explanation(text="CPI hotter than expected.", sources=[], grounded=True)
    msg = format_macro("CPI (All Urban Consumers)", 3.4, 3.2, 3.1, exp)
    assert "CPI" in msg and "3.4" in msg
    assert "Not financial advice" in msg
