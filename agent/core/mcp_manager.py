"""MCP servers: a pool of connections that outlives every turn.

The config is `mcp.json` at the application root, in the standard `mcpServers`
format, so a block from any MCP server's README pastes in unchanged:

    {"mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}}}

**Why a pool.** Atlas builds a fresh agent for every turn (so LIVE settings
apply). Handing that agent an `MCPClient` would make Strands start the server
when the agent is built and stop it when the agent goes away -- relaunching
`npx some-server` on every single message. Instead the pool connects each
server once, holds it open as a permanent consumer, and gives each turn the
server's individual tool objects. A turn's agent never owns a connection.

**Per-tool modes: on, ask, off.** "Off" is stored in the server's standard
`tool_filters.rejected` list; "ask" (the user must Allow each call, see
`policy.py`) in an Atlas-only `atlas.ask` list. The pool connects *without*
either, so the UI can still list a switched-off tool and switch it back on;
filtering happens when a turn's tool list is built, and changing a mode needs
no reconnect.

**Allowed folders.** Atlas cannot know what an arbitrary server's arguments
mean, and Strands' MCP client does not implement the MCP "roots" protocol, so
the link is explicit: an argument `"{atlas:folders}"` is replaced, when the
server connects, by the chats folder and every folder in `access.folders`,
one argument each. Changing that list reconnects the servers that use it.

**Cost.** Every tool schema is sent with every request. On a 32k window and a
2B model that is the real constraint on MCP, so each tool reports an estimate
of its prompt tokens and the UI shows the total.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from strands.tools.mcp import MCPClient

from agent.core import paths
from agent.core.settings import Settings

logger = logging.getLogger(__name__)

#: The pool's own consumer id. While it is registered, Strands never tears the
#: connection down, whatever the per-turn agents do.
POOL = "atlas-mcp-pool"


class McpError(Exception):
    """A config edit was refused. The message is shown to the user."""


def _estimate_tokens(spec: dict[str, Any]) -> int:
    """About four characters per token, which is close enough to budget with."""
    return max(1, len(json.dumps(spec, separators=(",", ":"))) // 4)


class _Server:
    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.config = config
        self.status = "disabled" if config.get("disabled") else "stopped"
        self.error: str | None = None
        self.client: MCPClient | None = None
        self.tools: list[Any] = []

    @property
    def rejected(self) -> set[str]:
        filters = self.config.get("tool_filters") or {}
        return {str(n) for n in filters.get("rejected") or [] if isinstance(n, str)}

    @property
    def ask(self) -> set[str]:
        atlas = self.config.get("atlas") or {}
        return {str(n) for n in atlas.get("ask") or [] if isinstance(n, str)}

    def mode(self, tool: str) -> str:
        return "off" if tool in self.rejected else "ask" if tool in self.ask else "on"

    def describe(self) -> dict[str, Any]:
        tools = []
        for tool in self.tools:
            spec = tool.tool_spec
            original = getattr(getattr(tool, "mcp_tool", None), "name", tool.tool_name)
            tools.append({
                "name": original,
                "agent_name": tool.tool_name,
                "description": spec.get("description", "").removeprefix(MCP_LABEL.format(self.name)),
                "enabled": original not in self.rejected,
                "mode": self.mode(original),
                "tokens": _estimate_tokens(spec),
            })
        return {
            "name": self.name,
            "config": self.config,
            "transport": "remote" if self.config.get("url") else "local",
            "status": self.status,
            "error": self.error,
            "enabled": not self.config.get("disabled", False),
            "uses_folders": FOLDERS in (self.config.get("args") or []),
            "tools": tools,
            "tokens": sum(t["tokens"] for t in tools if t["enabled"]),
        }


MCP_LABEL = "[MCP: {}] "

#: Replaced, in a server's `args`, by the folders Atlas allows.
FOLDERS = "{atlas:folders}"


def _label(tool: Any, server: str) -> None:
    """Prefix the description the model sees with the tool's server.

    Without it an MCP tool is just another name in the list, and asked to
    "use the MCP fetch tool" the model reached for the built-in web_fetch or
    went looking for a skill. The label is also how `mcp_server_of` finds a
    tool's server again when the prompt's tool list is built.
    """
    mcp_tool = getattr(tool, "mcp_tool", None)
    if mcp_tool is None:
        return
    label = MCP_LABEL.format(server)
    description = mcp_tool.description or f"Tool which performs {mcp_tool.name}"
    if not description.startswith(label):
        mcp_tool.description = label + description


def mcp_server_of(tool: Any) -> str | None:
    description = getattr(getattr(tool, "mcp_tool", None), "description", "") or ""
    if description.startswith("[MCP: "):
        return description[6:description.index("]")]
    return None


class McpManager:
    """Owns `mcp.json` and one connection per enabled server."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._servers: dict[str, _Server] = {}

    # ------------------------------------------------------------- config --

    def config_path(self) -> Path:
        return paths.mcp_config(self.settings)

    def read_config(self) -> dict[str, dict[str, Any]]:
        path = self.config_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise McpError(f"{path} is not valid JSON: {exc}") from exc
        servers = data.get("mcpServers", data) if isinstance(data, dict) else {}
        return {k: v for k, v in servers.items() if isinstance(v, dict)}

    def _write_config(self, servers: dict[str, dict[str, Any]]) -> None:
        path = self.config_path()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps({"mcpServers": servers}, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    # ---------------------------------------------------------- lifecycle --

    def start_all(self) -> None:
        """Connect every enabled server. Blocking; call from a worker thread."""
        try:
            config = self.read_config()
        except McpError as exc:
            logger.error("%s", exc)
            return
        for name, server in config.items():
            self._connect(name, server)

    def stop_all(self) -> None:
        with self._lock:
            for server in self._servers.values():
                self._disconnect(server)
            self._servers.clear()

    def _connect(self, name: str, config: dict[str, Any]) -> _Server:
        with self._lock:
            old = self._servers.pop(name, None)
            if old is not None:
                self._disconnect(old)
            server = _Server(name, config)
            self._servers[name] = server
        if config.get("disabled"):
            return server

        server.status = "connecting"
        try:
            # Connected without tool_filters (or Atlas's own keys), so a
            # switched-off tool can still be listed and switched back on.
            # Filtering happens per turn.
            unfiltered = {k: v for k, v in config.items() if k not in ("tool_filters", "atlas")}
            if FOLDERS in (unfiltered.get("args") or []):
                unfiltered["args"] = self._expand_folders(unfiltered["args"])
            unfiltered.setdefault("startup_timeout", int(self.settings.mcp.startup_timeout))
            (client,) = MCPClient.load_servers({name: unfiltered}, prefix_with_server_name=True)
            client.add_consumer(POOL)
            client.start()
            client._tool_provider_started = True  # noqa: SLF001 - Strands' own lifecycle flag
            server.client = client
            server.tools = list(client._list_all_tools_sync())  # noqa: SLF001
            for tool in server.tools:
                _label(tool, name)
            server.status = "connected"
            logger.info("mcp %s connected (%d tools)", name, len(server.tools))
        except Exception as exc:  # noqa: BLE001 - one bad server must not stop the rest
            server.status = "failed"
            server.error = f"{type(exc).__name__}: {exc}"
            logger.warning("mcp %s failed: %s", name, server.error)
            self._disconnect(server)
        return server

    def _expand_folders(self, args: list[Any]) -> list[Any]:
        folders = [str(paths.data_dir(self.settings) / "chats")]
        for f in self.settings.access.folders:
            p = Path(f).expanduser()
            if f.strip() and p.is_dir():
                folders.append(str(p.resolve()))
        out: list[Any] = []
        for arg in args:
            out.extend(folders if arg == FOLDERS else [arg])
        return out

    def set_settings(self, settings: Settings) -> None:
        """Take new settings; reconnect the servers whose folders changed."""
        before = list(self.settings.access.folders)
        self.settings = settings
        if before == list(settings.access.folders):
            return
        try:
            config = self.read_config()
        except McpError:
            return
        for name, server in config.items():
            if FOLDERS in (server.get("args") or []) and not server.get("disabled"):
                logger.info("mcp %s: allowed folders changed, reconnecting", name)
                self._connect(name, server)

    def is_sensitive(self, agent_name: str) -> bool:
        """Whether this tool (by its agent-facing name) must ask the user first."""
        with self._lock:
            for server in self._servers.values():
                for tool in server.tools:
                    if tool.tool_name == agent_name:
                        original = getattr(getattr(tool, "mcp_tool", None), "name", agent_name)
                        return server.mode(original) == "ask"
        return False

    @staticmethod
    def _disconnect(server: _Server) -> None:
        if server.client is not None:
            try:
                server.client.remove_consumer(POOL)
            except Exception:  # noqa: BLE001
                logger.debug("mcp %s did not stop cleanly", server.name, exc_info=True)
        server.client = None
        server.tools = []

    # ------------------------------------------------------------- per turn --

    def agent_tools(self) -> list[Any]:
        """The tool objects for one turn: connected servers, switched-on tools."""
        out: list[Any] = []
        with self._lock:
            for server in self._servers.values():
                if server.status != "connected":
                    continue
                rejected = server.rejected
                out.extend(t for t in server.tools
                           if getattr(getattr(t, "mcp_tool", None), "name", t.tool_name)
                           not in rejected)
        return out

    def describe(self) -> list[dict[str, Any]]:
        try:
            config = self.read_config()
        except McpError:
            config = {}
        with self._lock:
            for name, cfg in config.items():
                if name not in self._servers:
                    self._servers[name] = _Server(name, cfg)
                else:
                    self._servers[name].config = cfg
            return [self._servers[n].describe() for n in sorted(self._servers) if n in config]

    # -------------------------------------------------------------- edits --

    def upsert(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        name = name.strip()
        if not name or any(c in name for c in "/\\ "):
            raise McpError("a server name needs letters, digits, '-' or '_' only")
        if not isinstance(config, dict) or not (config.get("command") or config.get("url")):
            raise McpError("a server needs either a `command` (local) or a `url` (remote)")
        servers = self.read_config()
        keep = servers.get(name, {})
        # Keep the user's tool modes across an edit of the launch command.
        for key in ("tool_filters", "atlas"):
            if key in keep and key not in config:
                config = {**config, key: keep[key]}
        servers[name] = config
        self._write_config(servers)
        return self._connect(name, config).describe()

    def remove(self, name: str) -> None:
        servers = self.read_config()
        servers.pop(name, None)
        self._write_config(servers)
        with self._lock:
            server = self._servers.pop(name, None)
        if server is not None:
            self._disconnect(server)

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        servers = self.read_config()
        if name not in servers:
            raise McpError(f"no MCP server {name!r}")
        servers[name] = {**servers[name], "disabled": not enabled}
        if enabled:
            servers[name].pop("disabled")
        self._write_config(servers)
        return self._connect(name, servers[name]).describe()

    def set_tool(self, name: str, tool: str, mode: str) -> dict[str, Any]:
        """`mode` is "on", "ask" (the user approves each call) or "off"."""
        if mode not in ("on", "ask", "off"):
            raise McpError(f"a tool mode is on, ask or off, not {mode!r}")
        servers = self.read_config()
        if name not in servers:
            raise McpError(f"no MCP server {name!r}")
        filters = dict(servers[name].get("tool_filters") or {})
        rejected = {t for t in filters.get("rejected") or [] if t != tool} | ({tool} if mode == "off" else set())
        filters["rejected"] = sorted(rejected)
        atlas = dict(servers[name].get("atlas") or {})
        ask = {t for t in atlas.get("ask") or [] if t != tool} | ({tool} if mode == "ask" else set())
        atlas["ask"] = sorted(ask)
        servers[name] = {**servers[name], "tool_filters": filters, "atlas": atlas}
        self._write_config(servers)
        with self._lock:
            if name in self._servers:
                self._servers[name].config = servers[name]
                return self._servers[name].describe()
        return _Server(name, servers[name]).describe()

    def reconnect(self, name: str) -> dict[str, Any]:
        servers = self.read_config()
        if name not in servers:
            raise McpError(f"no MCP server {name!r}")
        return self._connect(name, servers[name]).describe()


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


__all__ = ["FOLDERS", "McpError", "McpManager", "mcp_server_of", "registry_entry_to_config", "search_registry"]
