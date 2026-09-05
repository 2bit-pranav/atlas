import asyncio
import json
import os
import re
import subprocess
import sys
import shutil
import tempfile
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
SKILLS_API_URL = os.getenv("SKILLS_API_URL", "https://skills.sh/api/v1/skills")
REGISTRY_PATH = SKILLS_DIR / ".atlas-registry.json"


class SkillManager:
    """Discovers local skills and proxies the remote skills.sh catalog."""

    def __init__(self, skills_dir: Path = SKILLS_DIR):
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def _registry(self) -> Dict[str, Dict[str, str]]:
        try:
            data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_registry(self, registry: Dict[str, Dict[str, str]]) -> None:
        REGISTRY_PATH.write_text(json.dumps(registry, indent=2), encoding="utf-8")

    def local_skills(self) -> List[Dict[str, Any]]:
        result = []
        for skill_file in sorted(self.skills_dir.glob("*/SKILL.md")):
            result.append(self._read_local_skill(skill_file))
        return result

    def _read_local_skill(self, skill_file: Path) -> Dict[str, Any]:
        text = skill_file.read_text(encoding="utf-8", errors="replace")
        heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        name = skill_file.parent.name
        return {
            "name": name,
            "description": heading.group(1).strip() if heading else "Installed Atlas skill",
            "path": str(skill_file.parent),
            "installed": True,
            "metadata": text[:30000],  # Full SKILL.md — never truncate early
            "source": self._registry().get(name, {}).get("source"),
        }

    async def catalog(self, page: int = 1, per_page: int = 24, search: str = "") -> Dict[str, Any]:
        if search and len(search.strip()) < 2:
            return {"data": [], "query": search, "count": 0}
        endpoint = f"{SKILLS_API_URL}/search" if search.strip() else SKILLS_API_URL
        params = {"q": search.strip(), "limit": per_page} if search.strip() else {
            "page": max(0, page - 1), "per_page": per_page, "view": "all-time"
        }
        headers = {"Accept": "application/json"}
        token = os.getenv("SKILLS_API_TOKEN") or os.getenv("VERCEL_OIDC_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(f"{endpoint}?{urlencode(params)}", headers=headers)
        try:
            def fetch() -> Any:
                with urlopen(request, timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))
            data = await asyncio.to_thread(fetch)
            if not isinstance(data, dict):
                return {"data": data}
            return data
        except Exception as exc:
            return {"data": [], "page": page - 1, "per_page": per_page, "error": str(exc)}

    async def remote_detail(self, skill_id: str) -> Dict[str, Any]:
        """Fetch a skill snapshot, including SKILL.md and bundled files."""
        if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)?", skill_id):
            raise ValueError("Invalid skill id")
        token = os.getenv("SKILLS_API_TOKEN") or os.getenv("VERCEL_OIDC_TOKEN")
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{SKILLS_API_URL}/{quote(skill_id, safe='/')}", headers=headers
        )

        def fetch() -> Any:
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))

        result = await asyncio.to_thread(fetch)
        return result if isinstance(result, dict) else {"files": []}

    def get_local(self, name: str) -> Optional[Dict[str, Any]]:
        skill_file = self.skills_dir / name / "SKILL.md"
        if not skill_file.is_file():
            return None
        return self._read_local_skill(skill_file)

    @staticmethod
    def _command_tokens(command: str) -> List[str]:
        if not command.strip() or any(char in command for char in (";", "&", "|", ">", "<", "`", "\\")):
            raise ValueError("Paste only the npx skills add command from skills.sh")
        tokens = shlex.split(command, posix=False)
        if len(tokens) < 4 or tokens[0].lower() not in {"npx", "npx.cmd"} or tokens[1:3] != ["skills", "add"]:
            raise ValueError("Command must start with: npx skills add")
        if "-g" in tokens or "--global" in tokens:
            raise ValueError("Global installs are not supported; Atlas installs skills locally")
        return tokens

    async def install_command(self, command: str) -> Dict[str, Any]:
        """Run a pasted skills.sh command in an isolated project and copy skills into Atlas."""
        tokens = self._command_tokens(command)
        source = tokens[3]
        requested = []
        for index, token in enumerate(tokens):
            if token in {"--skill", "-s"} and index + 1 < len(tokens):
                requested.append(tokens[index + 1])
        temp_dir = Path(tempfile.mkdtemp(prefix="atlas-skill-command-"))
        try:
            cli = "npx.cmd" if os.name == "nt" else "npx"
            completed = await asyncio.to_thread(
                subprocess.run,
                [cli, "--yes", "skills", "add", *tokens[3:], "--agent", "opencode", "--copy", "--yes"],
                cwd=str(temp_dir), check=False, timeout=120,
                capture_output=True, text=True,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "npx skills installation failed").strip()
                raise RuntimeError(detail[-2000:])
            candidates = [path.parent for path in temp_dir.rglob("SKILL.md")]
            if requested:
                candidates = [path for path in candidates if path.name in requested or path.parent.name in requested]
            if not candidates:
                raise RuntimeError("npx completed but no requested SKILL.md was installed")
            registry = self._registry()
            installed = []
            for source_root in candidates:
                skill_name = source_root.name
                target = self.skills_dir / skill_name
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source_root, target)
                registry[skill_name] = {"source": source, "name": skill_name}
                installed.append(skill_name)
            self._save_registry(registry)
            return {"status": "installed", "skills": installed}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def remove(self, name: str) -> bool:
        """Remove a skill from the Atlas catalogue and preload source."""
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise ValueError("Invalid skill name")
        target = (self.skills_dir / name).resolve()
        if self.skills_dir.resolve() not in target.parents or not target.is_dir():
            return False
        shutil.rmtree(target)
        registry = self._registry()
        registry.pop(name, None)
        self._save_registry(registry)
        return True

    async def update_all(self) -> Dict[str, Any]:
        registry = self._registry()
        updated = []
        for name, entry in list(registry.items()):
            result = await self.install_command(
                f"npx skills add {entry['source']} --skill {entry['name']}"
            )
            updated.extend(result.get("skills", []))
        return {"status": "updated", "skills": updated}

    def resolve_mentions(self, prompt: str) -> List[str]:
        return re.findall(r"@([A-Za-z0-9._-]+)", prompt)

    @staticmethod
    def _extract_script_usage(script_path: Path) -> str:
        """Reads docstrings or usage headers from a python script."""
        try:
            text = script_path.read_text(encoding="utf-8", errors="replace")
            doc_match = re.search(r'"""(.*?)"""', text, re.DOTALL)
            if doc_match:
                lines = [line.strip() for line in doc_match.group(1).splitlines() if line.strip()]
                return "\n      ".join(lines[:12])
            comments = []
            for line in text.splitlines()[:15]:
                s = line.strip()
                if s.startswith("#") and not s.startswith("#!"):
                    comments.append(s.lstrip("#").strip())
            if comments:
                return "\n      ".join(comments[:8])
        except Exception:
            pass
        return ""

    def context_for_prompt(self, prompt: str, uploaded_file_paths: list[str] | None = None) -> str:
        skills = [self.get_local(name) for name in self.resolve_mentions(prompt)]
        skills = [skill for skill in skills if skill]
        if not skills:
            return ""

        formatted_sections = []
        for skill in skills:
            skill_path = Path(skill["path"])
            scripts_dir = skill_path / "scripts"
            script_entries: list[str] = []
            if scripts_dir.exists():
                for p in sorted(scripts_dir.iterdir()):
                    if p.is_file():
                        rel = f"scripts/{p.name}"
                        usage = self._extract_script_usage(p)
                        if usage:
                            script_entries.append(f"  - script: '{rel}'\n    usage:\n      {usage}")
                        else:
                            script_entries.append(f"  - script: '{rel}'")

            manifest = ""
            if script_entries:
                manifest = "\nBUNDLED SCRIPTS (run via run_skill_script(skill_name, script, args)):\n" + "\n\n".join(script_entries)

            # Surface any uploaded file paths so the model can reference them by absolute path
            files_block = ""
            if uploaded_file_paths:
                files_block = (
                    "\nATTACHED INPUT FILES (use these exact absolute paths in any script you write or pass to args):\n"
                    + "\n".join(f"  INPUT_FILE: {p}" for p in uploaded_file_paths)
                    + "\n"
                )

            # Concise scripting guide injected after every skill activation
            scripting_guide = (
                "\nSCRIPTING RULES (MUST FOLLOW):\n"
                "1. To run a bundled script, call `run_skill_script(skill_name, script, args)`:\n"
                "   - skill_name: Exact skill name string, e.g. 'pdf'.\n"
                "   - script: Exact script path string relative to skill root, e.g. 'scripts/rotate_pdf.py'.\n"
                "   - args: MUST BE A LIST OF STRINGS containing positional arguments in order, e.g. [input_file_path, output_file_path, '90', 'all']. NEVER pass a single string or flag string to args!\n"
                "2. Use the INPUT_FILE absolute path(s) listed above directly in args or custom scripts — never use bare filenames.\n"
                "3. Write output files as absolute paths in Downloads, e.g. str(Path.home() / 'Downloads' / 'result.pdf').\n"
                "4. Alternatively, use `run_python_code(code, dependencies=['pypdf', ...])` to run a dynamic inline Python script.\n"
                "5. After the script finishes, call `verify_file(file_path)` on the output path.\n"
            )

            formatted_sections.append(
                f"=== ACTIVATED SKILL: {skill['name']} ===\n"
                f"SKILL ROOT DIR: {skill_path.resolve()}\n"
                f"{manifest}\n"
                f"{files_block}"
                f"{scripting_guide}\n"
                f"=== SKILL INSTRUCTIONS (SKILL.md) ===\n"
                f"{skill['metadata']}"
            )

        return "\n\n".join(formatted_sections)

    async def run_script(self, name: str, script: str, args: Optional[List[str]] = None) -> Dict[str, Any]:
        skill = self.get_local(name)
        if not skill:
            raise ValueError("Skill is not installed")
        script_path = (Path(skill["path"]) / script).resolve()
        skill_root = Path(skill["path"]).resolve()
        if skill_root not in script_path.parents or not script_path.is_file():
            raise ValueError("Script is outside the skill directory or does not exist")
        command = [str(script_path), *(args or [])]
        if script_path.suffix.lower() == ".py":
            command = [sys.executable, str(script_path), *(args or [])]
        completed = await asyncio.to_thread(subprocess.run, command, cwd=str(skill_root), capture_output=True, text=True, timeout=30)
        return {"returncode": completed.returncode, "stdout": completed.stdout[-10000:], "stderr": completed.stderr[-10000:]}


skill_manager = SkillManager()
