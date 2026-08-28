"""Retrieval-grounded event explanation layer (Features 2 & 3).

The LLM here only ever explains a price move or a macro release FROM retrieved
sources (headlines / release numbers). It cites them or refuses; it never gives
trading advice and never runs in the per-post hot path. Guardrails are
structural (output validation in `prompts.py`), not just prompt text — a
successful injection can at worst produce a sentence, which validation bounds.
"""
from explain.explainer import Explanation, explain_macro, explain_price_move
from explain.news_retrieval import NewsItem, NewsRetriever, get_retriever
from explain.llm_provider import LLMProvider, get_provider, model_for

# Rides on every Feature 2/3 alert (GUARD-2).
DISCLAIMER = "Not financial advice. Information only."

__all__ = [
    "Explanation", "explain_price_move", "explain_macro",
    "NewsItem", "NewsRetriever", "get_retriever",
    "LLMProvider", "get_provider", "model_for", "DISCLAIMER",
]
