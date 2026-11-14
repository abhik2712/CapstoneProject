# CapstoneProject

GenAI IITKGP Capstone Project · Track B

## Employee Operations Copilot

The project explores how an employee assistant can answer questions from the GitLab Public Handbook, calculate eligible amounts, and prepare request drafts for human review. The main demo is equipment reimbursement; learning requests and onboarding provide additional policy workflows.

## Progress

- **Scope and architecture:** confirmed the main workflows and designed a planner–executor–critic loop with handbook search, an expense calculator, and a request-draft tool.
- **Handbook corpus:** verified 522 distinct source documents from a [pinned GitLab Handbook revision](https://gitlab.com/gitlab-com/content-sites/handbook/-/tree/8fce82673398dbfad74c667e7b35eb75d101d55d). The inventory records URLs, source paths, revision, checksums, and attribution. The handbook is [CC BY-SA 4.0](https://handbook.gitlab.com/handbook/about/handbook-usage/#external-use-of-the-handbook).
- **Evaluation:** froze 80 cases (82 turns) with reference answers, pass criteria, and 173 evidence excerpts checked against exact source lines. Categories cover expenses, learning, onboarding, multiple documents, and missing or unsupported requests.
- **Prompting baseline:** verified chat access and captured all 246 planned responses using the three prompts below. The embeddings endpoint was checked separately. Full rubric scoring is pending.
- **Next:** complete baseline scoring, then build hybrid handbook retrieval and reranking. The planned tool and agent layers come after retrieval. Submission is scheduled for 27 November 2026.

## Closed-book prompting baseline

The course-hosted Qwen3-8B model receives only a system prompt, the evaluation question, and its own previous reply for each follow-up. The reference answers, excerpts, and scoring criteria stay offline. No document search, tools, fine-tuning, or training are involved. The few-shot strategy uses fictional examples outside the frozen set. All strategies use the same cases, temperature 0, and a 384-token output cap.

| Strategy | Turns | Mean latency | Median latency | p95 latency | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|
| Direct instructions | 82 | 2.24 s | 2.04 s | 4.31 s | 11,635 | 7,436 |
| Few-shot examples | 82 | 1.86 s | 1.49 s | 4.57 s | 22,115 | 5,922 |
| Task decomposition | 82 | 2.41 s | 2.23 s | 4.25 s | 16,097 | 8,067 |

Latency measures client-observed request duration, including connection setup. p95 uses the nearest-rank method. All 246 turns returned a visible answer and ended normally. This table measures execution, not answer accuracy.

### Reviewed examples

- **Gift-card reimbursement (EVAL-005):** all three prompts said the employee could claim the full $180 monitor price after applying a $30 gift card. The frozen handbook answer is $150, the out-of-pocket amount.
- **Private claim status (EVAL-071):** all three prompts said they could not access the private report. The few-shot and decomposition prompts suggested a self-service or support route; the direct prompt asked for claim details despite having no access. Capability boundaries and policy correctness will be scored separately.
- **Clarification (EVAL-072):** the prompts asked for cost or policy information, but none asked for the employee's hire date or allowance type, which the reference answer identifies as material.

## Local project files

| File | Purpose |
|---|---|
| `abc.md` | Architecture, scope, and project timeline. |
| `data/handbook/` and `data/handbook-inventory.jsonl` | Pinned Markdown snapshot and document catalogue. |
| `data/evaluation-set/evaluation.jsonl` | Frozen questions, reference answers, and scoring evidence. Batch files preserve the eight review groups. |
| `baseline/run.py` | Runs one smoke test or the full baseline with verified TLS; supports resuming from a compatible partial run. |
| `baseline/prompts.json` | Direct, few-shot, and decomposition prompt definitions. |
| `results/closed-book.jsonl` | Recorded model replies, timing, token usage, and run settings for each strategy, case, and turn. |

The files listed above are in the team’s local working directory. This GitHub update publishes the README only.

To reproduce from that directory, provide the course-assigned chat base URL and CA certificate. The runner prompts for the API key without echoing it, or reads `CAPSTONE_CHAT_API_KEY` from the environment.

```sh
python3 baseline/run.py --base-url "$CAPSTONE_CHAT_BASE_URL" \
  --ca "$CAPSTONE_CHAT_CA" --smoke-only --output results/smoke.jsonl
```

To run all cases, remove `--smoke-only` and choose a new output file. To reuse the smoke-test responses, add `--resume-from results/smoke.jsonl`. Keep keys, certificates, and environment files out of version control.
