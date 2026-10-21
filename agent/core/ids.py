"""ULIDs for launch ids.

A leaf module under `core/` so the CLI can use it without importing anything
above it. Chat and turn rows use `uuid4().hex` (`chats.py`) instead.

26 characters of Crockford base32: 10 of millisecond timestamp, then 16 (80
bits) of randomness. Lexicographic order matches creation order, so `ORDER BY
id` sorts by time and logs read in order. Deliberately not monotonic within one
millisecond; uniqueness comes from the 80 random bits.
"""

from __future__ import annotations

import secrets
import time

#: Crockford base32: no I, L, O or U, so an id read aloud stays unambiguous.
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

ULID_LENGTH = 26
_RANDOM_BITS = 80


def new_ulid() -> str:
    """A fresh 26-character ULID."""
    value = (int(time.time() * 1000) << _RANDOM_BITS) | secrets.randbits(_RANDOM_BITS)
    chars = []
    for _ in range(ULID_LENGTH):
        chars.append(CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


__all__ = ["CROCKFORD", "ULID_LENGTH", "new_ulid"]