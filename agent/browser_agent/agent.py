from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient
from autogen_core.tools import FunctionTool
from .tools import run_browser_use_task

def create_browser_agent(
    model_client: ChatCompletionClient,
    name: str = "BrowserAgent",
) -> AssistantAgent:
    """Create an AssistantAgent that delegates live browsing to the browser-use runtime."""

    tool = FunctionTool(
        run_browser_use_task,
        name="run_browser_use_task",
        description=(
            "Open a live web browser, perform interactive web tasks, search booking portals (e.g. IRCTC), "
            "navigate pages, fill forms, and return structured answers. "
            "Use this for interactive web automation and live browser navigation."
        ),
        strict=True,
    )

    return AssistantAgent(
        name=name,
        model_client=model_client,
        tools=[tool],
        system_message=(
            "You are BrowserAgent, a specialized browser automation specialist. "
            "Invoke run_browser_use_task for browser actions. The browser opens as an external headed application and remains open after the task finishes. Do not simulate browser actions. "
            "Do not simulate browser actions without calling run_browser_use_task. "
            "Once the tool returns the result, return the final_answer and relevant details back to Atlas."
        ),
        reflect_on_tool_use=False,
        max_tool_iterations=2,
    )

def create_browser_use_agent(
    model_client: ChatCompletionClient,
    name: str = "BrowserAgent",
) -> AssistantAgent:
    return create_browser_agent(model_client, name=name)