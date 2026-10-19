---
name: pdf
description: Read, search, merge, split and convert PDF documents. Use this whenever a PDF is attached or mentioned - to summarise it, quote a passage, find a number, answer a question about it, combine PDFs or chosen pages, split one into parts, or turn it into a Word document. Also creates PDFs from Markdown.
---

# PDFs

Use `shell` to run the script. Do not write PDF code yourself.

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

## Read pages

```
python "$ATLAS_SKILLS/pdf/scripts/read_pdf.py" "<file>" --pages 1-3
```

`--pages` takes `1-3`, `1,4,7`, or `all`. The default is the first two pages,
which is usually enough to tell what a document is.

## Images

The reader saves the document's images and prints each one as a line like
`![page 2, image 1](C:/.../page2-1.png)`. To keep an image in a new document,
put that exact line in `create_document`'s Markdown where it belongs.

## Search first when you know the word

Far cheaper than reading pages when you are hunting a term:

```
python "$ATLAS_SKILLS/pdf/scripts/read_pdf.py" "<file>" --search "coherence"
```

## Show more

Output is capped at about 1500 tokens. When the script says `[truncated ...]`,
it names the flag that shows more -- usually `--max-tokens 3000`, or a narrower
`--pages`. **Do not guess at what a truncated read left out.**

## Create or change a document

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

To change part of an existing file, call **`edit_document`** with the exact
text to `find` and its `replace`ment. Read the file first and copy the text
exactly. A PDF cannot be edited in place: create it again with the change.

## If it cannot read the file

`ERROR: pages [...] have no text layer -- this looks like a scanned or
image-only PDF`.

That means the file is images, not text. No tool here can read it. Say so
plainly and ask the user for a text version. Do not describe what you imagine
the document might contain, and do not report "the document contains no
information" -- the document contains plenty, this tool just cannot see it.