"""Run the three closed-book prompting baselines. Python standard library only."""
import argparse
import getpass
import hashlib
import http.client
import json
import os
import ssl
import sys
from pathlib import Path
from time import perf_counter, sleep
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
FROZEN_SHA = "3f648d78ce9aec5e01faf8c3c7bf1d5a3918b799d0a9551535a35017518a79ca"
SMOKE_IDS = {"EVAL-003", "EVAL-005", "EVAL-071", "EVAL-072"}
MODEL = "Qwen/Qwen3-8B"
MAX_TOKENS = 384
TEMPERATURE = 0
TIMEOUT = 45


def load_questions(file):
    raw = file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_SHA:
        raise ValueError("The evaluation file does not match the frozen snapshot.")
    cases = []
    for line in raw.splitlines():
        row = json.loads(line)
        cases.append((row["id"], tuple(t["user"] for t in row["turns"])))
    if len(cases) != 80 or sum(len(q) for _, q in cases) != 82:
        raise ValueError("Expected 80 cases and 82 turns.")
    return cases


def request(url, tls, key, messages):
    payload = json.dumps(dict(model=MODEL, temperature=TEMPERATURE,
                              max_tokens=MAX_TOKENS, messages=messages)).encode()
    start = perf_counter()
    for attempt in range(2):
        connection = http.client.HTTPSConnection(url.hostname, url.port or 443,
                                                  timeout=TIMEOUT, context=tls)
        try:
            connection.request("POST", url.path.rstrip("/") + "/chat/completions",
                               body=payload, headers={
                                   "Authorization": "Bearer " + key,
                                   "Content-Type": "application/json",
                               })
            response = connection.getresponse()
            status = response.status
            body = response.read(1_000_001)
            elapsed = round(perf_counter() - start, 3)
        finally:
            connection.close()
        if status in (429, 502, 503, 504) and attempt == 0:
            sleep(2)
            continue
        if status != 200:
            raise RuntimeError(f"Chat endpoint returned HTTP {status}.")
        if len(body) > 1_000_000:
            raise RuntimeError("Chat response exceeded the size limit.")
        result = json.loads(body)
        choice = result["choices"][0]
        answer = (choice["message"].get("content") or "").strip()
        if "</think>" in answer:
            answer = answer.rsplit("</think>", 1)[1].strip()
        elif "<think>" in answer:
            answer = answer.split("<think>", 1)[0].strip()
        answer = answer.replace(key, "[REDACTED]")
        usage = result.get("usage") or {}
        return dict(response=answer, latency_seconds=elapsed,
                    input_tokens=usage.get("prompt_tokens"),
                    output_tokens=usage.get("completion_tokens"),
                    finish_reason=choice.get("finish_reason"), attempts=attempt + 1)


def run_case(url, tls, key, prompt, questions, existing):
    messages = [{"role": "system", "content": prompt}]
    for turn, q in enumerate(questions, 1):
        messages.append({"role": "user", "content": q})
        row = existing.get(turn)
        if row is None:
            row = request(url, tls, key, messages)
        if not row["response"]:
            raise RuntimeError("Model returned no visible answer.")
        yield row
        messages.append({"role": "assistant", "content": row["response"]})


def options():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("CAPSTONE_CHAT_BASE_URL"))
    parser.add_argument("--ca", type=Path, default=os.getenv("CAPSTONE_CHAT_CA"))
    parser.add_argument("--evaluation", type=Path,
                        default=ROOT/"data/evaluation-set/evaluation.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--resume-from", type=Path, help="Reuse validated results from an earlier run.")
    return parser.parse_args()


def main():
    args = options()
    url = urlsplit(args.base_url or "")
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path.rstrip("/") != "/v1"):
        raise ValueError("Supply the assigned HTTPS /v1 base URL.")
    if not args.ca or not args.ca.is_file():
        raise ValueError("Supply the assigned CA certificate.")
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls.load_verify_locations(cafile=str(args.ca))
    cases = load_questions(args.evaluation)
    prompts_path = Path(__file__).with_name("prompts.json")
    prompts = json.loads(prompts_path.read_text())
    if len(prompts) != 3 or len({p["name"] for p in prompts}) != 3:
        raise ValueError("Expected three uniquely named prompt strategies.")
    if args.output.exists():
        raise ValueError("Choose a new results path to avoid overwriting a run.")
    key = os.getenv("CAPSTONE_CHAT_API_KEY") or getpass.getpass("Course chat API key (hidden): ")
    if not key.strip():
        raise ValueError("The chat API key is empty.")
    key = key.strip()

    prompt_sha = hashlib.sha256(prompts_path.read_bytes()).hexdigest()
    case_turns = {case: len(questions) for case, questions in cases}
    strategy_names = {p["name"] for p in prompts}
    previous = {}
    if args.resume_from:
        for line in args.resume_from.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            strategy, case, turn = row["strategy"], row["case_id"], row["turn"]
            identifier = (strategy, case, turn)
            if (identifier in previous or strategy not in strategy_names
                    or case not in case_turns or not 1 <= turn <= case_turns[case]
                    or row["evaluation_sha256"] != FROZEN_SHA
                    or row["prompts_sha256"] != prompt_sha
                    or row["model"] != MODEL or row["max_tokens"] != MAX_TOKENS
                    or row["temperature"] != TEMPERATURE or not row["response"]):
                raise ValueError("Previous run is incompatible with these settings.")
            previous[identifier] = row
        if any((p, c, earlier) not in previous
               for p, c, t in previous for earlier in range(1, t)):
            raise ValueError("Previous run is missing an earlier turn.")
        print(f"Reusing {len(previous)} verified turns.", flush=True)
    else:
        probe = request(url, tls, key, [
            {"role": "system", "content": "Answer briefly. /no_think"},
            {"role": "user", "content": "Reply with the single word OK."},
        ])
        if not probe["response"]:
            raise RuntimeError("Authenticated request returned no visible answer.")
        print(f"Authenticated completion: OK ({probe['latency_seconds']:.3f}s)", flush=True)

    smoke = [c for c in cases if c[0] in SMOKE_IDS]
    remaining = [c for c in cases if c[0] not in SMOKE_IDS]
    count = 0
    with args.output.open("x", encoding="utf-8") as out:
        stages = [("smoke", smoke)]
        if not args.smoke_only:
            stages.append(("full", remaining))
        for phase, selected in stages:
            for p in prompts:
                for case_id, questions in selected:
                    existing = {t: previous[(p["name"], case_id, t)]
                                for t in range(1, len(questions)+1)
                                if (p["name"], case_id, t) in previous}
                    for i, row in enumerate(run_case(url, tls, key, p["system"], questions, existing), 1):
                        row.update(strategy=p["name"], case_id=case_id, turn=i,
                                   model=MODEL, max_tokens=MAX_TOKENS, temperature=TEMPERATURE,
                                   evaluation_sha256=FROZEN_SHA, prompts_sha256=prompt_sha)
                        out.write(json.dumps(row, ensure_ascii=False) + "\n")
                        out.flush()
                        count += 1
                        if phase == "smoke" or count % 12 == 0:
                            print(f"{phase}: {count} turns, most recent {p['name']} / {case_id} ({row['latency_seconds']:.3f}s)", flush=True)
            if phase == "smoke":
                print("Smoke check complete: 15 evaluated turns across the three prompts.", flush=True)
    print(f"Saved {count} turns to {args.output}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, IndexError, TypeError,
            http.client.HTTPException) as exc:
        # Do not dump request headers, response bodies, or a traceback.
        detail = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f"Baseline stopped: {detail}", file=sys.stderr)
        sys.exit(1)
