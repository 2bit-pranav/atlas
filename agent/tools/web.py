"""`web_search` and `read_url`: the web through Exa, shaped for a 2B model.

The model cannot judge which source to trust, so code does what it can: at
most two results per site, only results whose highlights answer the query
(Exa's query-relevant sentences, not a page's first lines), each labelled
with its site, date and kind (official, reference, news, forum, other). The
model gets a few short cited passages and is told to prefer official sources.

`read_url` is fetched by Exa's servers, never from this machine, so it cannot
reach Atlas's own API or the local network (why the harness `web_fetch` was
removed). Addresses that are not public are refused before anything is sent,
and so are queries that look like they carry the user's data out: a file
path, the workspace, a long number, or a wall of text.

The key is read from `<data>/secrets/exa.key` at each call: never an
environment variable (every shell command would inherit it), never shown.
docs/plan.md has the design; decisions.md what it measured.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from strands import tool

API = "https://api.exa.ai"
TOOLS = ("web_search", "read_url")
MAX_QUERY = 300
MAX_CHARS = 6000          # the read tools' budget, about 1,500 tokens
PER_SITE, KEEP, ASK_FOR = 2, 5, 8
HIGHLIGHT_CHARS = 600

_OFFICIAL = re.compile(r"(\.gov|\.edu|\.int|\.mil)(\.[a-z]{2})?$|\.(ac|gov)\.[a-z]{2}$|^(docs|developer|developers)\.")
_REFERENCE = {"wikipedia.org", "britannica.com", "who.int", "europa.eu", "nature.com", "arxiv.org"}
_NEWS = {"reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nytimes.com", "theguardian.com", "bloomberg.com",
         "ft.com", "wsj.com", "cnn.com", "aljazeera.com", "npr.org", "economist.com", "thehindu.com"}
_FORUM = {"reddit.com", "quora.com", "stackexchange.com", "stackoverflow.com", "medium.com", "x.com",
          "twitter.com", "facebook.com", "tiktok.com", "youtube.com"}
_LONG_NUMBER = re.compile(r"\d(?:[\s-]?\d){11,}")
_PATHLIKE = re.compile(r"(?:^|\s)(?:[A-Za-z]:[/\\]|/[a-z]/|~/|\$ATLAS_|%ATLAS_)")


def key_file(data_dir: Path) -> Path:
    return Path(data_dir) / "secrets" / "exa.key"


def read_key(data_dir: Path) -> str:
    try:
        return key_file(data_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_key(data_dir: Path, key: str) -> None:
    """Save the key, or remove it when `key` is empty."""
    path = key_file(data_dir)
    if not key.strip():
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.strip(), encoding="utf-8")


def _failed(message: str) -> dict[str, Any]:
    return {"status": "error", "content": [{"text": f"Error: {message}"}]}


def _site(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def kind_of(url: str) -> str:
    site = _site(url)
    root = ".".join(site.split(".")[-2:])
    if _OFFICIAL.search(site):
        return "official"
    if site in _REFERENCE or root in _REFERENCE:
        return "reference"
    if root in _NEWS or site in _NEWS:
        return "news"
    if root in _FORUM:
        return "forum"
    return "other"


def query_refusal(query: str) -> str | None:
    """Why a query must not be sent: it may be carrying the user's data out."""
    if len(query) > MAX_QUERY:
        return f"the query is {len(query)} characters; keep it under {MAX_QUERY}: a few words that describe what to find."
    if _PATHLIKE.search(query):
        return "the query holds a file path; never send the user's files or paths to a search engine."
    if _LONG_NUMBER.search(query):
        return "the query holds a long number (an account, card or id number?); never send it to a search engine."
    return None


def url_refusal(url: str) -> str | None:
    """Only public web addresses. Exa fetches them, but nothing local is even named."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        return f"{url} is not a web address (http:// or https://)."
    try:
        ipaddress.ip_address(host.strip("[]"))
        return "addresses by IP number are not read; use the site's name."
    except ValueError:
        pass
    if "." not in host or host == "localhost" or host.endswith((".local", ".localhost", ".internal", ".lan", ".home")):
        return f"{host} is not a public website."
    return None


def _flat(text: str) -> str:
    """A highlight on one line: Exa returns page fragments with markdown line breaks."""
    return " ".join(text.replace("...", " ... ").split())


def _date(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return "undated"


def shape_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At most PER_SITE per site, only results with highlights, KEEP of them, in Exa's order."""
    out: list[dict[str, Any]] = []
    per_site: dict[str, int] = {}
    for r in results:
        site = _site(str(r.get("url", "")))
        highlights = [_flat(h) for h in r.get("highlights") or [] if h and h.strip()]
        if not site or not highlights or per_site.get(site, 0) >= PER_SITE:
            continue
        per_site[site] = per_site.get(site, 0) + 1
        out.append({**r, "highlights": highlights, "site": site})
        if len(out) == KEEP:
            break
    return out


