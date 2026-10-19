---
name: docx
description: Read, summarise and write Word documents (.docx). Use this whenever a .docx file is attached or mentioned - to summarise it, list its headings, read its tables, or produce a new Word document.
---

# Word documents

Use `shell` to run the scripts. Do not write `python-docx` code yourself.

## Read

```
python "$ATLAS_SKILLS/docx/scripts/read_docx.py" "<file>"
```

Returns the headings, the prose, and every table rendered as a pipe table, in
document order.

## The outline first, for long documents

```
python "$ATLAS_SKILLS/docx/scripts/read_docx.py" "<file>" --headings-only
```

Cheap, and it tells you which section actually answers the question.

## Images

The reader saves the document's images and prints each one as a line like
`![page 2, image 1](C:/.../page2-1.png)`. To keep an image in a new document,
put that exact line in `create_document`'s Markdown where it belongs.

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

To change part of an existing file, call **`edit_document`** with the exact
text to `find` and its `replace`ment. Read the file first and copy the text
exactly.

## Things that bite

- **A table is usually the answer.** Report and contract .docx files put their
  findings in tables. `read_docx.py` prints them; do not skip straight to prose.
- **Legacy `.doc` is not supported.** The script says so. Ask the user to save
  as `.docx` rather than trying to convert it.
- Output is capped near 1500 tokens and the script says so when it cuts.