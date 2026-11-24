# CapstoneProject

GenAI IITKGP Capstone Project · Track B

## Employee Operations Copilot

The project explores how an employee assistant can answer questions from the GitLab Public Handbook, calculate eligible amounts, and prepare request drafts for human review. The main demo is equipment reimbursement; learning requests and onboarding provide additional policy workflows.

## Run the equipment copilot

Install Git and Python 3.11 or later. The offline demo runs from a fresh clone
using the bundled GitLab handbook excerpts. Anyone can run it without a course
account or API key.

```sh
git clone https://github.com/abhik2712/CapstoneProject.git
cd CapstoneProject
```

### macOS and Linux

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
CAPSTONE_MODE=demo .venv/bin/python -m streamlit run streamlit_app.py
```

Use the Python executable inside `.venv` for both installation and launch.
This also works with Homebrew Python.

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:CAPSTONE_MODE = 'demo'
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

If your Windows installation uses `python` rather than `py`, use
`python -m venv .venv` for the first command.

### Try the demo

Open <http://localhost:8501> and keep the terminal running.

1. In **Equipment reimbursement**, click **Start $180 monitor example**.
2. Choose **Annual equipment refresh** and click **Continue**. Select **Yes**
   on the eligibility question and click **Continue** again.
3. Enter `200` for the remaining balance. Click **Calculate** to see a
   **USD 150.00** estimate, the handbook citations, and a draft for human review.
4. Open **Run traces** to see the planner, executor, and critic steps for the
   handbook search, calculator, and draft tools.
5. In **Handbook search**, ask **What should I attach if I lost a receipt?**
   The offline demo shows a **Prepared handbook answer** and the pinned
   Missing Receipt Affidavit source.

Press **Ctrl+C** in the terminal to stop the app. If port 8501 is already in
use, append `--server.port 8502` to the launch command and open
<http://localhost:8502>.

### Run with Docker

With Docker installed, run these commands from the repository root:

```sh
docker build -t capstone-copilot .
docker run --rm -p 127.0.0.1:8501:8501 -v capstone-state:/app/runtime capstone-copilot
```

Open <http://localhost:8501> and follow the same demo steps.

### Use the course model

Use `CAPSTONE_MODE` to select how the app answers handbook questions.

| Mode | Handbook search | Prerequisites |
|---|---|---|
| `demo` (default) | A prepared answer for the receipt example and matching passages for other supported searches | Bundled passages |
| `chat` | AI-generated answers with citations from the bundled passages | Course chat URL, CA certificate and chat API key |
| `live` | AI-generated answers with citations from the full hybrid index | Chat access, embeddings access and the completed index |

To use `chat`, stop the running demo first. Use the chat base URL assigned to
your course group, ending in `/v1`, and the CA certificate for that endpoint.
Save the certificate outside the repository and replace the example URL and
path below. Enter your assigned chat key at the prompt.

**macOS and Linux (Bash or Zsh)**

```bash
export CAPSTONE_CHAT_BASE_URL='https://YOUR_ASSIGNED_HOST:PORT/v1'
export CAPSTONE_CHAT_CA='/absolute/path/to/your-chat-ca.crt'
printf 'Course chat API key: '
read -rs CAPSTONE_CHAT_API_KEY
export CAPSTONE_CHAT_API_KEY
CAPSTONE_MODE=chat .venv/bin/python -m streamlit run streamlit_app.py
```

**Windows PowerShell**

```powershell
$env:CAPSTONE_CHAT_BASE_URL = 'https://YOUR_ASSIGNED_HOST:PORT/v1'
$env:CAPSTONE_CHAT_CA = 'C:\path\to\your-chat-ca.crt'
$env:CAPSTONE_CHAT_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Course chat API key' -AsSecureString)).Password
$env:CAPSTONE_MODE = 'chat'
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Ask the missing-receipt question again. **AI-generated handbook answer**
indicates a response from the course model. The app checks that citation IDs
come from the retrieved passages. The equipment workflow uses the same pinned
policy passages in every mode.

