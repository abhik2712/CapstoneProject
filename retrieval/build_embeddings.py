"""Build a resumable SQLite embedding index for the pinned handbook corpus."""
import argparse
import getpass
import hashlib
import http.client
import json
import math
import os
import re
import sqlite3
import ssl
import struct
import sys
import time
import urllib.request
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile

from chunk_handbook import DEFAULT_MAX_CHARS, PROFILES, ROOT, build_chunks

MODEL = "bge-small-en-v1.5"
DIMENSIONS = 384
MAX_TOKENS = 512
MAX_BATCH = 16
TOKENIZER_REV = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
TOKENIZER_SHA = "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
TOKENIZER_URL = f"https://huggingface.co/BAAI/{MODEL}/resolve/{TOKENIZER_REV}/tokenizer.json"
INDEX_FILE = Path("data/handbook-embeddings.sqlite")
FORMAT_VERSION = 1
BLOB = struct.Struct(f"<{DIMENSIONS}f")


def add_access_options(parser):
    parser.add_argument("--access-zip", type=Path, help="Course embeddings access archive.")
    parser.add_argument("--base-url", default=os.getenv("CAPSTONE_EMBED_BASE_URL"))
    parser.add_argument("--ca", type=Path, default=os.getenv("CAPSTONE_EMBED_CA"))
    parser.add_argument("--tokenizer", type=Path, help="Optional local copy of the pinned tokenizer.")


def load_tokenizer(path):
    try:
        from tokenizers import Tokenizer
    except ImportError:
        raise RuntimeError("Install tokenizers==0.22.2 in your Python environment.") from None
    if path:
        raw = path.read_bytes()
    else:
        with urllib.request.urlopen(TOKENIZER_URL, timeout=20) as response:
            raw = response.read(2_000_000)
    if hashlib.sha256(raw).hexdigest() != TOKENIZER_SHA:
        raise ValueError("Tokenizer does not match the pinned BGE tokenizer.")
    tokenizer = Tokenizer.from_str(raw.decode("utf-8"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def validate_texts(texts, tokenizer):
    counts = [len(encoding.ids) for encoding in tokenizer.encode_batch(texts, add_special_tokens=True)]
    oversized = [i for i, count in enumerate(counts) if count > MAX_TOKENS]
    if oversized:
        raise ValueError(
            f"{len(oversized)} inputs exceed {MAX_TOKENS} tokens; first index {oversized[0]}, "
            f"longest {max(counts)}. Reduce the chunk size or shorten the query."
        )
    return counts


def unit_vector(values):
    if (not isinstance(values, list) or len(values) != DIMENSIONS
            or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in values)):
        raise ValueError("Embedding service returned an invalid vector.")
    norm = math.hypot(*values)
    if not norm or not math.isfinite(norm):
        raise ValueError("Embedding service returned an invalid vector norm.")
    return tuple(x / norm for x in values)


class EmbeddingClient:
    def __init__(self, base_url, ca, key):
        url = urlsplit(base_url or "")
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path.rstrip("/") != "/v1"):
            raise ValueError("Supply the course-assigned HTTPS /v1 base URL.")
        if not key.strip():
            raise ValueError("The embeddings key is empty.")
        self.key = key.strip()
        self.route = url.path.rstrip("/") + "/embeddings"
        self.connection = http.client.HTTPSConnection(
            url.hostname, url.port or 443, timeout=40, context=ca
        )

    def close(self):
        self.connection.close()

    def embed(self, texts):
        if not 1 <= len(texts) <= MAX_BATCH:
            raise ValueError(f"An embedding batch must contain 1–{MAX_BATCH} texts.")
        body = json.dumps({"model": MODEL, "input": texts}, ensure_ascii=False).encode()
        for attempt in range(4):
            try:
                self.connection.request(
                    "POST", self.route, body=body,
                    headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"},
                )
                response = self.connection.getresponse()
                status = response.status
                raw = response.read(1_000_001)
            except (OSError, http.client.HTTPException):
                self.close()
                if attempt == 3:
                    raise RuntimeError("Embeddings connection failed after four attempts.") from None
            else:
                if status == 200:
                    if len(raw) > 1_000_000:
                        raise ValueError("Embeddings response exceeded the size limit.")
                    rows = sorted(json.loads(raw)["data"], key=lambda row: row["index"])
                    if [row["index"] for row in rows] != list(range(len(texts))):
                        raise ValueError("Embeddings response has missing or repeated indexes.")
                    return [unit_vector(row["embedding"]) for row in rows]
                if status not in (408, 429, 500, 502, 503, 504) or attempt == 3:
                    raise RuntimeError(f"Embeddings endpoint returned HTTP {status}.")
                if len(raw) > 1_000_000:
                    self.close()
            time.sleep(2 ** attempt)
        raise AssertionError("Unreachable")


