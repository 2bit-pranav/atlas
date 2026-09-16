"""Canonical on-disk chat sessions, isolated per chat identifier."""

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_CHAT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.root = (root or project_root / ".storage" / "sessions").resolve()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _validate_id(self, chat_id: str) -> str:
        if not _CHAT_ID.fullmatch(chat_id):
            raise ValueError("Invalid chat identifier.")
        return chat_id

    def _directory(self, chat_id: str) -> Path:
        return self.root / self._validate_id(chat_id)

    def _session_path(self, chat_id: str) -> Path:
        return self._directory(chat_id) / "session.json"

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def create_session(self, chat_id: Optional[str] = None) -> str:
        safe_id = self._validate_id(chat_id) if chat_id else str(uuid.uuid4())
        path = self._session_path(safe_id)
        if not path.exists():
            now = self._now()
            self._write_json(path, {
                "id": safe_id,
                "title": "New Chat",
                "created_at": now,
                "updated_at": now,
                "messages": [],
            })
        self.workspace_for(safe_id)
        return safe_id

    def get_session(self, chat_id: str) -> Optional[dict[str, Any]]:
        path = self._session_path(chat_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _require_session(self, chat_id: str) -> dict[str, Any]:
        session = self.get_session(chat_id)
        if session is None:
            raise KeyError(f"Session '{chat_id}' was not found.")
        return session

    def _save_session(self, session: dict[str, Any]) -> None:
        session["updated_at"] = self._now()
        self._write_json(self._session_path(session["id"]), session)

    def get_all_sessions(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        items: list[dict[str, Any]] = []
        for path in self.root.glob("*/session.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items.append({key: data.get(key, "") for key in ("id", "title", "created_at", "updated_at")})
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(items, key=lambda item: item["updated_at"], reverse=True)

    def set_title(self, chat_id: str, title: str) -> bool:
        session = self.get_session(chat_id)
        if session is None:
            return False
        session["title"] = title.strip() or "Untitled Chat"
        self._save_session(session)
        return True

    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        message_id: Optional[str] = None,
        attachments: Optional[list[dict[str, str]]] = None,
        thought: Optional[str] = None,
    ) -> dict[str, Any]:
        session = self._require_session(chat_id)
        record = {
            "id": message_id or str(uuid.uuid4()),
            "role": role,
            "content": content,
            "attachments": attachments or [],
            "timestamp": self._now(),
        }
        if thought:
            record["thought"] = thought
        session.setdefault("messages", []).append(record)
        self._save_session(session)
        return record

    def workspace_for(self, chat_id: str) -> Path:
        workspace = self._directory(chat_id) / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def set_agent_state(self, chat_id: str, state: Any) -> None:
        self._require_session(chat_id)
        self._write_json(self._directory(chat_id) / "agent_state.json", state)

    def get_agent_state(self, chat_id: str) -> Optional[Any]:
        path = self._directory(chat_id) / "agent_state.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def truncate_to_message(self, chat_id: str, message_id: str, *, include: bool = True) -> bool:
        session = self.get_session(chat_id)
        if session is None:
            return False
        messages = session.get("messages", [])
        index = next((i for i, item in enumerate(messages) if item.get("id") == message_id), None)
        if index is None:
            return False
        session["messages"] = messages[: index + 1 if include else index]
        self._save_session(session)
        (self._directory(chat_id) / "agent_state.json").unlink(missing_ok=True)
        return True

    def delete_session(self, chat_id: str) -> bool:
        directory = self._directory(chat_id)
        if not directory.exists():
            return False
        shutil.rmtree(directory)
        return True


session_store = SessionStore()