def web_tools(data_dir: Path, client: httpx.Client | None = None) -> list[Any]:
    """The two tools; `client` is for tests (a mock transport)."""
    http = client or httpx.Client(base_url=API, timeout=30.0)

    def post(path: str, body: dict[str, Any]) -> dict[str, Any] | str:
        """Exa's JSON, or a sentence saying what went wrong (never the key)."""
        key = read_key(data_dir)
        if not key:
            return "web search is not set up: the user can add an Exa key in Settings > Agent."
        try:
            r = http.post(path, json=body, headers={"x-api-key": key})
        except httpx.HTTPError as exc:
            return f"the web service could not be reached ({type(exc).__name__}). Try once more, then tell the user."
        if r.status_code in (401, 403):
            return "the Exa key was refused; the user can check it in Settings > Agent."
        if r.status_code == 402:
            return "the Exa account is out of credit; tell the user."
        if r.status_code == 429:
            return "too many web requests right now; wait and try once more."
        if r.status_code >= 400:
            return f"the web service answered {r.status_code}."
        return r.json()

    @tool(name="web_search")
    def web_search(query: str, recent: bool = False) -> Any:
        """Search the web. Returns a few relevant passages, each with its source and link.

        Use it for facts about the world, news, prices, versions, people and places.
        Never for the user's own files (use find_files), and never send their files'
        contents, paths or numbers in a query. Cite what you use as [1], [2] with its link.

        Args:
            query: A few words or a short question, e.g. "2024 Nobel Prize in Physics winners".
            recent: True for things that change (news, prices, latest versions): last 30 days only.
        """
        query = query.strip()
        if not query:
            return _failed("give web_search a query: a few words that describe what to find.")
        if why := query_refusal(query):
            return _failed(why)
        body: dict[str, Any] = {"query": query, "type": "auto", "numResults": ASK_FOR,
                                "contents": {"highlights": {"query": query, "maxCharacters": HIGHLIGHT_CHARS}}}
        if recent:
            body["startPublishedDate"] = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
            body["contents"]["maxAgeHours"] = 0
        got = post("/search", body)
        if isinstance(got, str):
            return _failed(got)
        results = shape_results(got.get("results") or [])
        if not results:
            return (f"Nothing relevant found for {query!r}{' in the last 30 days' if recent else ''}. Try other "
                    "words once; if still nothing, tell the user you could not find it. Do not guess.")
        lines, size = [], 0
        for i, r in enumerate(results, 1):
            block = (f"[{i}] {str(r.get('title') or r['site']).strip()} - {r['site']} "
                     f"({kind_of(str(r['url']))}, {_date(r.get('publishedDate'))})\n    {r['url']}\n"
                     + "\n".join(f'    "{h}"' for h in r["highlights"]))
            if lines and size + len(block) > MAX_CHARS:
                break
            lines.append(block)
            size += len(block)
        # "Cite as [1] with their links" got [1] and no links (2026-11-05): ask for the list itself.
        return ("\n".join(lines) + "\n\nAnswer from these passages. Mark each claim with its number, [1], and "
                "end your answer with a Sources list: each number with its full link. If they disagree, say "
                "so and prefer official sources. To read one page further: read_url(url, question).")

    @tool(name="read_url")
    def read_url(url: str, question: str = "") -> Any:
        """Read a web page by its address. With a question, only the parts that answer it.

        Use it for a link the user gave or a result of web_search. A PDF link: use read_pdf.

        Args:
            url: The page's full address, starting with https://.
            question: Optional: what you need from the page, e.g. "the release date".
        """
        url = url.strip()
        if why := url_refusal(url):
            return _failed(why)
        if urlparse(url).path.lower().endswith(".pdf"):
            return _failed(f'that is a PDF: read it with read_pdf(path="{url}").')
        if question and (why := query_refusal(question)):
            return _failed(why)
        body: dict[str, Any] = {"urls": [url]}
        if question.strip():
            body["highlights"] = {"query": question.strip(), "maxCharacters": MAX_CHARS // 2}
        else:
            body["text"] = {"maxCharacters": MAX_CHARS}
        got = post("/contents", body)
        if isinstance(got, str):
            return _failed(got)
        status = next(iter(got.get("statuses") or []), {})
        results = got.get("results") or []
        if status.get("status") == "error" or not results:
            code = (status.get("error") or {}).get("httpStatusCode") or ""
            return _failed(f"the page could not be read{f' ({code})' if code else ''}. Tell the user; do not "
                           "describe what it might say.")
        r = results[0]
        head = f"{str(r.get('title') or _site(url)).strip()} - {_site(url)} ({kind_of(url)}, {_date(r.get('publishedDate'))})"
        if question.strip():
            passages = [_flat(h) for h in r.get("highlights") or [] if h.strip()]
            if not passages:
                return f"{head}\nNothing on this page answers {question!r}."
            return head + "\n" + "\n".join(f'"{p}"' for p in passages) + f"\nSource: {url}"
        text = str(r.get("text") or "").strip()
        if not text:
            return _failed("the page has no readable text.")
        more = ("\n\n[The page may go on. For a part of it: read_url(url, question=\"what you need\").]"
                if len(text) >= MAX_CHARS - 50 else "")
        return f"{head}\n{url}\n\n{text}{more}"

    return [web_search, read_url]


__all__ = ["TOOLS", "kind_of", "query_refusal", "read_key", "url_refusal", "web_tools", "write_key"]
