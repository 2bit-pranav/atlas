import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Union, Optional
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import (
    ModelClientStreamingChunkEvent,
    MultiModalMessage,
    TextMessage,
    ThoughtEvent,
)
from autogen_core import Image
from agent.agent import create_atlas_agent
from agent.config import get_cloud_model, get_local_model

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
TEXT_EXTENSIONS = {".txt", ".md", ".py", ".json", ".csv", ".log", ".html", ".xml", ".yml", ".yaml", ".js", ".ts"}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
EXCEL_EXTENSIONS = {".xlsx", ".xls"}

CHAT_DB: Dict[str, Dict[str, Any]] = {}
_THOUGHT_PREFIX = "<|atlas_thought|>"

class ChatService:

    @staticmethod
    def validate_path(path: str) -> Optional[Path]:
        if not path or not path.strip():
            return None
        candidate = path.strip().strip('"')
        p = Path(candidate).expanduser().resolve(strict=False)
        return p if p.exists() and p.is_file() else None

    @classmethod
    def extract_file_content(cls, path: Path, display_name: Optional[str] = None) -> Union[str, Image, None]:
        name = display_name or path.name
        suffix = path.suffix.lower()

        # 1. Images
        if suffix in IMAGE_EXTENSIONS:
            try:
                return Image.from_file(str(path))
            except Exception as e:
                return f"[Error loading image {name}: {e}]"

        # 2. UTF-8 Text / Code
        if suffix in TEXT_EXTENSIONS:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                return f"[Attached File: {name}]\n{content}"
            except Exception as e:
                return f"[Error reading text file {name}: {e}]"

        # 3. PDF Documents
        if suffix in PDF_EXTENSIONS:
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                pages = [page.extract_text() or "" for page in reader.pages]
                return f"[Attached PDF: {name}]\n" + "\n".join(pages).strip()
            except Exception as e:
                return f"[Error reading PDF {name}: {e}]"

        # 4. Word Documents (.docx)
        if suffix in DOCX_EXTENSIONS:
            try:
                import docx
                doc = docx.Document(str(path))
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                tables = [
                    " | ".join(c.text.strip() for c in r.cells if c.text.strip())
                    for t in doc.tables for r in t.rows
                ]
                return f"[Attached Word Document: {name}]\n" + "\n".join(paragraphs + tables)
            except Exception as e:
                return f"[Error reading DOCX {name}: {e}]"

        # 5. Excel Spreadsheets (.xlsx, .xls)
        if suffix in EXCEL_EXTENSIONS:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(str(path), data_only=True)
                sheets = []
                for sheet_name in wb.sheetnames:
                    ws = wb[sheet_name]
                    rows = [
                        "\t".join(str(c) if c is not None else "" for c in r)
                        for r in ws.iter_rows(values_only=True)
                        if any(r)
                    ]
                    if rows:
                        sheets.append(f"--- Sheet: {sheet_name} ---\n" + "\n".join(rows))
                return f"[Attached Excel Spreadsheet: {name}]\n" + "\n\n".join(sheets)
            except Exception as e:
                return f"[Error reading Excel {name}: {e}]"

        return f"[Unsupported file type {suffix} for file {name}]"

    @classmethod
    def build_task_payload(
        cls,
        prompt: str,
        attachments: Optional[List[Union[str, Dict[str, str]]]],
        chat_id: str,
    ) -> Union[str, MultiModalMessage]:

        content_items: List[Union[str, Image]] = []
        clean_prompt = prompt.strip()

        if clean_prompt:
            content_items.append(clean_prompt)

        if attachments:
            for item in attachments:
                if isinstance(item, dict):
                    raw_path = item.get("path", "")
                    display_name = item.get("name")
                else:
                    raw_path = str(item)
                    display_name = None

                p = cls.validate_path(raw_path)
                if not p:
                    continue

                fname = display_name or p.name
                extracted = cls.extract_file_content(p, display_name=fname)
                if isinstance(extracted, Image):
                    content_items.append(f"[Attached Image: {fname}]")
                    content_items.append(extracted)
                elif isinstance(extracted, str):
                    content_items.append(extracted)

        if not content_items:
            raise ValueError("Message must include text or a valid attachment.")

        if len(content_items) == 1 and isinstance(content_items[0], str):
            return content_items[0]

        return MultiModalMessage(content=content_items, source="user")

    @classmethod
    async def process_chat(
        cls,
        prompt: str,
        chat_id: Optional[str] = None,
        thinking_budget: int = 0,
        use_cloud: bool = False,
        attachments: Optional[List[Union[str, Dict[str, str]]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:

        active_chat = chat_id or str(uuid.uuid4())

        model_client = get_cloud_model() if use_cloud else get_local_model(thinking_budget=thinking_budget)
        atlas = create_atlas_agent(model_client=model_client)

        session = CHAT_DB.setdefault(active_chat, {})
        if "agent_state" in session:
            await atlas.load_state(session["agent_state"])

        yield {"type": "meta", "chat_id": active_chat}

        task = cls.build_task_payload(prompt, attachments, active_chat)

        chunk_yielded = False
        async for message in atlas.run_stream(task=task):
            if isinstance(message, ModelClientStreamingChunkEvent):
                content = message.content
                if not content:
                    continue
                chunk_yielded = True
                if content.startswith(_THOUGHT_PREFIX):
                    thought_text = content[len(_THOUGHT_PREFIX):]
                    if thought_text:
                        yield {"type": "thought", "content": thought_text}
                else:
                    yield {"type": "chunk", "content": content}

            elif isinstance(message, ThoughtEvent):
                if message.content:
                    yield {"type": "thought", "content": message.content}

            elif isinstance(message, TaskResult) and not chunk_yielded:
                for msg in reversed(message.messages):
                    if isinstance(msg, TextMessage) and msg.source != "user":
                        yield {"type": "chunk", "content": msg.content}
                        break

        session["agent_state"] = await atlas.save_state()