For `live` mode, [prepare the full handbook index](#reproduce-locally) or
obtain the completed SQLite index from the team. The default path is
`data/handbook-embeddings.sqlite`. Set `CAPSTONE_INDEX` for another path.
Set `CAPSTONE_EMBED_BASE_URL`, `CAPSTONE_EMBED_CA`, and
`CAPSTONE_EMBED_API_KEY`, or point `CAPSTONE_EMBED_ACCESS_ZIP` to your course
embeddings archive. Set `CAPSTONE_TOKENIZER` if using a local copy of the
pinned tokenizer. Then use `CAPSTONE_MODE=live` in the launch command for your
shell. Keep keys and access archives outside Git.

### Command line and tests

From the repository root, use the virtual environment created above:

```sh
.venv/bin/python -m copilot demo
.venv/bin/python -m unittest discover -s tests -v
```

On Windows, use `.\.venv\Scripts\python.exe` in place of `.venv/bin/python`.
The CLI demo prints the USD 150 estimate, citations, and a session ID. Pass
that ID to `python -m copilot traces SESSION_ID`, using the virtual environment
Python for your shell, to inspect the recorded steps.

The CLI and Streamlit store typed equipment facts in `runtime/copilot.sqlite`.
Use `CAPSTONE_STATE_DB` to select another path. Traces record the stage,
operation, outcome, retries, latency, and reported model token counts when
available. Set `CAPSTONE_OTEL_CONSOLE=1` to export OpenTelemetry spans to
stderr. The app limits requests per session and instance and caches the
pinned equipment lookup in memory.

The tests cover state persistence, calculation limits, draft behavior,
refusals, malformed inputs, retries, rate and step limits, citation validation,
and the Streamlit workflow. The chat integration test uses a test double.
Full agent accuracy and safety evaluation on the frozen set remains pending.

## Progress

- **Scope and architecture:** confirmed the main workflows and designed a planner–executor–critic loop with handbook search, an expense calculator, and a request-draft tool.
- **Handbook corpus:** verified 522 distinct source documents from a [pinned GitLab Handbook revision](https://gitlab.com/gitlab-com/content-sites/handbook/-/tree/8fce82673398dbfad74c667e7b35eb75d101d55d). The inventory records URLs, source paths, revision, checksums, and attribution. The handbook is [CC BY-SA 4.0](https://handbook.gitlab.com/handbook/about/handbook-usage/#external-use-of-the-handbook).
- **Evaluation:** froze 80 cases (82 turns) with reference answers, pass criteria, and 173 evidence excerpts checked against exact source lines. Categories cover expenses, learning, onboarding, multiple documents, and missing or unsupported requests.
- **Prompting baseline:** verified chat access and captured all 246 planned responses using the three prompts below. The embeddings endpoint was checked separately. All 246 responses were scored against the frozen rubric.
- **Retrieval and RAG:** indexed all 522 documents, compared four search methods on the frozen set, and scored 82 cited responses.
- **Agent workflow:** the equipment workflow uses a planner, an executor, and a critic with handbook search, an expense calculator, and a request-draft tool. A Streamlit app shows real execution traces.
- **Next:** score the agent against the frozen evaluation set, extend workflow coverage, and prepare the final report. Submission is scheduled for 27 November 2026.

## Closed-book prompting baseline

The course-hosted Qwen3-8B model receives only a system prompt, the evaluation question, and its own previous reply for each follow-up. The reference answers, excerpts, and scoring criteria stay offline. No document search, tools, fine-tuning, or training are involved. The few-shot strategy uses fictional examples outside the frozen set. All strategies use the same cases, temperature 0, and a 384-token output cap.

| Strategy | Turns | Mean latency | Median latency | p95 latency | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|
| Direct instructions | 82 | 2.24 s | 2.04 s | 4.31 s | 11,635 | 7,436 |
| Few-shot examples | 82 | 1.86 s | 1.49 s | 4.57 s | 22,115 | 5,922 |
| Task decomposition | 82 | 2.41 s | 2.23 s | 4.25 s | 16,097 | 8,067 |

Latency measures client-observed request duration, including connection setup. p95 uses the nearest-rank method. All 246 turns returned a visible answer and ended normally. This table measures execution, not answer accuracy.


### Answer quality

An assistant reviewed every response against the local case rubric. A turn passes only if it satisfies the material criteria without a contradictory claim. A case passes if every turn passes. Partial responses contain some required content; incomplete responses miss the requested policy or action; incorrect responses introduce a material error. None of these outcomes count as passes. Optional points marked “may” are not required. These are single-review results; no independent reviewer agreement has been measured.

| Strategy | Turns passed | Cases passed | Answer turns | Clarification turns | Refusal turns |
|---|---:|---:|---:|---:|---:|
| direct | 1/82 (1.2%) | 1/80 (1.2%) | 0/66 | 1/8 | 0/8 |
| few_shot | 2/82 (2.4%) | 2/80 (2.5%) | 0/66 | 0/8 | 2/8 |
| decomposition | 4/82 (4.9%) | 4/80 (5.0%) | 0/66 | 1/8 | 3/8 |

No strategy passed a full policy-answer turn. Failing the policy rubric can mean the model honestly lacked the evidence, gave only partial guidance, or gave a wrong answer. The per-turn scorecard distinguishes those outcomes. Common failures were guessed reimbursement rules, missing approval steps, and clarification questions that did not ask for the policy-relevant detail. The small differences in pass rates are driven by clarification and refusal cases and do not establish that one prompt is reliably better.

The endpoint reported token counts. No monetary cost is reported because no verified pricing was available for the course endpoint.

### Reviewed examples

- **Gift-card reimbursement (EVAL-005):** all three prompts said the employee could claim the full $180 monitor price after applying a $30 gift card. The frozen handbook answer is $150, the out-of-pocket amount.
- **Private claim status (EVAL-071):** all three prompts said they could not access the private report. The few-shot and decomposition prompts suggested a self-service or support route and passed this case. The direct prompt asked for claim details despite having no access and was graded partial.
- **Clarification (EVAL-072):** the prompts asked for cost or policy information, but none asked for the employee's hire date or allowance type, which the reference answer identifies as material.

## Retrieval and grounded answers

The retriever splits the pinned handbook into heading-based passages with permanent source citations. The selected profile produced **9,211 passages from 522 documents**. The tokenizer verified a maximum of **407 tokens per passage** against the 512-token limit. The course BGE model generates 384-dimensional embeddings. BM25 and semantic search each nominate up to 30 passages; reciprocal rank fusion combines their lists, and a local second pass reranks the candidates. The answer run used the top five reranked passages.

| Retrieval method | Document recall@5 | Evidence span recall@5 |
|---|---:|---:|
| BM25 | 81.7% | 41.8% |
| Semantic | 89.0% | 49.6% |
| Rank fusion | 88.4% | 48.8% |
| Rank fusion + local reranker | 86.2% | 48.1% |

Recall is averaged across the 82 frozen turns. Document recall checks which required documents appear; evidence span recall checks whether the chunks cover each annotated span's content-bearing lines, excluding blank lines, headings, and removed markup. Semantic search had the highest measured evidence recall at five; the reranker did not improve that metric. At ten passages, rank fusion led on evidence span recall (64.4%), before accounting for the extra context it would add to an answer request.

| Answer setup | Turns passed | Cases passed | Answer turns | Clarification turns | Refusal turns |
|---|---:|---:|---:|---:|---:|
| Best closed-book prompt | 4/82 | 4/80 | 0/66 | 1/8 | 3/8 |
| RAG with citations | 20/82 | 19/80 | 20/66 | 0/8 | 0/8 |

Both runs used the same chat model and frozen evaluation set. RAG used an evidence-aware prompt and supplied retrieved passages. Reference answers and scoring criteria stayed offline. The average RAG chat request took **3.05 s**, excluding retrieval; the endpoint reported **128,123 input tokens and 9,936 output tokens** over the run. These are single-review scores. A resolvable citation indicates which passage was referenced; it does not prove the passage supports the answer.

- **Worked:** the cited [gift-card reimbursement rule](https://gitlab.com/gitlab-com/content-sites/handbook/-/blob/8fce82673398dbfad74c667e7b35eb75d101d55d/content/handbook/finance/expenses.md#L64-68) changed the answer from $180 to $150 after a $30 gift card.
- **Retrieval miss:** the new-hire equipment question surfaced the existing-employee allowance without the rule for new hires.
- **Interpretation error:** the model retrieved the tuition repayment rule but treated the $1,000 threshold as a deductible.

### Development trial

We tried two changes on eight separate development cases. Adding up to three neighbouring passages left coverage at **10/11 annotated evidence points** and raised input token use by **52%**. An answer/clarify/decline gate chose the expected action in **3/8 cases**: it declined both requests to act in private systems, but blocked three valid policy questions and missed both clarification cases. Neither change is enabled in the evaluated RAG workflow.

## Project files

| File | Purpose |
|---|---|
| [baseline/run.py](baseline/run.py) and [prompts.json](baseline/prompts.json) | Run the three closed-book prompts and record replies, timing, and token use. |
| [Closed-book replies](results/closed-book.jsonl) and [scorecard](results/baseline-scores.jsonl) | Inspect baseline model output and turn-level verdicts. |
| [chunk_handbook.py](retrieval/chunk_handbook.py) and [build_embeddings.py](retrieval/build_embeddings.py) | Prepare citable passages and build or resume the SQLite vector index. |
| [search_bm25.py](retrieval/search_bm25.py), [search_semantic.py](retrieval/search_semantic.py), and [search_hybrid.py](retrieval/search_hybrid.py) | Compare keyword, vector, and combined retrieval. |
| [evaluate_rag.py](retrieval/evaluate_rag.py) | Measure retrieval separately from cited answers on the frozen set. |
| [trial_rag_improvements.py](retrieval/trial_rag_improvements.py) | Reproduce the separate eight-case development trial. |

The pinned handbook, its inventory, the SQLite index, the frozen question and answer set, and the per-case RAG and development results stay in the team’s working directory. A fresh clone requires the team’s local inputs to reproduce the runs.

## Reproduce locally

Use Python 3.11 or later. From the repository root, place the pinned Markdown in `data/handbook/`, the matching inventory at `data/handbook-inventory.jsonl`, and the frozen cases at `data/evaluation-set/evaluation.jsonl`.

Install the dependencies using the setup above. The embedding scripts download
the pinned public BGE tokenizer or accept a matching local copy via
`--tokenizer`. Set `CAPSTONE_EMBED_BASE_URL`, `CAPSTONE_EMBED_CA`,
`CAPSTONE_CHAT_BASE_URL`, and `CAPSTONE_CHAT_CA` using your assigned course
settings. The scripts prompt for keys without echoing them or read
`CAPSTONE_EMBED_API_KEY` and `CAPSTONE_CHAT_API_KEY` from the environment.

The examples use the macOS/Linux virtual environment path. In PowerShell,
replace `.venv/bin/python` with `.\.venv\Scripts\python.exe`.

```sh
# Closed-book smoke check
.venv/bin/python -B baseline/run.py --smoke-only --output results/smoke.jsonl

# Build or resume the embedding index, then search
.venv/bin/python -B retrieval/build_embeddings.py
.venv/bin/python -B retrieval/search_hybrid.py "How should I handle a lost expense receipt?"

# Evaluate retrieval and generate cited answers
.venv/bin/python -B retrieval/evaluate_rag.py retrieve
.venv/bin/python -B retrieval/evaluate_rag.py report
.venv/bin/python -B retrieval/evaluate_rag.py answer
```

Use a new results filename for a fresh retrieval run; the answer stage resumes only when the prior results match its inputs. To run the full closed-book baseline, omit `--smoke-only` and choose a new output path. Keep course credentials, certificates, and access archives outside the repository.
