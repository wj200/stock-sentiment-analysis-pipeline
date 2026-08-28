"""RSS transform mapping (parser logic only; no network).

We feed the real `feedparser` a small structural RSS document and assert the
RSSSource maps entries -> Post correctly (ticker tagging, source label, HTML
cleaning, stable ids). This tests the transform, not a data source: the app
itself only ever reads live feeds.
"""
import feedparser

from ingestion.sources.rss_source import RSSSource

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>news</title>
<item>
  <title>Nvidia beats on earnings, guides higher</title>
  <link>https://example.com/a</link>
  <guid>guid-a</guid>
  <pubDate>Mon, 15 Jul 2024 13:00:00 GMT</pubDate>
  <description>&lt;p&gt;Shares &lt;b&gt;jump&lt;/b&gt; after hours&lt;/p&gt;</description>
</item>
<item>
  <title>Analysts raise NVDA price target</title>
  <link>https://example.com/b</link>
  <guid>guid-b</guid>
  <pubDate>Mon, 15 Jul 2024 14:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def test_rss_transform_maps_entries(monkeypatch):
    src = RSSSource(["NVDA"])
    # bypass the network fetch; exercise the real transform on parsed entries
    monkeypatch.setattr(src, "_parse", lambda url: feedparser.parse(SAMPLE_RSS))

    posts = src.fetch()
    assert len(posts) == 2
    for p in posts:
        assert p.ticker == "NVDA"
        assert p.source == "rss"
        assert p.text  # non-empty
        assert "<" not in p.text and ">" not in p.text  # HTML stripped
        assert len(p.id) == 40  # sha1 hex

    # HTML in the description is cleaned and appended to the title
    assert "jump" in posts[0].text.lower()
    # ids are stable across a re-fetch (idempotency)
    posts2 = src.fetch()
    assert {p.id for p in posts} == {p.id for p in posts2}


def test_rss_bad_feed_status_raises_but_fetch_is_resilient(monkeypatch):
    src = RSSSource(["NVDA"])

    def boom(url):
        raise RuntimeError("HTTP 503")

    monkeypatch.setattr(src, "_parse", boom)
    # a failing feed must not raise out of fetch(); it returns [] for that ticker
    assert src.fetch() == []
