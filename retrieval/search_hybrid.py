"""Find citable handbook passages with BM25, BGE, and a local reranking pass."""
import argparse
import json
import math
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from build_embeddings import INDEX_FILE, ROOT, add_access_options, load_tokenizer, open_client
from search_bm25 import BM25, terms
from search_semantic import SemanticIndex, embed_queries

RRF_K = 60
DEFAULT_CANDIDATES = 30


def fuse_rankings(keyword, semantic):
    """Combine ranks without treating keyword and cosine scores as comparable."""
    candidates = {}
    for name, hits in (("bm25", keyword), ("semantic", semantic)):
        for rank, hit in enumerate(hits, 1):
            ident = hit["chunk_id"]
            row = candidates.setdefault(
                ident, {k: v for k, v in hit.items() if k != "score"}
            )
            row.setdefault("ranks", {}).setdefault(name, rank)
    for row in candidates.values():
        row["rrf_score"] = sum(1 / (RRF_K + rank) for rank in row["ranks"].values())
    return sorted(candidates.values(), key=lambda r: (-r["rrf_score"], r["chunk_id"]))


class HybridSearch:
    def __init__(self, index_path):
        self.semantic = SemanticIndex(index_path)
        # Both search methods use identical frozen passages and chunk IDs.
        self.keyword = BM25(json.loads(doc) for _, doc, _ in self.semantic.rows)

    def retrieve(self, query, query_vector, candidates=DEFAULT_CANDIDATES):
        if candidates < 1:
            raise ValueError("candidates must be positive.")
        return (
            self.keyword.search(query, candidates),
            self.semantic.search_vector(query_vector, candidates),
        )

    def rerank(self, query, fused):
        query_terms = tuple(terms(query))
        count = len(self.keyword.chunks)
        # Give repeated search terms only one vote and weight up rare words.
        weights = {
            term: math.log1p((count + 0.5) / (len(self.keyword.postings[term]) + 0.5))
            for term in dict.fromkeys(query_terms)
            if term in self.keyword.postings
        }
        total = sum(weights.values())
        pairs = {(a, b) for a, b in zip(query_terms, query_terms[1:]) if a != b}
        ranked = []
        for row in fused:
            # Chunk text begins with a repeated title and heading prefix. A
            # term in the actual evidence body carries more weight.
            heading, _, body = row["text"].partition("\n\n")
            head_terms = set(terms(heading))
            body_terms = tuple(terms(body))
            body_set = set(body_terms)
            coverage = sum(weight * (1 if word in body_set else 0.25 if word in head_terms else 0)
                           for word, weight in weights.items()) / (total or 1)
            adjacent = pairs.intersection(zip(body_terms, body_terms[1:]))
            phrase = len(adjacent) / (len(pairs) or 1)
            fusion = row["rrf_score"] * (RRF_K + 1) / 2
            score = 0.70 * fusion + 0.25 * coverage + 0.05 * phrase
            ranked.append(dict(row, rerank_score=score, weighted_term_coverage=coverage,
                               phrase_match_fraction=phrase))
        return sorted(
            ranked, key=lambda r: (-r["rerank_score"], -r["rrf_score"], r["chunk_id"])
        )

    def search(self, query, query_vector, top_k=5, candidates=DEFAULT_CANDIDATES, rerank=True):
        if not 1 <= top_k <= candidates:
            raise ValueError("Require 1 ≤ top-k ≤ candidates.")
        fused = fuse_rankings(*self.retrieve(query, query_vector, candidates))
        ranked = self.rerank(query, fused) if rerank else fused
        return ranked[:top_k]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--index", type=Path, default=ROOT / INDEX_FILE)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidates", type=int, default=DEFAULT_CANDIDATES)
    parser.add_argument("--fusion-only", action="store_true", help="Skip the second-pass reranker.")
    parser.add_argument("--json", action="store_true")
    add_access_options(parser)
    args = parser.parse_args()
    if not 1 <= args.top_k <= args.candidates:
        parser.error("Require 1 ≤ --top-k ≤ --candidates.")
    try:
        search = HybridSearch(args.index)
        tokenizer = load_tokenizer(args.tokenizer)
        with closing(open_client(args)) as client:
            vector, = embed_queries([args.query], tokenizer, client)
        hits = search.search(args.query, vector, args.top_k, args.candidates, not args.fusion_only)
        if args.json:
            print(json.dumps(hits, ensure_ascii=False, indent=2))
            return
        for rank, hit in enumerate(hits, 1):
            keyword = hit["ranks"].get("bm25", "—")
            semantic = hit["ranks"].get("semantic", "—")
            score = hit.get("rerank_score", hit["rrf_score"])
            print(f"{rank}. {hit['chunk_id']} | score {score:.4f} | BM25 #{keyword} | semantic #{semantic}")
            print(hit["citation"])
            print(hit["text"], end="\n\n")
    except (ValueError, RuntimeError, sqlite3.Error) as exc:
        sys.exit(f"Hybrid search stopped: {exc}")
    except (OSError, KeyError, TypeError) as exc:
        sys.exit(f"Hybrid search stopped: {type(exc).__name__}")


if __name__ == "__main__":
    main()
