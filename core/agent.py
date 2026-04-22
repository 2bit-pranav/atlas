import os
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, AIMessage, trim_messages
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import asyncio
import aiosqlite
import json
from pathlib import Path
from dotenv import load_dotenv

from state import AgentState
from memory import factual, semantic, episodic
from tools.tool_registry import TOOL_GROUPS, ALL_TOOLS

load_dotenv()

ACTIVE_PROVIDER = "gemini" 

def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """Returns the configured LLM instance."""
    if ACTIVE_PROVIDER == "gemini":
        return ChatGoogleGenerativeAI(
            model="gemini-3.1-flash-lite-preview", 
            temperature=temperature
        )
    else:
        return ChatOllama(
            model="gemma4:e2b", 
            temperature=temperature
        )

executor_llm = get_llm()
embeddings = OllamaEmbeddings(model="nomic-embed-text")

def memfetch_node(state: AgentState):
    """Fetches from local FAISS if missing"""
    msg = "[Memory] Searching memory..."
    print(msg)
    user_query = state["messages"][-1].content

    facts = factual.get_profile()
    semantic_context = semantic.search_knowledge(user_query)
    episodic_context = episodic.search_past_experiences(user_query)

    return {
        "logs": [msg] if "logs" not in state else state["logs"] + [msg],
        "factual_memory": facts,
        "semantic_memory": semantic_context,
        "episodic_memory": episodic_context,
        "step_count": 0
    }


def planner_node(state: AgentState):
    """Plans steps and identifies required toolsets"""
    msg = "[Planner] Drafting plan and toolsets..."
    print(msg)
    
    # --- THE FIX: Safe message extraction for Gemini ---
    # This guarantees the list starts with a HumanMessage and doesn't orphan tool calls,
    # preventing the 400 INVALID_ARGUMENT crash from the Gemini API.
    safe_recent_msgs = trim_messages(
        state["messages"],
        max_tokens=1500,
        strategy="last",
        token_counter=executor_llm,
        start_on="human", 
        include_system=False,
        allow_partial=False
    )
    
    facts = state.get("factual_memory", {})

    sys_prompt = f"""
    You are the Strategic Planning Engine for Atlas, an autonomous browser agent.

    FACTUAL MEMORY CURRENTLY AVAILABLE:
    {facts}

    IDENTITY:
    You are the internal planner. You are not the user-facing assistant.
    You do not directly browse, click, scrape, or execute tools.
    You convert user intent into precise operational plans for the execution engine.

    PRIMARY OBJECTIVE:
    Given the user's request and current known context, determine:

    1. What the user truly wants
    2. The safest and fastest next step
    3. Which toolkits are required immediately
    4. What success looks like for this step
    5. What follow-up steps are likely after completion

    You are expected to think like an operations strategist, not a chatbot.

    --------------------------------------------------
    CORE RESPONSIBILITIES
    --------------------------------------------------

    You must:

    - infer intent from vague requests
    - break complex tasks into manageable phases
    - prioritize action over unnecessary conversation
    - minimize wasted tool calls
    - avoid redundant browsing
    - recover momentum when context is incomplete
    - route tasks efficiently

    --------------------------------------------------
    AVAILABLE TOOLKITS
    --------------------------------------------------

    NAV
    Use for:
    - navigating to URLs
    - opening websites
    - performing search engine queries
    - moving to known destinations

    SCROLL
    Use for:
    - moving vertically or horizontally on a page
    - loading lazy content
    - reaching hidden elements

    SCRAPE
    Use for:
    - reading visible text
    - extracting links
    - checking presence of buttons/forms/elements
    - inspecting page state
    - collecting factual data from pages

    MEMORY
    Use for:
    - recalling user facts/preferences/history
    - saving durable information
    - retrieving prior session context

    NONE: CRITICAL. 
    Use this if the user is just chatting, asking a simple question, or asking about their identity (e.g. "What is my name?", "Who am I?") AND the answer is present in the FACTUAL MEMORY.

    --------------------------------------------------
    PLANNING PRINCIPLES
    --------------------------------------------------

    1. Always choose the next best action, not the entire universe.
    2. If browsing is required, route immediately.
    3. If memory likely helps, include MEMORY.
    4. If page state is unknown, prefer NAV or SCRAPE first.
    5. If user gives direct URL, trust it unless obviously malformed.
    6. If task is multi-step, produce phase-aware planning.
    7. Avoid over-planning trivial requests.
    8. Be assertive and capable.

    --------------------------------------------------
    DO NOT DO THESE
    --------------------------------------------------

    NEVER say:
    - I cannot browse
    - I am only an AI
    - I need permission first
    - I apologize
    - I am unable to help

    NEVER ask the user questions unless absolutely necessary.
    NEVER output casual conversation.
    NEVER explain tool limitations.
    NEVER underestimate Atlas capabilities.

    --------------------------------------------------
    WHEN REQUESTS ARE AMBIGUOUS
    --------------------------------------------------

    Infer the most probable helpful interpretation.

    Example:
    "Find me internships"
    => likely requires NAV + SCRAPE

    Example:
    "Remember that I like dark mode"
    => MEMORY

    Example:
    "Go to MIT website"
    => NAV

    --------------------------------------------------
    OUTPUT FORMAT (STRICT)
    --------------------------------------------------
    Return EXACTLY the following two lines and nothing else. Do not add conversational filler before or after.
    Use EXACT UPPERCASE for toolkit names.

    PLAN: <clear concise operational plan for next step>
    TOOLS: <UPPERCASE, comma-separated toolkit names only>
    """

    planner_messages = [SystemMessage(content=sys_prompt)] + safe_recent_msgs + [
        SystemMessage(content="CRITICAL REMINDER: You are the PLANNER. Do NOT converse with the user. You MUST output EXACTLY 'PLAN: <text>\nTOOLS: <categories>' and nothing else.")
    ]

    response_content = executor_llm.invoke(planner_messages).content

    if isinstance(response_content, list):
        plan_raw_text = "".join(
            block["text"] if isinstance(block, dict) and "text" in block else str(block) 
            for block in response_content
        )
    else:
        plan_raw_text = str(response_content)

    plan_text = plan_raw_text
    toolkits = ["MEMORY"]  # always default to memory

    if "TOOLS:" in plan_raw_text:
        parts = plan_raw_text.split("TOOLS:")
        plan_text = parts[0].replace("PLAN:", "").strip()
        tools_str = parts[1].strip()
        toolkits = [t.strip() for t in tools_str.split(",") if t.strip() and t.strip() != "NONE"]

    # Uses .get() to safely pull existing logs and append the new one
    return {
        "plan": plan_text, 
        "active_toolkits": toolkits, 
        "logs": state.get("logs", []) + [msg]
    }

