import os
from pathlib import Path

def read_file(file_name: str) -> str:
    """
    Read a UTF-8 text file and return its total line count, character size, and contents.
    """
    path = Path(file_name)

    if not path.exists():
        return f"ERROR: File '{file_name}' does not exist."

    if not path.is_file():
        return f"ERROR: '{file_name}' is not a file."

    try:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        line_count = len(lines)
        char_count = len(content)

        return (
            f"SUCCESS: Read file '{file_name}' (Total lines: {line_count}, Size: {char_count} characters).\n"
            f"--- BEGIN FILE CONTENT ---\n"
            f"{content}\n"
            f"--- END FILE CONTENT ---"
        )
    except UnicodeDecodeError:
        return f"ERROR: File '{file_name}' is not a valid UTF-8 text file."
    except OSError as e:
        return f"ERROR: Could not read '{file_name}': {e}"


def write_file(file_name: str, content: str, overwrite: bool = False) -> str:
    """
    Create or update a UTF-8 text file.

    Parameters:
    - file_name: Path of the target file.
    - content: The text content to write or append.
    - overwrite: If True, replaces existing file content. If False (default), appends to existing content.
    """
    try:
        path = Path(file_name)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)

        existed_before = path.exists()

        if overwrite or not existed_before:
            path.write_text(content, encoding="utf-8")
            operation = "overwritten" if existed_before else "created"
        else:
            existing_text = path.read_text(encoding="utf-8") if path.stat().st_size > 0 else ""
            prefix = ""
            if existing_text and not existing_text.endswith("\n") and not content.startswith("\n"):
                prefix = "\n"

            with path.open("a", encoding="utf-8") as file:
                file.write(prefix + content)
            operation = "updated/appended"

        updated_content = path.read_text(encoding="utf-8")
        line_count = len(updated_content.splitlines())
        byte_size = path.stat().st_size

        return (
            f"SUCCESS: File '{file_name}' was {operation} successfully. "
            f"File now contains {line_count} lines ({byte_size} bytes)."
        )

    except OSError as e:
        return f"ERROR: Could not write '{file_name}': {e}"


def verify_operation(file_name: str) -> str:
    """
    Verify that a UTF-8 text file exists and is readable, returning its current line count and size.
    """
    path = Path(file_name)

    if not path.exists():
        return f"VERIFY_FAILED: File '{file_name}' does not exist."

    if not path.is_file():
        return f"VERIFY_FAILED: '{file_name}' is not a file."

    try:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()

        return (
            f"VERIFY_SUCCESS: File '{file_name}' verified successfully. "
            f"Current state: {len(lines)} lines, {len(content)} characters."
        )

    except UnicodeDecodeError:
        return f"VERIFY_FAILED: File '{file_name}' is not valid UTF-8 text."
    except OSError as e:
        return f"VERIFY_FAILED: Could not read '{file_name}': {e}"