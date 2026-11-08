---
name: pdf
description: Merge, split and convert PDF documents, and create PDFs from Markdown. Use this to combine PDFs or chosen pages, split one into parts, turn one into a Word document, or write a new PDF. To read or search a PDF, use the read_pdf tool; no skill is needed.
---

# PDFs

Reading is the `read_pdf` tool, not this skill. Use `shell` to run the
scripts below. Do not write PDF code yourself.

## Merge, split, convert

**For these, do not read the file first and do not rebuild it with `create_document`.** The scripts copy pages exactly, images included, in one call.

Combine files, or chosen pages of them, in the order given (`5-` runs to the
last page):

```
python "$ATLAS_SKILLS/pdf/scripts/merge_pdf.py" combined.pdf "a.pdf" "b.pdf:2-5" "c.pdf:1,3"
```

Split into one file per page, or one per range:

```
python "$ATLAS_SKILLS/pdf/scripts/split_pdf.py" "<file>"
python "$ATLAS_SKILLS/pdf/scripts/split_pdf.py" "<file>" 1-3 4-10 11-
```

Make an editable Word document (`--pages 1-3` for part of it):

```
python "$ATLAS_SKILLS/pdf/scripts/pdf_to_docx.py" "<file>"
```

## Create a PDF

Do not use `shell` or `write` for this. Call the **`create_document`** tool
with the whole document as **Markdown**:

- `path`: a file name such as `summary.pdf` (it is saved in your workspace)
- `content`: Markdown -- `#` headings, paragraphs, `**bold**`, `- bullets`,
  `1. numbered`, and tables:

```
| Month | Total |
|---|---|
| Jan | 489337.15 |
```

To keep a source document's images, copy the `![...](asset:...)` lines
`read_pdf` printed into the Markdown, exactly. A PDF cannot be edited in
place: create it again with the change.