def executor_node(state: AgentState):
    """Executes the plan and calls tools as needed"""
    msg1 = "[Atlas] Evaluating next steps..."
    print(msg1)
    facts = state.get("factual_memory", {})
    plan = state.get("plan", "No active plan.")

    sys_prompt = f"""
    You are the Execution Engine for Atlas, an autonomous browser operations system.

    IDENTITY:
    You are the action layer.
    You control tools that can interact with a real browser, live web content, and memory systems.

    You do not speculate when tools can verify reality.

    --------------------------------------------------
    CURRENT OBJECTIVE FROM PLANNER
    --------------------------------------------------

    {plan}

    --------------------------------------------------
    FACTUAL MEMORY
    --------------------------------------------------

    {facts}

    --------------------------------------------------
    SEMANTIC CONTEXT
    --------------------------------------------------

    {state.get('semantic_memory', 'None')}

    --------------------------------------------------
    PRIMARY RESPONSIBILITIES
    --------------------------------------------------

    You must:

    1. Execute the planner objective efficiently
    2. Use tools decisively
    3. Prefer verification over guessing
    4. Adapt when page state differs from expectation
    5. Recover from errors automatically
    6. Continue progress until objective or blocker is reached

    --------------------------------------------------
    BEHAVIOR RULES
    --------------------------------------------------

    1. If browsing/search/navigation is needed, invoke tools immediately.
    2. If page content is unknown, inspect it.
    3. If a tool fails, retry with a smarter alternative.
    4. If selectors fail, inspect then adapt.
    5. If user asked for information, gather evidence first.
    6. If memory can personalize results, use it.
    7. Minimize unnecessary tool calls.
    8. Stay focused on current objective.

    --------------------------------------------------
    HARD CONSTRAINTS
    --------------------------------------------------

    NEVER say:
    - I do not have internet access
    - I am just an AI model
    - I cannot browse
    - I am unable to perform actions

    NEVER guess CSS selectors, XPaths, or element IDs. If you do not know the exact selector, use SCRAPE to find it first.
    NEVER assume a form submits successfully without verifying the post-submit page state.
    NEVER fabricate search results.
    NEVER invent page contents.
    NEVER claim success without evidence.
    NEVER stop after first obstacle.

    --------------------------------------------------
    DIRECT ANSWER PROTOCOL
    --------------------------------------------------
    If the user asks a conversational question (e.g. "What is my name?") and the answer is explicitly visible in the FACTUAL MEMORY above, DO NOT USE TOOLS. 
    Answer the question directly, conversationally, and confidently. 
    You are fully authorized to state the user's personal details. NEVER say "As an AI, I do not know".

    --------------------------------------------------
    FAILURE RECOVERY MODEL
    --------------------------------------------------

    If a tool fails:

    1. Read the error
    2. Diagnose likely cause
    3. Choose alternate method
    4. Retry intelligently

    --------------------------------------------------
    FORM FILLING STANDARD
    --------------------------------------------------

    When interacting with forms:

    1. Inspect visible fields first
    2. Match labels carefully
    3. Use memory/user context where relevant
    4. Fill accurately
    5. Verify before submit
    6. Submit only when appropriate

    --------------------------------------------------
    PERSONAL DATA RULE
    --------------------------------------------------

    Use supplied factual memory confidently when relevant.
    Do not expose unrelated private memory.
    Use only necessary data.

    --------------------------------------------------
    SUCCESS STANDARD
    --------------------------------------------------

    You should feel like a capable browser operator, not a timid chatbot.

    Take action.
    Use tools.
    Verify outcomes.
    Advance the task.

    --------------------------------------------------
    HANDING BACK CONTROL
    --------------------------------------------------
    When the objective is complete, or if you hit a hard blocker requiring human input, output a final thought summarizing the outcome, stop using tools, and await further instructions.

    """

    full_conversation = [SystemMessage(content=sys_prompt)] + state["messages"]

    trimmed_msgs = trim_messages(
        full_conversation,
        max_tokens=3000,
        strategy="last",
        token_counter=executor_llm, 
        include_system=True, 
        allow_partial=False
    )

    active_tools = []
    requested_kits = state.get("active_toolkits", ["MEMORY"])

    msg2 = f"[Atlas] Loaded Toolkits: {requested_kits}"
    print(msg2)
    
    for kit in requested_kits:
        if kit in TOOL_GROUPS:
            active_tools.extend(TOOL_GROUPS[kit])
            
    if active_tools:
        active_llm = executor_llm.bind_tools(active_tools)
    else:
        active_llm = executor_llm

    response = active_llm.invoke(trimmed_msgs)

    current_steps = state.get("step_count", 0)
    
    logs = state.get("logs", [])
    logs.extend([msg1, msg2])

    return {"messages": [response], "step_count": current_steps + 1, "logs": logs}


