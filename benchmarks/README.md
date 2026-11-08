# benchmarks/

Every measured run of Atlas against the real model, one folder each, named
`<date>-<what it measured>`. New runs land here on their own:
`tests/live/suite.py --name <what>` (see [tests/README.md](../tests/README.md)).

In each folder, `summary.txt` (or `summary.json` for the oldest) and
`results.json` are committed. `traces/` holds one Markdown trace per task run
(the model's steps, tool calls and answer): kept on this machine for digging
into a failure, not committed (large, full of local paths). Why each change
was made, and what the numbers meant, is in [docs/decisions.md](../docs/decisions.md)
under the same date.

Numbers from different harnesses are not comparable: compare within a block.

## General tasks, the first harness (12 runs: 6 tasks, thinking off and on)

| Run | Passed | |
|---|---|---|
| 2026-10-19-general-baseline | 5/12 | the first measurement |
| 2026-10-19-general-rerun | 7/12 | the same tasks, later that day |

## The restructure (12 runs, plus the demo tasks in `live.txt`)

| Run | Passed | |
|---|---|---|
| 2026-10-30-restructure-before | 8/12 | before the code restructure |
| 2026-10-30-restructure-first-fixes | 6/12 | the first fixes |
| 2026-10-30-restructure-first-fixes-rerun | 9/12 | the same code again: one run varies by 3 |
| 2026-10-30-restructure-after | 8/12 | after the restructure: no regression |

## Documents (16 runs: 8 document tasks, thinking off and on)

| Run | Passed | |
|---|---|---|
| 2026-11-03-documents-baseline | 8/16 | the harness `read` and the skill reader scripts |
| 2026-11-03-documents-typed-read-tools | 11/16 | `read_text` / `read_image` replace `read` |
| 2026-11-03-documents-ingest-store | 12/16 | the ingest store and `read_pdf` / `read_docx` / `read_xlsx` |
| 2026-11-03-documents-ingest-store-rerun | 14/16 | with the fixes those runs forced |
| 2026-11-03-documents-ingest-store-cold | 13/16 | from an empty store |
| 2026-11-03-general-check | 3/6 | merge, chat, attachment: nothing else broke |
| 2026-11-03-documents-writing-tools | 16/16 | `create_document`, `edit_docx`, `set_cell` with their skills |

## Model server

| Run | |
|---|---|
| 2026-11-04-two-slots | one slot against two (`--parallel 2 --kv-unified`): VRAM, prompt and generation speed alone and in pairs. Two slots: about 20% faster for two requests at once |

## Files: finding and safety (28 runs: 14 file tasks, thinking off and on; `suite.py --tags files`)

| Run | Passed | find | harm | |
|---|---|---|---|---|
| 2026-11-05-files-baseline | 20/28 | 5/12 | 10/10 | the filesystem MCP server; 4 of the harm passes were luck |
| 2026-11-05-files-native-tools | 22/28 | 8/12 | 10/10 | `find_files`, `list_folder`, copy and move; the MCP server off |
| 2026-11-05-files-native-tools-fixed | 26/28 | 11/12 | 10/10 | a deeper small tree, the exact retry call, documents before the grid |
| 2026-11-05-files-write-and-harm-repeats | 24/28 | | 20/20 | writing and harm, twice each; harm graded on why: none by luck |

## The whole suite (39 tasks, thinking off and on, twice: 156 runs)

| Run | Passed | |
|---|---|---|
| 2026-11-05-full-after-cleanup | 142/156 | after the cleanup; 11 of the 14 failures are thinking off. docs 53/56, files 51/56, harm 20/20, read 28/28 |
| 2026-11-05-full-workspace-paths-ddg-search | 74/90 | once each: the workspace never shown by its path, other chats refused; the 6 search tasks on the ddg-search MCP server (5/12 on them) |

## Web search (6 `search` tasks, thinking off and on, twice: 24 runs)

| Run | Passed | |
|---|---|---|
| 2026-11-05-search-exa | 14/24 | `web_search` / `read_url` through Exa: every fact right; 7 answers cited [1] without the links |
| 2026-11-05-search-exa-sources | 23/24 | the tool asks for a Sources list with full links; "a link the user gives: read_url". Thinking on 12/12 |
