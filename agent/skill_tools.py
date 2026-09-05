from typing import List, Optional

from server.managers import skill_manager

async def run_skill_script(
    skill_name: str,
    script: str,
    args: Optional[List[str]] = None,
) -> dict:
    """
    Run an allowlisted script bundled inside an installed skill.

    Args:
        skill_name: Exact name of the installed skill (e.g. 'pdf').
        script: Exact script path relative to the skill folder (e.g. 'scripts/rotate_pdf.py').
        args: List of positional CLI string arguments in order (e.g. ["C:/path/input.pdf", "C:/path/output.pdf", "90", "all"]). MUST BE A LIST OF STRINGS. Do not pass a single string.
    """
    return await skill_manager.run_script(skill_name, script, args)