def speaker_node(state: AgentState):
    """Node that generates conversational responses"""
    last_msg = state["messages"][-1]
    last_user_msg = next((m for m in reversed(state["messages"]) if m.type == "human"), "")

    if last_msg.tool_calls:
        tool_call = last_msg.tool_calls[0]
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]

        print(f"[Atlas] Calling tool: {tool_name}")

        sys_prompt = f"""
        You are the Voice Interface for Atlas.

        The user said:
        "{last_user_msg}"

        The system is about to execute:
        Tool: {tool_name}
        Arguments: {tool_args}

        --------------------------------------------------
        ROLE
        --------------------------------------------------

        You are the polished user-facing layer.

        Your job is to keep the user informed naturally while backend actions happen.

        You transform internal tool operations into short, confident, human language.

        The user should feel that Atlas is actively working.

        --------------------------------------------------
        STYLE RULES
        --------------------------------------------------

        Your tone must be:

        - calm
        - competent
        - concise
        - conversational
        - confident
        - modern

        Never robotic.
        Never overly cheerful.
        Never verbose.

        --------------------------------------------------
        STRICT CONSTRAINTS
        --------------------------------------------------

        1. Output exactly ONE sentence.
        2. Keep it under 18 words when possible.
        3. No markdown.
        4. No bullet points.
        5. No JSON.
        6. No code syntax.
        7. Never mention tool names.
        8. Never say "executing", "calling function", "invoking tool".
        9. Never say "as an AI".
        10. Never sound confused.
        11. DO NOT wrap your response in quotation marks.
        12. DO NOT use prefatory filler like "Status:" or "System:"

        --------------------------------------------------
        TRANSLATION RULE
        --------------------------------------------------

        Convert internal actions into human language.

        Examples:

        navigate_to_url
        => Opening that page now.

        google_search
        => Let me search that for you.

        scroll_page
        => Scrolling a bit to find the next section.

        scrape_text
        => Checking the page details now.

        memory_lookup
        => Let me pull up what we saved earlier.

        fill_form
        => I'm filling that form now.

        submit_form
        => Submitting it now.

        --------------------------------------------------
        FINAL OUTPUT RULE
        --------------------------------------------------

        Return only the single sentence and nothing else.
        """

        response_content = executor_llm.invoke(sys_prompt).content
        
        if isinstance(response_content, list):
            ui_text = "".join(
                block["text"] if isinstance(block, dict) and "text" in block else str(block) 
                for block in response_content
            )
        else:
            ui_text = str(response_content)
            
        ui_text = ui_text.replace('"', '').strip()
        last_msg.content = ui_text

    return {"messages": [last_msg]}


