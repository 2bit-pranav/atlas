import asyncio
import os
from pathlib import Path
from agent.file_agent.agent import file_agent
from autogen_agentchat.ui import Console

async def test_file_agent_task():
    test_file = Path("test/sample_lines.txt")
    test_file.write_text("Line A\nLine B\nLine C\nLine D\nLine E\n", encoding="utf-8")

    print(f"Created {test_file} with initial 5 lines.")

    task_prompt = (
        f"Read {test_file}, count how many lines are currently in the file, "
        f"and append a final line stating: 'Total lines: <count>'."
    )

    print(f"\n--- Running file_agent with prompt: '{task_prompt}' ---\n")
    
    # Run stream to see conversation steps
    await Console(file_agent.run_stream(task=task_prompt))

    final_content = test_file.read_text(encoding="utf-8")
    print(f"\n--- Final File Content of {test_file} ---")
    print(final_content)
    print("------------------------------------------")

if __name__ == "__main__":
    asyncio.run(test_file_agent_task())
