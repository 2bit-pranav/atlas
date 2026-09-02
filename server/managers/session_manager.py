import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class ChatSessionManager:
    """Manages in-memory chat sessions with message history and agent state."""

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def create_session(self, chat_id: Optional[str] = None) -> str:
        """Create or return session ID."""
        if not chat_id:
            chat_id = str(uuid.uuid4())

        if chat_id not in self._sessions:
            now_iso = datetime.now(timezone.utc).isoformat()
            self._sessions[chat_id] = {
                "id": chat_id,
                "title": "New Chat",
                "created_at": now_iso,
                "updated_at": now_iso,
                "messages": [],
                "agent_state": None,
            }
        return chat_id

    def get_session(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full session data."""
        return self._sessions.get(chat_id)

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Retrieve all sessions sorted by update time."""
        sessions = [
            {
                "id": s["id"],
                "title": s.get("title", "Untitled Chat"),
                "created_at": s.get("created_at", ""),
                "updated_at": s.get("updated_at", ""),
            }
            for s in self._sessions.values()
        ]
        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        return sessions

    def set_title(self, chat_id: str, title: str) -> bool:
        """Set session title."""
        if session := self.get_session(chat_id):
            session["title"] = title
            return True
        return False

    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        attachments: Optional[List[Dict[str, str]]] = None,
        thought: Optional[str] = None,
    ) -> bool:
        """Add a message to session."""
        if session := self.get_session(chat_id):
            session["messages"].append({
                "id": str(uuid.uuid4()),
                "role": role,
                "content": content,
                "attachments": attachments or [],
                "thought": thought,
            })
            session["updated_at"] = datetime.now(timezone.utc).isoformat()
            return True
        return False

    def set_agent_state(self, chat_id: str, state: Any) -> bool:
        """Store agent state."""
        if session := self.get_session(chat_id):
            session["agent_state"] = state
            return True
        return False

    def get_agent_state(self, chat_id: str) -> Optional[Any]:
        """Retrieve agent state."""
        if session := self.get_session(chat_id):
            return session.get("agent_state")
        return None

    def delete_session(self, chat_id: str) -> bool:
        """Delete session."""
        if chat_id in self._sessions:
            del self._sessions[chat_id]
            return True
        return False


# Global singleton instance
chat_session_manager = ChatSessionManager()