def memwrite_node(state: AgentState):
    """Runs before END and updates memory"""
    msg1 = "[Memory] Reviewing conversation for updates..."
    print(msg1)
    logs = state.get("logs", [])
    logs.append(msg1)

    # factual write
    last_user_msg = next((m for m in reversed(state["messages"]) if m.type == "human"), None)

    if last_user_msg:
        extraction_prompt = f"""Extract any permanent personal facts the user stated about themselves in this message. 
        Return ONLY a valid JSON object. Do not use markdown formatting.
        Example: {{"name": "Pranav", "location": "Mumbai"}}
        If no facts are present, return {{"None": "None"}}.
        Message: "{last_user_msg.content}"
        """

        try:
            response_content = executor_llm.invoke(extraction_prompt).content

            if isinstance(response_content, list):
                extraction_text = "".join(
                    block["text"] if isinstance(block, dict) and "text" in block else str(block) 
                    for block in response_content
                )
            else:
                extraction_text = str(response_content)

            if "```json" in extraction_text:
                extraction_text = extraction_text.split("```json")[1].split("```")[0].strip()
            elif "```" in extraction_text:
                extraction_text = extraction_text.replace("```", "").strip()

            new_facts = json.loads(extraction_text)

            if "None" not in new_facts:
                factual.update_facts(new_facts)
                print(f"[Memory] Updated factual memory with: {new_facts}")

        except json.JSONDecodeError:
            print(f"[Memory] Failed to parse factual extraction into JSON")
        except Exception as e:
            print(f"[Memory] Error during factual extraction: {e}")

    # episodic write
    if state.get("plan"):
        user_query = state["messages"][0].content
        msg2 = "[Memory] Logged experience in episodic memory"
        print(msg2)
        episodic.log_experience(user_query, state.get("plan", ""))
        logs.append(msg2)

    return {"logs": logs}


def executor_router(state: AgentState):
    last_msg = state["messages"][-1]

    if last_msg.tool_calls:
        return "speaker_node"

    return "memwrite_node"


def guard_router(state: AgentState):
    """Failsafe for infinite loops"""
    # 🚨 FIX: Only read the state here. The counter increments in executor_node.
    if state.get("step_count", 0) >= 5:
        print(f"[Guard] 🛑 Too many steps, triggering emergency brake.")
        return "memwrite_node"

    return "executor_node"


workflow = StateGraph(AgentState)

# define nodes
workflow.add_node("memfetch_node", memfetch_node)
workflow.add_node("planner_node", planner_node)
workflow.add_node("executor_node", executor_node)
workflow.add_node("speaker_node", speaker_node)
workflow.add_node("tools_node", ToolNode(ALL_TOOLS))
workflow.add_node("memwrite_node", memwrite_node)

# core flow
workflow.add_edge(START, "memfetch_node")
workflow.add_edge("memfetch_node", "planner_node")
workflow.add_edge("planner_node", "executor_node")

# executor branch
workflow.add_conditional_edges(
    "executor_node",
    executor_router,
    {
        "speaker_node": "speaker_node",
        "memwrite_node": "memwrite_node",
    },
)

# tool execution loop
workflow.add_edge("speaker_node", "tools_node")
workflow.add_conditional_edges(
    "tools_node",
    guard_router,
    {
        "executor_node": "executor_node",
        "memwrite_node": "memwrite_node",
    },
)

# exit
workflow.add_edge("memwrite_node", END)

_atlas_graph = None
_memory_conn = None
_memory_saver = None
_graph_init_lock = asyncio.Lock()

async def get_atlas_graph():
    global _atlas_graph, _memory_conn, _memory_saver

    if _atlas_graph is not None:
        return _atlas_graph

    async with _graph_init_lock:
        if _atlas_graph is not None:
            return _atlas_graph

        checkpoint_path = Path("checkpoints") / "atlas_memory.db"
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

        if _memory_saver is None:
            _memory_conn = await aiosqlite.connect(str(checkpoint_path))
            _memory_saver = AsyncSqliteSaver(_memory_conn)

        _atlas_graph = workflow.compile(checkpointer=_memory_saver)

    return _atlas_graph