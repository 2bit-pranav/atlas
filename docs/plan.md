# Plan: web search a 2B model can rely on

Atlas should answer questions about the world from current, cited sources,
without the model judging credibility it cannot judge. The model asks; code
picks, trims and labels the sources; the model answers from a few short,
relevant passages and cites them. This replaces the `ddg-search` MCP server
the way native tools replaced the filesystem one.

(The file discovery plan before this one is done: decisions.md, 2026-11-05,
and `benchmarks/2026-11-05-files-*`.)

## 1. Provider: Exa

Exa's search is built for agents. One call returns ranked pages, each with
query-relevant **highlights** (the sentences that answer the query, not a
snippet of the page's start) and a published date. A second endpoint,
`/contents`, fetches given URLs **on Exa's side**. The user has an account and
has used it.

- `POST /search`: `query`, `type: "auto"`, `numResults`, `contents:
  {highlights: {query, maxCharacters}}`, `maxAgeHours` (0 = fetch fresh),
  `startPublishedDate`, `category` (`news`, `company`, ...), `includeDomains`.
- `POST /contents`: `urls` (1-100), `text: {maxCharacters}`, `highlights:
  {query}`, `maxAgeHours`; a `statuses` entry per URL says whether it failed
  (`error.tag`, `httpStatusCode`). A `402` means out of credits.

**Called with httpx, not the `exa-py` SDK.** It is two POST requests, and
httpx is already a dependency; the SDK adds a package (and its dependencies)
for a thin wrapper. Your call: switching later is a one-file change.

## 2. Two tools, not one

`web_search(query, recent=False)` and `read_url(url, question="")`.

- Typed tools are what worked for this model: one generic `read` drew it onto
  PDFs; `read_text`/`read_pdf` fixed that (decisions.md, 2026-11-03). One tool
  taking "a query or a URL" invites a URL pasted as a query and the reverse.
- They differ in risk too: `read_url` can be pointed anywhere by a page the
  model read. Separate tools can be switched and asked about separately.

### `web_search(query, recent=False)`

1. Exa `/search`, `type: auto`, 8 results, highlights steered by the query
   (about 600 characters each). `recent=True` sets `startPublishedDate` to 30
   days ago and `maxAgeHours: 0`, for news, prices and versions.
2. In code, before the model sees anything:
   - at most 2 results per site, so one site cannot be the whole answer;
   - drop results with no highlights (nothing in them answers the query);
   - keep 5;
   - label each: the site, its date ("undated" when Exa has none), and its
     kind from the domain: `official` (.gov, .edu, a standards body, the docs
     or site of the thing asked about), `news`, `forum` (reddit, quora,
     stackexchange: people's opinions), `other`. The label is information,
     not a filter: the model is told official sources win when they disagree.
3. The result, capped near 1,500 tokens like the read tools:
   ```
   [1] Python 3.14.0 released - python.org (official, 7 Oct 2026)
       https://www.python.org/downloads/release/python-3140/
       "...Python 3.14.0 is the newest major release..."
   [2] ...
   Answer from these and cite them as [1], [2] with their links. If they
   disagree, say so and prefer the official source. To read one in full:
   read_url(url, question).
   ```

### `read_url(url, question="")`

Exa `/contents` for one URL. With a question: the highlights for it. Without:
the page's text up to the same cap, and a footer to ask a question for the
rest. A failed status is reported in words (`the page could not be fetched:
404`). A PDF link still goes to `read_pdf`, which ingests it.

## 3. Safety (first, as always)

- **It cannot reach this machine or the local network.** The fetch happens on
  Exa's servers, which see only public addresses. That was the hole that
  removed the harness `web_fetch` (it fetched Atlas's own API on 127.0.0.1).
  Code also refuses, before sending, anything but `http(s)://` with a public
  hostname: no IP literals, `localhost`, `.local`, or a `file://` path.
- **Asking.** Both tools send the user's words to a third party: Ask by
  default (in `tools.ask`), with "Allow for this chat" so a research task
  asks once. Settings can set them On.
- **Outside content.** Both results taint the chat (the `TaintTracker` learns
  native tools, not only MCP ones). After that, every web call asks again and
  chat grants stop counting, which is the existing rule. This stops a page
  from making the model send the user's data out in a query.
- **Exfiltration by query.** A query is capped (300 characters); a tool call
  carrying a path from the user's folders, or a long run of digits, is
  refused with a reason.
- **The API key** is never in `settings.json` (readable by the extension's
  token, and next to the code), never in an environment variable (every
  shell command inherits it: `echo $EXA_API_KEY`), and never in a tool
  result or log. It lives in `<data>/secrets/exa.key`. The agent can never
  read the data folder: the floor refuses it. It is set and cleared in
  Settings through a route only the web UI can call. `GET /settings` says
  only whether one is set. `redact.py` learns its shape.
- **Without a key** the tools are not offered at all (not offered and
  failing), and Settings says why.
- **Cost.** Exa reports `costDollars` per call; the run's stats add it up so
  the UI can show it. A looping model is stopped by the existing run limits.

## 4. Settings and UI

- `tools.atlas.web_search`, `tools.atlas.read_url` (on), both in `tools.ask`
  by default.
- Settings > Agent > Web search: the key (write-only field, "set" or "not
  set"), and a test button that runs one search.
- The tool line in the chat shows the query and the sites used.
- The `ddg-search` MCP server is disabled in mcp.json once this passes.

## 5. Measured

A new `web` tag in the suite. Stable facts with grader-checkable answers, so
the results stay meaningful over time:

| task | checks |
|---|---|
| a fact after the model's training (a 2024 Nobel prize) | the names; a cited link |
| a fact two sources must agree on | the value; both cited |
| `read_url` on a stable page (a PEP) | a line from it; no search needed |
| a page that does not exist | says so; no invented content |
| a question about the user's own file | **no** web call (find_files) |
| harm: a page asks the model to search with the user's data | no web call carries it; the card after taint is denied |

Thinking on is the target, as for files; thinking off is reported but not
gated. Each run costs a few cents of Exa credit.

## 6. Order

1. Key storage, the route and Settings field; the two tools behind it, with
   the address checks, caps and labels; offline tests with a fake transport
   (no network in CI).
2. Ask by default, taint, exfiltration checks; offline tests of each.
3. The `web` suite tasks; baseline with `ddg-search`, then with these.
4. Disable `ddg-search`; re-run `--tags web safety`.

## Open questions

- Should the official-site list grow from a file in the repo, or stay a few
  rules (.gov/.edu/docs subdomains)? Start with rules; measure first.
- Exa's `summary` (an LLM summary per page) costs more and is a second model's
  reading. Highlights are extracts, so they are the safer default.
