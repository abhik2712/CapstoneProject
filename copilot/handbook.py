"""Adapt the repository's BM25 and hybrid retrievers to the copilot."""
import json
import os
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
# Upstream retrieval modules have sibling imports for their script entry points.
sys.path.insert(0, str(ROOT / "retrieval"))

from search_bm25 import BM25, terms

REVISION = "8fce82673398dbfad74c667e7b35eb75d101d55d"
EXPENSES = f"https://gitlab.com/gitlab-com/content-sites/handbook/-/blob/{REVISION}/content/handbook/finance/expenses.md"
AFFIDAVIT_CITATION = f"{EXPENSES}#L684-686"
REQUIRED_CITATIONS = {
    "equipment": f"{EXPENSES}#L416-423",
    "personal_payment": f"{EXPENSES}#L64-65",
    "new_hire": f"{EXPENSES}#L427-430",
    "annual_refresh": f"{EXPENSES}#L432-437",
}


def pinned_sources(hits):
    prefix = f"https://gitlab.com/gitlab-com/content-sites/handbook/-/blob/{REVISION}/content/handbook/"
    return [
        {"title": " · ".join([hit["title"], *hit.get("headings", [])]), "url": hit["citation"],
         "text": hit["text"]}
        for hit in hits if hit["citation"].startswith(prefix)
    ]


def missing_receipt_source(question, sources):
    words = set(terms(question))
    if "receipt" in words and words.intersection({"lost", "missing", "misplaced"}):
        return next((source for source in sources if source["url"] == AFFIDAVIT_CITATION), None)
    return None


class HandbookSearch:
    def __init__(self, live_search=None):
        passages = Path(__file__).parent / "data" / "expenses.json"
        self.demo_index = BM25(json.loads(passages.read_text(encoding="utf-8")))
        self.live_search = live_search
        # The fixed equipment query contains no user data. Its sources are pinned.
        self.equipment = lru_cache(maxsize=1)(self._equipment)

    def _equipment(self):
        hits = self.demo_index.search(
            "equipment stipend new hire refresh Navan allowance gift cards out-of-pocket monitor", top_k=6
        )
        return tuple(pinned_sources(hits))

    def search(self, question):
        hits = self.live_search(question) if self.live_search else self.demo_index.search(question, top_k=3)
        return pinned_sources(hits)


def course_chat():
    """Use the same chat endpoint and model as the evaluation."""
    from evaluate_rag import chat_credentials, request

    names = ("CAPSTONE_CHAT_BASE_URL", "CAPSTONE_CHAT_CA", "CAPSTONE_CHAT_API_KEY")
    missing = [name for name in names if not os.getenv(name, "").strip()]
    if missing:
        raise ValueError("Set these course chat environment variables before starting: " + ", ".join(missing))
    connection = chat_credentials(SimpleNamespace(
        chat_base_url=os.environ["CAPSTONE_CHAT_BASE_URL"],
        chat_ca=os.environ["CAPSTONE_CHAT_CA"],
    ))

    def answer(messages):
        return request(*connection, messages)

    return answer


def course_clients():
    """Connect the full hybrid index and the course chat endpoint."""
    from build_embeddings import INDEX_FILE, load_tokenizer, open_client
    from search_hybrid import HybridSearch
    from search_semantic import embed_queries

    answer = course_chat()
    access_zip = os.getenv("CAPSTONE_EMBED_ACCESS_ZIP")
    if not access_zip and not os.getenv("CAPSTONE_EMBED_API_KEY", "").strip():
        raise ValueError("Live mode needs the assigned embeddings credentials. See the README.")
    args = SimpleNamespace(
        access_zip=Path(access_zip) if access_zip else None,
        base_url=os.getenv("CAPSTONE_EMBED_BASE_URL"),
        ca=os.getenv("CAPSTONE_EMBED_CA"),
    )
    with closing(open_client(args)):
        pass
    index = HybridSearch(Path(os.getenv("CAPSTONE_INDEX", ROOT / INDEX_FILE)))
    path = os.getenv("CAPSTONE_TOKENIZER")
    tokenizer = load_tokenizer(Path(path) if path else None)

    def search(question):
        # Each request owns its HTTPS connection. The loaded index is read-only.
        with closing(open_client(args)) as client:
            vector, = embed_queries([question], tokenizer, client)
        return index.search(question, vector, top_k=5)

    return HandbookSearch(search), answer
