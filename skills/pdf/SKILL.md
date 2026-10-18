---
name: pdf
description: Read, search and inspect PDF documents. Use this whenever a PDF is attached or mentioned - to summarise it, quote a passage, find a number, or answer a question about it.
---

# Reading PDFs

Use `shell` to run the script. Do not write PDF code yourself.

## Read pages

```
python skills/pdf/scripts/read_pdf.py "<path>" --pages 1-3
```

`--pages` takes `1-3`, `1,4,7`, or `all`. The default is the first two pages,
which is usually enough to tell what a document is.

## Search first when you know the word

Far cheaper than reading pages when you are hunting a term:

```
python skills/pdf/scripts/read_pdf.py "<path>" --search "coherence"
```

## Show more

Output is capped at about 1500 tokens. When the script says `[truncated ...]`,
it names the flag that shows more -- usually `--max-tokens 3000`, or a narrower
`--pages`. **Do not guess at what a truncated read left out.**

## If it cannot read the file

`ERROR: pages [...] have no text layer -- this looks like a scanned or
image-only PDF`.

That means the file is images, not text. No tool here can read it. Say so
plainly and ask the user for a text version. Do not describe what you imagine
the document might contain, and do not report "the document contains no
information" -- the document contains plenty, this tool just cannot see it.