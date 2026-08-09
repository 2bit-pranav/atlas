"""
Atlas Agent Package
Clean Python module exposing modern AutoGen AssistantAgent and tools.
"""

from config import (
    get_local_model,
    get_cloud_model,
)
from agent import (
    AtlasAgent,
)
from tools import web_search, web_fetch, write_file

__all__ = [
    "AtlasAgent",
    "get_local_model",
    "get_cloud_model",
    "web_search",
    "web_fetch",
    "write_file",
]
