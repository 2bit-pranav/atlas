"""Backward-compatible public entrypoint for the unified Atlas runtime."""

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient

from .runtime import create_runtime_agent


def create_atlas_agent(model_client: ChatCompletionClient) -> AssistantAgent:
    return create_runtime_agent(model_client)


create_scoped_agent = create_atlas_agent
