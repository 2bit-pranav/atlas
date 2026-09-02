from typing import List, Optional

from server.managers import skill_manager

async def run_skill_script(
    skill_name: str,
    script: str,
    args: Optional[List[str]] = None,
) -> dict:
    """Run an allowlisted script bundled inside an installed skill."""
    return await skill_manager.run_script(skill_name, script, args)
