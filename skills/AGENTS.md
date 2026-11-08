# skills/ — what the agent can load

A skill is a folder with a `SKILL.md`. The model sees every enabled skill's
`name` and `description` in its prompt, calls the `skills` tool to load the
body when one applies, and then runs the skill's scripts through `shell`.

```
skills/
  _shared.py           friendly import errors, input and output paths, and the one
                       document-link resolver (`open_link`, `save_link`)
  pdf/   SKILL.md  scripts/merge_pdf.py, split_pdf.py, pdf_to_docx.py
  docx/  SKILL.md  scripts/docx_to_pdf.py   (needs Word or LibreOffice)
  xlsx/  SKILL.md  scripts/combine_xlsx.py, xlsx_to_csv.py
  <installed>/  ...  .atlas-source.json                  (where it came from)
```

Documents are *read* with Atlas's own tools (`read_pdf`, `read_docx`,
`read_xlsx`), from what was parsed at upload; no skill is loaded to read.
The bundled skills are for what reading is not: merging, splitting,
converting and writing. Loading one adds its writing tools: `create_document`
(Markdown in), `edit_docx` (a paragraph or cell by id) and `set_cell`. What a skill needs is listed on
the Skills page with an install button.

## Writing one for a 2B model

- **Ship a script; never ask the model to write library code.** "Run
  `python skills/pdf/scripts/merge_pdf.py out.pdf "a.pdf" "b.pdf"`" works.
  "Use pypdf to extract page 3" does not.
- **Keep `SKILL.md` short.** Its whole body is loaded into a 32k window. The
  Skills page warns above about 2,500 tokens.
- **The description decides whether the skill is used.** Name the file types
  and the user's likely words ("whenever a .docx is attached or mentioned").
- **Budget the output.** A script's output goes into a 32k context: keep it
  short, and say plainly when it was cut and how to see more, because a model
  that cannot tell a fragment from the whole will answer from the fragment.
- **Fail in one sentence.** `_shared.require()` turns a missing library into a
  short message. A traceback is what provokes the model to `pip install`.
- **Take links with `_shared.save_link`.** `file://` and `http(s)://` are opened
  by `open_link` for every caller, `read_pdf` and the backend's PDF import and
  viewer included: checked for the file type and 100 MB, and refused when a link
  returns a web page instead.
- **Resolve inputs with `_shared.resolve`.** A relative path is looked for in
  the workspace, then the allowed folders (`$ATLAS_FOLDERS`); a bare name
  found nowhere is looked up by name there (`find_by_name`: unique matches
  only, bounded, inputs only). Name outputs with `default_output` and report
  them with `created()`, which prints the path relative to the workspace: a
  bare `x.docx` read as "beside the input" and the model looked there.
- **Tolerate mangled quoting.** Paths may arrive with stray quotes or
  backslashes; `_shared.unquote` is there for that.
- **Declare what you need.** `requirements.txt` for Python, `package.json`
  for Node, or an `npm install -g ...` line in a SKILL.md code block. The
  Skills page shows each as installed or missing and installs the missing
  ones. If the model installs instead, the user is asked first.

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
