from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core.models import ChatCompletionClient
from autogen_core.tools import FunctionTool
from .tools import run_browser_use_task

def create_browser_use_agent(
    model_client: ChatCompletionClient,
    name: str = "browser_use_agent",
) -> AssistantAgent:
    """Create an AssistantAgent that delegates live browsing to the browser-use runtime."""

    tool = FunctionTool(
        run_browser_use_task,
        name="run_browser_use_task",
        description=(
            "Open a browser, perform a live web task, and return a structured result with the final answer and URL. "
            "Use this for current web tasks, browsing, form filling, and research that requires a live browser."
        ),
        strict=True,
    )

    return AssistantAgent(
        name=name,
        model_client=model_client,
        tools=[tool],
        system_message=(
            "You are a browser specialist agent. "
            "Use the browser-use runtime tool for any live web task, page inspection, current-event lookup, or form-filling flow. "
            "Do not claim you can access the web unless you invoke the browser-use tool. "
            "After the tool returns a structured result, do not explain the browser steps. "
            "Pass the result to the summarizer agent so it can provide a clean final answer."
        ),
        reflect_on_tool_use=True,
        max_tool_iterations=3,
    )

def create_browser_use_answerer(
    model_client: ChatCompletionClient,
    name: str = "browser_use_answerer",
) -> AssistantAgent:
    """Summarize the browser-use result into a clean final answer."""
    return AssistantAgent(
        name=name,
        model_client=model_client,
        system_message=(
            "You are the browser result summarizer. "
            "Use the browser-use tool output to answer the user's request in one short, clear sentence or paragraph. "
            "Do not narrate browser actions or logs. "
            "If the browser result contains a final_answer field, use that value. "
            "If it failed, explain the failure briefly and clearly. "
            "End your final response with the exact token FINAL_ANSWER."
        ),
    )

def create_browser_use_team(
    model_client: ChatCompletionClient,
) -> RoundRobinGroupChat:
    """Create a small browser-use team: executor + result formatter."""
    browser_agent = create_browser_use_agent(model_client=model_client)
    answerer = create_browser_use_answerer(model_client=model_client)
    return RoundRobinGroupChat(
        participants=[browser_agent, answerer],
        termination_condition=(
            TextMentionTermination("FINAL_ANSWER") | MaxMessageTermination(6)
        ),
    )