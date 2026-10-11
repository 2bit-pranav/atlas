"""ULID generation (spec section 5: "ULID primary keys").

A shared leaf utility rather than part of a layer: both L1 (launch ids) and L2
(row ids) need it, and the ground rule is that a layer never imports from a
higher one.

26 characters of Crockford base32: 10 characters of millisecond timestamp
followed by 16 characters (80 bits) of randomness. Lexicographic order matches
creation order, which makes `ORDER BY id` a usable creation-time sort and keeps
debug logs readable.

Not monotonic *within* a single millisecond - that would need the random
component incremented on collision. Two ids created in the same millisecond sort
arbitrarily. Uniqueness comes from the 80 random bits, which is ample.
"""

from __future__ import annotations

import secrets
import time

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_ULID_LENGTH = 26
_RANDOM_BITS = 80


def new_ulid() -> str:
    """A fresh 26-character ULID."""
    value = (int(time.time() * 1000) << _RANDOM_BITS) | secrets.randbits(_RANDOM_BITS)
    chars = []
    for _ in range(_ULID_LENGTH):
        chars.append(CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def ulid_timestamp(ulid: str) -> int:
    """Recover the epoch-ms timestamp encoded in a ULID's first 10 characters."""
    if len(ulid) < 10:
        raise ValueError(f"not a ULID: {ulid!r}")
    value = 0
    for char in ulid[:10]:
        value = value * 32 + CROCKFORD.index(char)
    return value


def now_ms() -> int:
    """Integer epoch milliseconds, the spec's timestamp convention."""
    return int(time.time() * 1000)


__all__ = ["CROCKFORD", "new_ulid", "now_ms", "ulid_timestamp"]
