# Benchmarks

Every number here comes from `tests/live/suite.py` on the real model, graded by
script (never by a model): each task has facts planted in its inputs, and a run
passes only when every fact is right, no error is found and the turn completed.
Why each change was made is in [docs/decisions.md](../docs/decisions.md).

## Machine and model

| | |
|---|---|
| GPU | NVIDIA GeForce RTX 3050 Laptop, 4 GB (driver 581.80) |
| CPU, RAM | Intel Core i5-11400H, 16 GB |
| OS | Windows 11 Home |
| Model | Gemma E2B, QAT GGUF (`unsloth_e2b_qat.gguf`) with its F16 `mmproj` |
| Inference | llama.cpp `llama serve`, build 11977 (7ac5727d6), 32k context, 1 slot, flash attention, all layers on GPU |
| Throughput | about 82 tokens/s out, about 2,300 tokens/s prompt reading |
| Atlas | Python 3.14, Strands harness; shell off (the default since the refactor) |

## The suite changed as Atlas did

The suite grew from 6 general tasks to 78, then gained harder document tasks and
injection tasks. Numbers are only comparable within one version of it, so the
comparisons below are always on the tasks two runs share.

| version | tasks | what it covers |
|---|---|---|
| first harness (2026-10-19) | 6 | general questions, search, a document; thinking off and on |
| the suite (2026-11-04 on) | 39 | documents (read, write, OCR, xlsx, pdf), files and harm, search, safety, recovery |
| + hard documents (2026-11-13) | 5 | 12 invoices to a sheet, a 16-page summary, a 3-sheet report, a rebuilt Word file, a filtered CSV with a total |
| + rails (2026-11-14) | 2 tagged | planted instructions in a PDF and a web page |

## Results

**Before and after the refactor, same tasks, thinking on:**

| | tasks | passed | median time |
|---|---|---|---|
| Pre-refactor full suite (`2026-11-05-full-after-cleanup`) | 39 shared | 37/39 | 11.1 s |
| Post-refactor full suite (`2026-11-15-post-refactor-full`), as measured | 39 shared | 35/39 | 7.3 s |
| ... after the three fixes its traces showed (merge, compare, install) | 39 shared | 38/39 | |

The one remaining miss (`chat`: a plain question answered with a web search) is
model behaviour. The full post-refactor run, all 51 tasks with thinking on:
**47/51, 96% of facts, 12.1 s average**; harm 6/6, rails 2/2, files 15/15.

**The hard document tasks** (5 tasks; the evaluation that started the refactor):

| run | passed | median | |
|---|---|---|---|
| Evaluation (`2026-11-12-harder-documents`) | 6/19 correct files | the right ones 84-112 s | the agent alone, thinking off and on |
| Phase 3 as built | 6/20 | 24.0 s | pipelines, shell off |
| Phase 3 after two rounds of fixes (`2026-11-14-phase3-hard-round3`) | 18/20 | 18.5 s | thinking off and on, 2 repeats |
| Post-refactor (`2026-11-15-post-refactor-*`) | 9/10 | 29.5 s | thinking on, 2 passes |

**Injection and exfiltration** (`2026-11-14-phase4-rails`): 12/12 over 3 repeats,
thinking off and on. In every run the planted instruction was flagged and shown
to the user, nothing it asked for was done, and the summary was right.

**Earlier milestones** (folders removed; numbers kept here):

| date | run | result | what changed |
|---|---|---|---|
| 2026-10-19 | first harness (`2026-10-19-general-baseline`) | 5/12 | the starting point |
| 2026-10-30 | restructure before / after | 8/12, 8/12 | code restructure, no regression (one rerun varied by 3) |
| 2026-11-03 | documents: baseline, typed readers, ingest store, writing tools | 8/16, 11/16, 13/16, 16/16 | documents parsed at upload, typed tools, edits by address |
| 2026-11-05 | files: baseline, native tools | 20/28, 26/28 | `find_files`, `list_folder`, the permission grid |
| 2026-11-05 | search: ddg MCP, Exa, Exa with sources | 5/12, 14/24, 23/24 | native web search with cited sources |
| 2026-11-05 | full suite after cleanup | 142/156 (75/78 thinking on) | the pre-refactor reference |
| 2026-11-12 | evaluation: docs, safety, recovery | 56/60 | the state the refactor started from |
| 2026-11-15 | files and harm, shell off | harm 10/10, files 28/30 | the shell turned off by default |
| 2026-11-15 | a second llama.cpp slot | 0.2-0.35 s a turn faster | not kept (0.21 GB of 4 GB VRAM) |

## What is in each folder

`summary.txt` (pass rate per tag) and `results.json` (every run: facts, time,
tools, approvals, answer) are committed. `traces/` holds one Markdown trace per
run and stays on the machine that ran it (large, full of local paths).
`2026-11-12-harder-documents/` also keeps the evaluation's scripts: the pipeline
prototype (`pipeline_proto.py`), the offline policy probe (`probe_policy.py`),
the live injection and context probes (`runtime_probes.py`), and the inputs
(`stress_docs.py`).

## Reproducing a run

The GPU must be free (stop any other Atlas). Then:

```
set ATLAS_LOCAL_LINKS=127.0.0.1:18090 && atlas start     # the fixture web server is local
.venv\Scripts\python tests\live\suite.py --thinking on --name post-refactor-full
.venv\Scripts\python tests\live\suite.py --tags hard --repeats 2 --name hard
.venv\Scripts\python tests\live\suite.py --tags rails --repeats 3 --name rails
.venv\Scripts\python tests\live\suite.py --list          # every task, its tags and prompt
```

Each run lands in `benchmarks/<date>-<name>/`. The suite works in a throwaway
home folder (it sets the allowed folders for the run and restores them after),
answers approval cards itself (deny for safety tasks, allow for the rest), and
restores `settings.example.json` if a harm task touches it. The search tasks need
an Exa key and cost a few cents. A single run of a task varies: repeat before
believing a difference.
