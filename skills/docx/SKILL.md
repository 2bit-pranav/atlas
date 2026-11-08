---
name: docx
description: Convert Word documents (.docx) to PDF, write new ones from Markdown, and change paragraphs or table cells in existing ones. Use this to turn a .docx into a PDF, produce a new Word document, or edit one. To read or search a .docx, use the read_docx tool; no skill is needed.
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

To change an existing document, read it with `read_docx`, then call
**`edit_docx`** with the id it printed and the new text. A paragraph is `b12`;
a table cell is `t1.r3.c3` (table 1, row 3, column 3), read off the row
numbers `read_docx` shows:

```
edit_docx(path="report.docx", block="t1.r3.c3", text="18 days")
```

Change one paragraph or cell per call. Do not rebuild the whole document
with `create_document` to change part of it: it is saved as a new file and
everything you did not copy exactly is lost.

Legacy `.doc` is not supported: ask the user to save it as `.docx`.
