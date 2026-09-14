import threading
from typing import Dict, Optional
from autogen_core import CancellationToken


class CancellationManager:
    """Tracks active AutoGen cancellation tokens per chat_id."""
    def __init__(self):
        self._tokens: Dict[str, CancellationToken] = {}
        self._lock = threading.Lock()

    def create_token(self, chat_id: str) -> CancellationToken:
        with self._lock:
            token = CancellationToken()
            self._tokens[chat_id] = token
            return token

    def cancel(self, chat_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(chat_id)
            if token and not token.is_cancelled():
                token.cancel()
                return True
            return False

    def remove_token(self, chat_id: str) -> None:
        with self._lock:
            self._tokens.pop(chat_id, None)


cancellation_manager = CancellationManager()