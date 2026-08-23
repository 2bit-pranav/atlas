"""
Atlas Agent Package
"""

from .config import get_local_model, get_cloud_model
from .web_agent.tools import web_search, web_fetch
from .file_agent.tools import read_file, write_file, verify_operation

__all__ = [
    "get_local_model",
    "get_cloud_model",
    "web_search",
    "web_fetch",
    "read_file",
    "write_file",
    "verify_operation",
]