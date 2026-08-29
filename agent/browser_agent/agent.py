from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core.models import ChatCompletionClient
from autogen_ext.agents.web_surfer import MultimodalWebSurfer


def create_browser_agent(
    model_client: ChatCompletionClient,
    name: str = "browser_agent",
    headless: bool = True,
) -> MultimodalWebSurfer:
    """Create a dedicated AutoGen-native browser specialist."""
    return MultimodalWebSurfer(
        name=name,
        model_client=model_client,
        headless=headless,
        animate_actions=False,
        to_save_screenshots=False,
        use_ocr=False,
        to_resize_viewport=True,
    )


def create_browser_answerer(model_client: ChatCompletionClient, name: str = "browser_answerer") -> AssistantAgent:
    """Summarize page observations into a clean final answer."""
    return AssistantAgent(
        name=name,
        model_client=model_client,
        system_message=(
            "You are the browser answer summarizer. "
            "Use the latest browser observation to answer the user's request in one concise sentence or short paragraph. "
            "Do not describe the tool steps. "
            "Do not include internal reasoning. "
            "End your final response with the exact token FINAL_ANSWER."
        ),
    )


def create_browser_team(
    model_client: ChatCompletionClient,
    headless: bool = True,
) -> RoundRobinGroupChat:
    """Create a small browser specialist team: the surfer acts, the summarizer answers."""
    surfer = create_browser_agent(model_client=model_client, headless=headless)
    answerer = create_browser_answerer(model_client=model_client)
    team = RoundRobinGroupChat(
        participants=[surfer, answerer],
        termination_condition=(
            TextMentionTermination("FINAL_ANSWER") | MaxMessageTermination(6)
        ),
    )
    return team
