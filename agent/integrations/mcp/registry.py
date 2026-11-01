"""Searching the public MCP registry, and turning an entry into a config."""

from __future__ import annotations

from typing import Any

from agent.integrations.mcp.pool import FOLDERS

# ----------------------------------------------------------- registry --

REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"


def registry_entry_to_config(server: dict[str, Any]) -> list[dict[str, Any]]:
    """The ways to run one registry server, each as a ready mcpServers block.

    A server can publish several: an npm package (run with npx), a PyPI package
    (uvx), an OCI image, or a remote URL. Each becomes a separate option with
    the environment variables it needs listed, so the user fills them in rather
    than discovering them from a failed start.
    """
    options: list[dict[str, Any]] = []
    for pkg in server.get("packages") or []:
        ident, version = pkg.get("identifier"), pkg.get("version")
        if not ident or (pkg.get("transport") or {}).get("type", "stdio") != "stdio":
            continue
        kind = pkg.get("registryType")
        if kind == "npm":
            config: dict[str, Any] = {"command": "npx",
                                      "args": ["-y", f"{ident}@{version}" if version else ident]}
        elif kind == "pypi":
            config = {"command": "uvx", "args": [f"{ident}=={version}" if version else ident]}
        elif kind == "oci":
            config = {"command": "docker", "args": ["run", "-i", "--rm", ident]}
        else:
            continue
        config["args"] += [str(a.get("value")) for a in pkg.get("packageArguments") or []
                           if a.get("type") == "positional" and a.get("value")]
        if "server-filesystem" in ident:
            # Its allowed folders are its arguments: let Atlas fill them in.
            config["args"].append(FOLDERS)
        env = pkg.get("environmentVariables") or []
        if env:
            config["env"] = {e["name"]: str(e.get("default") or "") for e in env if e.get("name")}
        options.append({"kind": kind, "local": True, "config": config, "env": env})
    for remote in server.get("remotes") or []:
        if remote.get("url"):
            config = {"url": remote["url"]}
            headers = remote.get("headers") or []
            if headers:
                config["headers"] = {h["name"]: "" for h in headers if h.get("name")}
            options.append({"kind": remote.get("type", "remote"), "local": False,
                            "config": config, "env": headers})
    return options


_registry_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


_REGISTRY_TTL = 600.0


def search_registry(query: str, limit: int = 30) -> list[dict[str, Any]]:
    """Search the official MCP registry. Latest versions only, cached ten minutes.

    The registry can take half a minute to answer, so a repeated search (the
    user typing, clearing, typing again) is served from memory.
    """
    import time

    import httpx

    key = query.strip().lower()
    hit = _registry_cache.get(key)
    if hit and time.monotonic() - hit[0] < _REGISTRY_TTL:
        return hit[1]
    response = httpx.get(REGISTRY, params={"search": key, "limit": limit, "version": "latest"},
                         timeout=60, follow_redirects=True)
    response.raise_for_status()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in response.json().get("servers") or []:
        server = item.get("server") or {}
        meta = (item.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
        name = server.get("name")
        if not name or name in seen or meta.get("isLatest") is False:
            continue
        seen.add(name)
        options = registry_entry_to_config(server)
        if not options:
            continue
        out.append({
            "name": name,
            "title": server.get("title") or name.split("/")[-1],
            "description": server.get("description", ""),
            "version": server.get("version"),
            "repository": (server.get("repository") or {}).get("url"),
            "options": options,
        })
        if len(out) >= limit:
            break
    _registry_cache[key] = (time.monotonic(), out)
    return out


__all__ = ["REGISTRY", "registry_entry_to_config", "search_registry"]
