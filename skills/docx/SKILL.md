---
name: docx
description: Convert Word documents (.docx) to PDF, write new ones from Markdown, and change text in existing ones. Use this to turn a .docx into a PDF, produce a new Word document, or edit one. To read or search a .docx, use the read_docx tool; no skill is needed.
---

# Word documents

Reading is the `read_docx` tool, not this skill. Use `shell` to run the
script below. Do not write `python-docx` code yourself.

## Convert to PDF

Do not read the document first: the script converts it in one call.

```
python "$ATLAS_SKILLS/docx/scripts/docx_to_pdf.py" "<file>"
```

This needs Microsoft Word or LibreOffice. If the script says neither is
installed, follow its hint: read the document with `read_docx` and create the
PDF from that Markdown with `create_document`.

## Create or change a document

Do not use `shell` or `write` for this. Call the **`create_document`** tool
with the whole document as **Markdown**:

- `path`: a file name such as `summary.docx` (it is saved in your workspace)
- `content`: Markdown -- `#` headings, paragraphs, `**bold**`, `- bullets`,
  `1. numbered`, and tables:

```
| Month | Total |
|---|---|
| Jan | 489337.15 |
```

To keep a source document's images, copy the `![...](asset:...)` lines its
reader printed, exactly.

To change part of an existing file, call **`edit_document`** with the exact
text to `find` and its `replace`ment, within one paragraph or one table cell:
for a table row `| Brightline | 9.85 | 23 days |`, `find` is the one cell,
`23 days`.

Legacy `.doc` is not supported: ask the user to save it as `.docx`.
