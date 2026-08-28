from ingestion.sources.ticker_extract import extract_tickers

UNIVERSE = ["AAPL", "NVDA", "TSLA", "MSFT"]


def test_cashtag_in_universe():
    assert extract_tickers("$NVDA breaking out hard", UNIVERSE) == ["NVDA"]


def test_cashtag_case_insensitive():
    assert extract_tickers("loading up on $tsla calls", UNIVERSE) == ["TSLA"]


def test_cashtag_not_in_universe_ignored():
    assert extract_tickers("$FOO mooning", UNIVERSE) == []


def test_bare_symbols_matched_and_sorted():
    assert extract_tickers("NVDA and AAPL both ripping", UNIVERSE) == ["AAPL", "NVDA"]


def test_plain_prose_no_false_positive():
    assert extract_tickers("the cat sat on the mat", UNIVERSE) == []


def test_short_ticker_only_via_cashtag():
    # 'IT' is a common word; a bare occurrence must not match, only the cashtag.
    uni = ["IT", "NVDA"]
    assert extract_tickers("it is what it is", uni) == []
    assert extract_tickers("$IT earnings tonight", uni) == ["IT"]


def test_empty_text():
    assert extract_tickers("", UNIVERSE) == []
    assert extract_tickers(None, UNIVERSE) == []


def test_symbol_inside_word_not_matched():
    # 'MSFT' should not match inside 'MSFTX' or similar token.
    assert extract_tickers("MSFTX is not microsoft", UNIVERSE) == []
