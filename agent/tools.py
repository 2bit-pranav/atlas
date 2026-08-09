import os
from typing import Annotated
from dotenv import load_dotenv
from exa_py import Exa

load_dotenv()

exa = Exa(api_key=os.environ["EXA_API_KEY"])

async def web_search(
    query: Annotated[str, "Natural language search query"],
) -> str:
    """
    Search the web using Exa and return compressed highlights and summaries.
    """
    try:
        results = exa.search(
            query,
            type="auto",
            num_results=2,
            contents={
                "highlights": {
                    "numSentences": 3,
                    "highlightsPerUrl": 2,
                },
                "summary": {
                    "query": query,
                },
            },
        )

        if not results.results:
            return "No relevant results found."

        formatted_results = []
        for i, r in enumerate(results.results, 1):
            title = getattr(r, "title", "Untitled")
            url = getattr(r, "url", "")
            summary = getattr(r, "summary", "").strip()
            highlights = getattr(r, "highlights", [])
            
            snippet = f"**[{i}] {title}**\nURL: {url}"
            if summary:
                snippet += f"\nSummary: {summary}"
            if highlights:
                hl_str = " ".join(h.strip() for h in highlights)
                snippet += f"\nHighlights: {hl_str}"

            formatted_results.append(snippet)

        return "\n\n---\n\n".join(formatted_results)

    except Exception as e:
        return f"Search error: {e}"


async def web_fetch(
    url: Annotated[str, "URL to fetch"],
) -> str:
    """
    Fetch and extract clean text content from a single webpage.
    """
    try:
        results = exa.get_contents(
            urls=[url],
            text={
                "maxCharacters": 2500,
            },
            summary={"query": "Key technical points and main concepts"},
        )

        if not results.results:
            return "Unable to fetch content from URL."

        page = results.results[0]
        title = getattr(page, "title", "Untitled")
        summary = getattr(page, "summary", "").strip()
        text = getattr(page, "text", "").strip()

        output = f"**TITLE:** {title}\n**URL:** {page.url}\n"
        if summary:
            output += f"**SUMMARY:** {summary}\n\n"
        output += f"**CONTENT:**\n{text}"

        return output

    except Exception as e:
        return f"Fetch error: {e}"


async def write_file(
    path: Annotated[str, "Path of the file to create or update"],
    content: Annotated[str, "Plain text content to write into the file"]
) -> str:
    """
    Create a new file or overwrite an existing file.
    """
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        with open(path, "w", encoding="utf-8") as file:
            file.write(content)

        return f"Successfully wrote file to '{path}'"

    except Exception as e:
        return f"Failed writing file: {e}"