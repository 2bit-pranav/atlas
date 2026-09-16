"""Thread-safe cancellation tokens for active chat turns."""

from threading import Lock

from autogen_core import CancellationToken


class CancellationRegistry:
    def __init__(self) -> None:
        self._tokens: dict[str, CancellationToken] = {}
        self._lock = Lock()

    def create(self, chat_id: str) -> CancellationToken:
        token = CancellationToken()
        with self._lock:
            previous = self._tokens.get(chat_id)
            if previous and not previous.is_cancelled():
                previous.cancel()
            self._tokens[chat_id] = token
        return token

    def cancel(self, chat_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(chat_id)
            if token is None or token.is_cancelled():
                return False
            token.cancel()
            return True

    def remove(self, chat_id: str, token: CancellationToken | None = None) -> None:
        with self._lock:
            current = self._tokens.get(chat_id)
            if token is None or current is token:
                self._tokens.pop(chat_id, None)


cancellation_registry = CancellationRegistry()
