"""Drive a running backend end to end with the real model.

    python tests/live_api.py [base_url]

Needs `atlas start` (or llama-server plus the backend) already running. Checks
the properties the chat tree promises rather than the wording of answers:

- reasoning deltas are not duplicated, and text arrives as many deltas;
- a retry is a sibling and is only allowed on the last turn;
- an edit deletes the edited turn's versions and everything after it;
- `<` / `>` switches versions without recomputing anything;
- a reopened chat carries its transcript, reasoning included.
"""

from __future__ import annotations

import json
import sys
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000") + "/api"
client = httpx.Client(base_url=BASE, timeout=300)


def run_to_end(run_id: str) -> list[dict]:
    events: list[dict] = []
    with client.stream("GET", f"/runs/{run_id}/events", params={"after": 0}) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                events.append(ev)
                if ev["type"] in ("done", "error"):
                    break
    return events


def check(cond: bool, label: str) -> None:
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    chat = client.post("/chats", json={}).json()
    cid = chat["id"]

    started = time.time()
    out = client.post(f"/chats/{cid}/messages",
                      json={"text": "In two sentences: why is the sky blue?", "thinking": True}).json()
    events = run_to_end(out["run"]["id"])
    kinds = [e["type"] for e in events]
    check(kinds[-1] == "done", f"first send completes ({time.time() - started:.1f}s)")
    thinking = "".join(e["text"] for e in events if e["type"] == "thinking_delta")
    words = thinking.split()
    doubled = sum(1 for a, b in zip(words, words[1:]) if a == b)
    check(not words or doubled < max(2, len(words) // 20), f"reasoning not doubled ({doubled} repeats in {len(words)} words)")
    check(kinds.count("text_delta") > 3, f"text streams in pieces ({kinds.count('text_delta')} deltas)")
    stats = [e for e in events if e["type"] == "stats"]
    check(bool(stats) and stats[-1].get("context_used", 0) > 0, f"context stats reported: {stats[-1] if stats else None}")

    view = client.get(f"/chats/{cid}").json()
    t1 = view["turns"][0]
    check(any(p["kind"] == "reasoning" for p in t1["render"]), "reasoning survives a reload")
    check(any(p["kind"] == "text" for p in t1["render"]), "answer stored in transcript")

    out = client.post(f"/turns/{t1['id']}/retry", json={"thinking": False}).json()
    run_to_end(out["run"]["id"])
    view = client.get(f"/chats/{cid}").json()
    check(len(view["turns"]) == 1 and len(view["turns"][0]["versions"]) == 2, "retry adds a sibling")
    a1 = "".join(p["text"] for p in t1["render"] if p["kind"] == "text")
    a2 = "".join(p["text"] for p in view["turns"][0]["render"] if p["kind"] == "text")
    print("  v1:", a1[:160].replace("\n", " "))
    print("  v2:", a2[:160].replace("\n", " "))

    t1b = view["turns"][0]["id"]
    out = client.post(f"/chats/{cid}/messages", json={"text": "Now say it in one sentence."}).json()
    run_to_end(out["run"]["id"])
    view = client.get(f"/chats/{cid}").json()
    check(len(view["turns"]) == 2, "follow-up appended")

    r = client.post(f"/turns/{t1b}/retry", json={})
    check(r.status_code == 409, "retry refused on a non-last turn")

    v = client.post(f"/turns/{t1b}/select", json={"delta": -1}).json()
    check(len(v["turns"]) == 1 and v["turns"][0]["id"] == t1["id"], "< shows version 1, whose branch ends there")
    v = client.post(f"/turns/{t1['id']}/select", json={"delta": 1}).json()
    check(len(v["turns"]) == 2, "> returns to version 2 with its follow-up kept")

    out = client.post(f"/turns/{t1b}/edit", json={"text": "What colour is grass? One sentence."}).json()
    run_to_end(out["run"]["id"])
    view = client.get(f"/chats/{cid}").json()
    check(len(view["turns"]) == 1 and len(view["turns"][0]["versions"]) == 1,
          "edit deletes the turn's versions and everything after")
    print("  edited:", "".join(p["text"] for p in view["turns"][0]["render"] if p["kind"] == "text")[:160])

    client.delete(f"/chats/{cid}")
    check(client.get(f"/chats/{cid}").status_code == 404, "chat deleted")


if __name__ == "__main__":
    main()
