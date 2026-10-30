# tests/

Two kinds, kept apart on purpose.

**Offline checks** need no model and run in seconds. CI runs them on every push
(`.github/workflows/checks.yml`), and so should you before a commit:

```
.venv\Scripts\python tests\check.py        # ruff, pyright, pytest, tsc, oxlint
.venv\Scripts\python -m pytest             # the tests only
```

| File | What it pins down |
|---|---|
| `test_policy.py` | the tool policy: access scope, approvals, installs, page taint, path normalising, the document redirect; skill requirements |
| `test_maths.py` | `calculate` and `dates`: results, the forms people write, what is refused |
| `test_chats.py` | the chat tree: send, retry, edit, version switching, crash recovery |
| `test_runs.py` | runs: one at a time, approvals and their timeout, client calls, cancel, stream replay |
| `test_server_runs.py` | the backend's run lifecycle: however a run ends, its slot is freed |
| `client/src/**/*.test.ts` | the web UI store (vitest): who answers the extension's page calls |

A test for a known, not yet fixed bug is marked `xfail(strict=True)` with the
bug's id from `docs/restructure-plan.md`. The fix removes the marker; strict
means a fix that lands without removing it fails, so it cannot go unnoticed.

**Live checks** use the real model and need the GPU to themselves (stop any
other Atlas first). Start an Atlas, then point them at it:

```
.venv\Scripts\python tests\bench.py --url http://127.0.0.1:8000             # 6 tasks x thinking off/on
.venv\Scripts\python tests\live\check_demo.py --url http://127.0.0.1:8000   # the demo tasks
```

`check_demo.py` builds its own fixtures in `.data/live/fixtures/` and, for the
run, sets the target's `access.folders` to them (the old value is restored
afterwards). Its trace goes to `.data/live/<timestamp>.log`. Run both at every
checkpoint and compare: they are what "it still works" means.
