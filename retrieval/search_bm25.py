"""Rank citable handbook passages with an offline BM25 keyword index."""
import argparse
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from chunk_handbook import DEFAULT_MAX_CHARS, PROFILES, ROOT, build_chunks

TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
STOP = frozenset(
    "a an and are as at be been but by can could did do does for from had has have how i if "
    "in is it its me my of on or our should so than that the their them there these they "
    "this to was we were what when where which who will with would you your".split()
)


def terms(text):
    for word in TOKEN.findall(unicodedata.normalize("NFKC", text).casefold()):
        if word and word not in STOP:
            # A conservative English plural normalization; avoids stemming names.
            if len(word) > 4 and word.endswith("ies"):
                word = word[:-3] + "y"
            elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
                word = word[:-1]
            yield word


class BM25:
    def __init__(self, chunks, k1=1.2, b=0.75):
        self.chunks = list(chunks)
        self.postings = defaultdict(list)
        lengths = []
        for position, chunk in enumerate(self.chunks):
            counts = Counter(terms(chunk["text"]))
            lengths.append(sum(counts.values()))
            for token, frequency in counts.items():
                self.postings[token].append((position, frequency))
        mean_length = sum(lengths) / len(lengths) if lengths else 1
        self.normalizer = [k1 * (1 - b + b * n / (mean_length or 1)) for n in lengths]
        self.k1 = k1

    def search(self, query, top_k=5):
        if top_k < 1:
            raise ValueError("top_k must be positive.")
        scores = defaultdict(float)
        count = len(self.chunks)
        for term in sorted(set(terms(query))):
            postings = self.postings.get(term, ())
            if not postings:
                continue
            df = len(postings)
            idf = math.log1p((count - df + 0.5) / (df + 0.5))
            for pos, tf in postings:
                scores[pos] += idf * tf * (self.k1 + 1) / (tf + self.normalizer[pos])
        ranked = sorted(scores, key=lambda pos: (-scores[pos], self.chunks[pos]["chunk_id"]))
        return [dict(self.chunks[pos], score=round(scores[pos], 6)) for pos in ranked[:top_k]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Employee question or keyword query.")
    parser.add_argument("--inventory", type=Path, default=ROOT / "data/handbook-inventory.jsonl")
    parser.add_argument("--chunks", type=Path, help="Use an existing chunk JSONL file.")
    parser.add_argument("--profile", choices=PROFILES, default="section")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Emit ranked passages as a JSON array.")
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive.")
    if args.chunks:
        with args.chunks.open(encoding="utf-8") as handle:
            index = BM25(json.loads(line) for line in handle if line.strip())
    else:
        index = BM25(build_chunks(args.inventory, ROOT, args.profile, args.max_chars))
    hits = index.search(args.query, args.top_k)
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
    elif not hits:
        print("No keyword matches.")
    else:
        for rank, hit in enumerate(hits, 1):
            print(f"{rank}. {hit['chunk_id']} (BM25 {hit['score']:.3f})")
            print(hit["citation"])
            print(hit["text"], end="\n\n")


if __name__ == "__main__":
    main()
