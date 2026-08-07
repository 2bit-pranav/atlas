"""
Atlas Agent Package
Clean Python module exposing modern AutoGen AssistantAgent and tools.
"""

from config import USE_LOCAL_MODEL, LOCAL_MODEL_NAME, CLOUD_MODEL_NAME, get_model_client
from tools import web_search, web_fetch
from agent import AtlasAgent, create_agent

__all__ = [
    "create_agent",
    "AtlasAgent",
    "web_search",
    "web_fetch",
    "get_model_client",
    "USE_LOCAL_MODEL",
    "LOCAL_MODEL_NAME",
    "CLOUD_MODEL_NAME",
]