def open_client(args):
    ca = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if args.access_zip:
        # Read credentials in memory. Do not extract the ZIP or mix settings
        # from the environment and a different access archive.
        with ZipFile(args.access_zip) as access:
            key = access.read("shared-embedding-key.txt").decode().strip()
            ca.load_verify_locations(cadata=access.read("vm02-ca.crt").decode())
            doc = access.read("Embedding_API_Quickstart.md").decode()
        match = re.search(r"\*\*Base URL\*\*\s+\x60(https://[^\x60]+)\x60", doc)
        if not match:
            raise ValueError("The course archive does not specify an embeddings base URL.")
        return EmbeddingClient(match[1], ca, key)
    if not args.ca or not args.base_url:
        raise ValueError("Provide --access-zip or the assigned CA and base URL.")
    ca.load_verify_locations(cafile=str(args.ca))
    key = os.getenv("CAPSTONE_EMBED_API_KEY") or getpass.getpass("Embeddings API key (hidden): ")
    return EmbeddingClient(args.base_url, ca, key)


def chunk_manifest(chunks, profile, max_chars):
    hash_ = hashlib.sha256()
    for chunk in chunks:
        serialized = json.dumps(chunk, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        hash_.update(serialized.encode("utf-8") + b"\n")
    return {
        "format_version": FORMAT_VERSION, "model": MODEL, "dimensions": DIMENSIONS,
        "tokenizer_sha256": TOKENIZER_SHA, "profile": profile, "max_chars": max_chars,
        "chunk_count": len(chunks), "chunk_sha256": hash_.hexdigest(),
    }


def existing_rows(db, manifest):
    columns = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    if not columns:
        with db:
            db.execute("CREATE TABLE manifest (config TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE passages (id TEXT PRIMARY KEY, chunk TEXT NOT NULL, "
                "tokens INTEGER NOT NULL CHECK(tokens BETWEEN 1 AND 512), "
                "vector BLOB NOT NULL CHECK(length(vector) = 1536))"
            )
            db.execute("INSERT INTO manifest VALUES (?)", (json.dumps(manifest, sort_keys=True),))
    stored = db.execute("SELECT config FROM manifest").fetchall()
    if len(stored) != 1 or json.loads(stored[0][0]) != manifest:
        raise ValueError("Existing index does not match the model, tokenizer, or current chunks.")
    return {row[0] for row in db.execute("SELECT id FROM passages")}


def build(args):
    root = args.root.resolve()
    index = args.index or root / INDEX_FILE
    inventory = args.inventory or root / "data/handbook-inventory.jsonl"
    chunks = list(build_chunks(inventory, root, args.profile, args.max_chars))
    if not chunks:
        raise ValueError("No handbook passages found.")
    tokenizer = load_tokenizer(args.tokenizer)
    token_counts = validate_texts([chunk["text"] for chunk in chunks], tokenizer)
    print(f"Token check: {len(chunks):,} passages; longest {max(token_counts)} of {MAX_TOKENS} tokens.",
          flush=True)
    if args.check_only:
        return

    manifest = chunk_manifest(chunks, args.profile, args.max_chars)
    with closing(sqlite3.connect(index)) as db:
        done = existing_rows(db, manifest)
        missing = [(chunk, count) for chunk, count in zip(chunks, token_counts)
                   if chunk["chunk_id"] not in done]
        if len(done) + len(missing) != len(chunks):
            raise ValueError("Index contains unexpected chunk IDs.")
        print(f"Starting from {len(done):,}/{len(chunks):,} indexed passages.", flush=True)
        if not missing:
            return
        if args.max_batches:
            missing = missing[:args.max_batches * args.batch_size]
        with closing(open_client(args)) as client:
            for offset in range(0, len(missing), args.batch_size):
                batch = missing[offset:offset + args.batch_size]
                vectors = client.embed([chunk["text"] for chunk, _ in batch])
                with db:
                    db.executemany("INSERT INTO passages VALUES (?, ?, ?, ?)", [
                        (chunk["chunk_id"], json.dumps(chunk, ensure_ascii=False), count, BLOB.pack(*vec))
                        for (chunk, count), vec in zip(batch, vectors)
                    ])
                finished = len(done) + offset + len(batch)
                if offset == 0 or offset // args.batch_size % 20 == 19 or offset + len(batch) == len(missing):
                    print(f"Indexed {finished:,}/{len(chunks):,} passages.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Project directory.")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--profile", choices=PROFILES, default="section")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--batch-size", type=int, choices=range(1, MAX_BATCH+1), default=MAX_BATCH)
    parser.add_argument("--max-batches", type=int, help="Stop after this many new batches.")
    parser.add_argument("--check-only", action="store_true", help="Validate tokens without API calls.")
    add_access_options(parser)
    args = parser.parse_args()
    if args.max_batches is not None and args.max_batches < 1:
        parser.error("--max-batches must be positive.")
    try:
        build(args)
    except (ValueError, RuntimeError, sqlite3.Error) as exc:
        sys.exit(f"Indexing stopped: {exc}")
    except (OSError, KeyError, TypeError) as exc:
        sys.exit(f"Indexing stopped: {type(exc).__name__}")


if __name__ == "__main__":
    main()
