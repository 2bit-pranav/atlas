"""Credentials in free text (a command line, a tool's output), hidden before it
reaches the UI.

A skill's requirement can carry one (`git+https://TOKEN@github.com/...`,
`--index-url https://user:pw@host/simple`), and pip and npm echo what they
install. Found by shape, not by knowing the secret: a URL's user info, a
`name=value` or `--name value` whose name says it is a secret.
"""

from __future__ import annotations

import re

REDACTED = "••••••"

_NAME = r"[\w.-]*(?:token|secret|password|passwd|api[-_]?key|auth|credential|bearer)[\w.-]*"
#: scheme://user:password@ or scheme://token@
_USERINFO = re.compile(r"(?P<scheme>\b[a-z][\w+.-]*://)(?P<user>[^\s/@:]+)(?::(?P<pw>[^\s/@]*))?@", re.I)
#: name=value, --name=value, ?name=value&
_ASSIGNED = re.compile(rf"(?P<name>{_NAME})=(?P<value>[^\s&]+)", re.I)
#: --name value
_FLAG = re.compile(rf"(?P<flag>--?{_NAME})\s+(?P<value>(?!-)\S+)", re.I)


def redact_text(text: str) -> str:
    def userinfo(m: re.Match[str]) -> str:
        if m["pw"] is not None:
            return f"{m['scheme']}{m['user']}:{REDACTED}@"
        return f"{m['scheme']}{REDACTED}@"

    text = _USERINFO.sub(userinfo, text)
    text = _ASSIGNED.sub(lambda m: f"{m['name']}={REDACTED}", text)
    return _FLAG.sub(lambda m: f"{m['flag']} {REDACTED}", text)


__all__ = ["REDACTED", "redact_text"]
