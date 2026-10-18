"""Identifiers and timestamps, in the one convention this project uses.

A leaf utility under `core/` because both the CLI (launch ids) and the store
(row ids) need it, and the ground rule here is that a layer never imports from
a higher one.

**26 characters of Crockford base32:** 10 characters of millisecond timestamp
followed by 16 characters (80 bits) of randomness. Lexicographic order matches
creation order, which makes `ORDER BY id` a usable creation-time sort and keeps
debug logs readable -- two properties that matter more here than they sound,
because a chat transcript is read by eye far more often than it is queried.

Deliberately *not* monotonic within a single millisecond. Making it so would
mean incrementing the random component on collision, and every row id in this
project is a `uuid4().hex` from the store anyway -- ULIDs are for launch ids,
where ordering actually matters. Uniqueness comes from the 80 random bits.
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


def now_ms() -> int:
    """Integer epoch milliseconds, the project's timestamp convention.

    Named rather than inlined because the unit is the thing that gets forgotten:
    the store writes `time.time() * 1000` and the API serves it unchanged, so a
    client that multiplies again puts every timestamp in the year 58000.
    """
    return int(time.time() * 1000)


__all__ = ["CROCKFORD", "ULID_LENGTH", "new_ulid", "now_ms"]