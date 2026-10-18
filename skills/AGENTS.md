# skills/ — what the agent can load

A skill is a folder with a `SKILL.md`. The model sees every enabled skill's
`name` and `description` in its prompt, calls the `skills` tool to load the
body when one applies, and then runs the skill's scripts through `shell`.

```
skills/
  _shared.py           output budget, truncation notices, friendly import errors
  pdf/   SKILL.md  scripts/read_pdf.py
  docx/  SKILL.md  scripts/read_docx.py, write_docx.py
  xlsx/  SKILL.md  scripts/read_xlsx.py, query_xlsx.py   (SQL via DuckDB)
  <installed>/  ...  .atlas-source.json                  (where it came from)
```

Rich documents only work through skills. The harness `read` tool returns a
pdf, docx or xlsx as a `document` block that llama.cpp cannot accept, and
`write`/`edit` handle text only.

## Writing one for a 2B model

- **Ship a script; never ask the model to write library code.** "Run
  `python skills/pdf/scripts/read_pdf.py "<path>" --pages 1-3`" works.
  "Use pypdf to extract page 3" does not.
- **Keep `SKILL.md` short.** Its whole body is loaded into a 32k window. The
  Skills page warns above about 2,500 tokens.
- **The description decides whether the skill is used.** Name the file types
  and the user's likely words ("whenever a .docx is attached or mentioned").
- **Budget the output.** `_shared.py` caps a script's output at about 1,500
  tokens. It also says plainly when it truncated and which flag shows more,
  because a model that cannot tell a fragment from the whole will answer from
  the fragment.
- **Fail in one sentence.** `_shared.require()` turns a missing library into a
  short message. A traceback is what provokes the model to `pip install`.
- **Tolerate mangled quoting.** Paths may arrive with stray quotes or
  backslashes; `_shared.unquote` is there for that.
- **Never install.** Declare packages in `requirements.txt`. The Skills page
  lists them and installs them into the venv only when the user clicks.

## Installing

From the Skills page:
- **skills.sh:** paste the command shown on a skill's page there, e.g.
  `npx skills add https://github.com/anthropics/skills --skill pdf`. Atlas
  reads the repository and skill name from it and fetches the folder from
  GitHub itself; nothing is executed.
- **GitHub:** a URL or `owner/repo`. If the repository has several skills,
  you pick which ones.
- **Zip:** upload a zip containing one or more `SKILL.md` folders.

Community skills are mostly written for large coding agents. Read-only ones
(look something up, read a format) tend to work; ones that expect the model to
write and debug code tend not to.

Switch a skill off instead of deleting it to keep it around; the switch is
`skills.disabled` in `settings.json`.
