"""Search a completed handbook index with BGE embeddings and cosine similarity."""
import argparse
import heapq
import json
import math
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from build_embeddings import (
    BLOB, DIMENSIONS, FORMAT_VERSION, INDEX_FILE, MODEL, ROOT, TOKENIZER_SHA,
    add_access_options, load_tokenizer, open_client, validate_texts,
)

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class SemanticIndex:
    def __init__(self, path):
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            stored = db.execute("SELECT config FROM manifest").fetchall()
            if len(stored) != 1:
                raise ValueError("Index has an invalid manifest.")
            self.meta = json.loads(stored[0][0])
            expected = (FORMAT_VERSION, MODEL, DIMENSIONS, TOKENIZER_SHA)
            if tuple(self.meta.get(k) for k in ("format_version", "model", "dimensions", "tokenizer_sha256")) != expected:
                raise ValueError("Index and configured embedding model are incompatible.")
            self.rows = db.execute("SELECT id, chunk, vector FROM passages").fetchall()
        if not self.rows or len(self.rows) != self.meta["chunk_count"]:
            raise ValueError("Index is incomplete. Resume the builder before searching.")

    def search_vector(self, query_vector, top_k=5):
        if len(query_vector) != DIMENSIONS or top_k < 1:
            raise ValueError("Expected a 384-dimensional query vector and positive top-k.")
        # The builder stores unit vectors; their dot product is cosine similarity.
        ranked = heapq.nsmallest(top_k, (
            (-math.fsum(x * y for x, y in zip(query_vector, BLOB.unpack(blob))), ident, doc)
            for ident, doc, blob in self.rows
        ))
        return [dict(json.loads(doc), score=round(-score, 6)) for score, _, doc in ranked]


def embed_queries(queries, tokenizer, client):
    if any(not q.strip() for q in queries):
        raise ValueError("Queries must not be empty.")
    texts = [QUERY_PREFIX + query.strip() for query in queries]
    validate_texts(texts, tokenizer)
    return client.embed(texts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--index", type=Path, default=ROOT / INDEX_FILE)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    add_access_options(parser)
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive.")
    try:
        index = SemanticIndex(args.index)
        tokenizer = load_tokenizer(args.tokenizer)
        with closing(open_client(args)) as client:
            vector, = embed_queries([args.query], tokenizer, client)
        hits = index.search_vector(vector, args.top_k)
        if args.json:
            print(json.dumps(hits, ensure_ascii=False, indent=2))
        else:
            for rank, hit in enumerate(hits, 1):
                print(f"{rank}. {hit['chunk_id']} (cosine {hit['score']:.3f})")
                print(hit["citation"])
                print(hit["text"], end="\n\n")
    except (ValueError, RuntimeError, sqlite3.Error) as exc:
        sys.exit(f"Search stopped: {exc}")
    except (OSError, KeyError, TypeError) as exc:
        sys.exit(f"Search stopped: {type(exc).__name__}")


if __name__ == "__main__":
    main()
