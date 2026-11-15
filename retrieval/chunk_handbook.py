"""Build deterministic, citable passages from the pinned handbook snapshot."""
import argparse
import hashlib
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_CHARS = 1000
PROFILES = {"section": 0, "overlap": 180}
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
FRONT_MATTER = re.compile(r"\A\ufeff?---[ \t]*\r?\n.*?^---[ \t]*(?:\r?\n|\Z)", re.S | re.M)
MARKUP = re.compile(r"<!--.*?-->|{{[<%].*?[>%]}}", re.S)
LINK = re.compile(r"(!?)\[([^\]\n]*)\]\((?:[^()\n]|\([^()\n]*\))*\)")
HTML = re.compile(r"</?[A-Za-z][^>\n]*>")
URL = re.compile(r"https?://[^\s<>)]+")
NAV = re.compile(r"^\s*\[(?:toc|table of contents)\]\s*$", re.I)


class Span(NamedTuple):
    text: str
    start: int
    end: int


def clean(line):
    """Retain link labels, list markers and table rows rather than URL noise."""
    line = LINK.sub(lambda m: "" if m[1] else m[2], line)
    line = HTML.sub("", line)
    return URL.sub("", line).rstrip()


def sections(source):
    """Yield heading paths and paragraphs with original one-based line numbers."""
    fm = FRONT_MATTER.match(source)
    start = source[:fm.end()].count("\n") + 1 if fm else 1
    source = MARKUP.sub(lambda m: "\n" * m[0].count("\n"), source)
    path, paragraphs, paragraph = [], [], []
    fence, fence_size = None, 0

    for number, line in enumerate(source.splitlines(), 1):
        if number < start:
            continue
        marker = FENCE.match(line)
        if marker:
            token, rest = marker.groups()
            if fence is None:
                fence, fence_size = token[0], len(token)
                continue
            if token[0] == fence and len(token) >= fence_size and not rest.strip():
                fence = None
                continue
        title = HEADING.match(line) if fence is None else None
        if title:
            if paragraph:
                paragraphs.append(paragraph)
            if paragraphs:
                yield [name for _, name in path], paragraphs
            level, name = len(title[1]), clean(title[2]).strip()
            while path and path[-1][0] >= level:
                path.pop()
            if name:
                path.append((level, name))
            paragraphs, paragraph = [], []
        elif not line.strip() or NAV.match(line):
            if paragraph:
                paragraphs.append(paragraph)
                paragraph = []
        elif (value := clean(line)).strip():
            paragraph.append((number, value))

    if paragraph:
        paragraphs.append(paragraph)
    if paragraphs:
        yield [name for _, name in path], paragraphs


def join_spans(left, right):
    separator = "\n\n" if right.start > left.end + 1 else "\n"
    return Span(left.text + separator + right.text, left.start, right.end)


def pack_paragraph(paragraph, limit):
    """Split an oversized paragraph on lines, then on words for long lines."""
    pending = None
    for line, text in paragraph:
        for fragment in textwrap.wrap(
            text, width=limit, replace_whitespace=False, break_on_hyphens=False,
            expand_tabs=False,
        ) if len(text) > limit else [text]:
            span = Span(fragment, line, line)
            candidate = join_spans(pending, span) if pending else span
            if len(candidate.text) > limit:
                yield pending
                pending = span
            else:
                pending = candidate
    if pending:
        yield pending


def sections_to_chunks(paragraphs, body_limit, overlap):
    """Greedily pack heading-local paragraphs and optionally repeat tail lines."""
    current = None
    for paragraph in paragraphs:
        for span in pack_paragraph(paragraph, body_limit):
            if current is None:
                current = span
                continue
            combined = join_spans(current, span)
            if len(combined.text) <= body_limit:
                current = combined
                continue
            yield current
            tail = current.text.splitlines()[-1]
            # Repeat one preceding source line when it fits and ends before
            # the next paragraph or block. Never cross a heading boundary.
            if (len(tail) <= overlap and len(tail) + 2 + len(span.text) <= body_limit
                    and current.end < span.start):
                current = join_spans(Span(tail, current.end, current.end), span)
            else:
                current = span
    if current:
        yield current


def build_chunks(inventory, root=ROOT, profile="section", max_chars=DEFAULT_MAX_CHARS):
    if max_chars < 300:
        raise ValueError("max_chars must be at least 300.")
    handbook = (root / "data/handbook").resolve()
    seen = set()
    for line in inventory.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        key = doc["document_id"]
        if key in seen:
            raise ValueError(f"Duplicate inventory document ID: {key}")
        seen.add(key)
        file = (root / doc["local_path"]).resolve()
        if not file.is_relative_to(handbook):
            raise ValueError(f"Inventory path is outside the handbook: {key}")
        raw = file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != doc["sha256"]:
            raise ValueError(f"Handbook checksum mismatch: {key}")
        seq = 0
        for path, paragraphs in sections(raw.decode("utf-8")):
            prefix = " > ".join([doc["title"], *path])
            # Cap the repeated prefix but preserve the complete heading path as metadata.
            prefix = textwrap.shorten(prefix, width=min(220, max_chars // 4), placeholder="…")
            body_limit = max_chars - len(prefix) - 2
            for span in sections_to_chunks(paragraphs, body_limit, PROFILES[profile]):
                text = f"{prefix}\n\n{span.text.strip()}"
                if not any(c.isalnum() for c in span.text):
                    continue
                seq += 1
                yield {
                    "chunk_id": f"{profile}-{max_chars}:{key}:{seq:04d}",
                    "document_id": key,
                    "title": doc["title"],
                    "headings": path,
                    "line_start": span.start,
                    "line_end": span.end,
                    "source_url": doc["source_url"],
                    "source_commit": doc["source_commit"],
                    "citation": f"{doc['source_revision_url']}#L{span.start}-{span.end}",
                    "text": text,
                }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=ROOT / "data/handbook-inventory.jsonl")
    parser.add_argument("--profile", choices=PROFILES, default="section")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--output", type=Path, help="New JSONL file; omit to stream to stdout.")
    args = parser.parse_args()
    rows = list(build_chunks(args.inventory, ROOT, args.profile, args.max_chars))
    if not rows:
        parser.error("No handbook passages were built.")
    out = args.output.open("x", encoding="utf-8") if args.output else sys.stdout
    try:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False), file=out)
    finally:
        if args.output:
            out.close()
    print(f"{len(rows):,} passages from {len({r['document_id'] for r in rows}):,} documents", file=sys.stderr)


if __name__ == "__main__":
    main()
