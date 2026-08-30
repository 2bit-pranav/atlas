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

from datetime import datetime, timezone
import shutil

CHAT_DB: Dict[str, Dict[str, Any]] = {}
_THOUGHT_PREFIX = "<|atlas_thought|>"

class ChatService:

    @classmethod
    def get_all_sessions(cls) -> List[Dict[str, Any]]:
        sessions = [
            {
                "id": s["id"],
                "title": s.get("title", "Untitled Chat"),
                "created_at": s.get("created_at", ""),
                "updated_at": s.get("updated_at", ""),
            }
            for s in CHAT_DB.values()
        ]
        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        return sessions

    @classmethod
    def get_session(cls, chat_id: str) -> Optional[Dict[str, Any]]:
        s = CHAT_DB.get(chat_id)
        if not s:
            return None
        return {
            "id": s["id"],
            "title": s.get("title", "Untitled Chat"),
            "created_at": s.get("created_at", ""),
            "updated_at": s.get("updated_at", ""),
            "messages": s.get("messages", []),
        }

    @classmethod
    def delete_session(cls, chat_id: str) -> bool:
        if chat_id in CHAT_DB:
            del CHAT_DB[chat_id]
            uploads_dir = Path(__file__).resolve().parent.parent / "uploads" / chat_id
            if uploads_dir.exists():
                shutil.rmtree(uploads_dir, ignore_errors=True)
            return True
        return False

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
        now_iso = datetime.now(timezone.utc).isoformat()

        session = CHAT_DB.setdefault(active_chat, {
            "id": active_chat,
            "title": "New Chat",
            "created_at": now_iso,
            "updated_at": now_iso,
            "messages": [],
            "agent_state": None,
        })

        clean_prompt = prompt.strip()

        # Derive chat title from first user prompt or attachment name if untitled
        if session.get("title") == "New Chat" or not session.get("messages"):
            if clean_prompt:
                first_line = clean_prompt.split("\n")[0].strip()
                title = first_line[:35] + ("..." if len(first_line) > 35 else "")
            elif attachments:
                first_att = attachments[0]
                fname = first_att.get("name") if isinstance(first_att, dict) else Path(str(first_att)).name
                title = f"File: {fname}"
            else:
                title = "Chat Session"
            session["title"] = title

        # Record User Message
        user_attachment_meta = []
        if attachments:
            for a in attachments:
                fname = a.get("name") if isinstance(a, dict) else Path(str(a)).name
                is_img = any(fname.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)
                user_attachment_meta.append({
                    "name": fname,
                    "type": "image" if is_img else "document",
                })

        user_msg = {
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": clean_prompt,
            "attachments": user_attachment_meta,
        }
        session["messages"].append(user_msg)

        model_client = get_cloud_model() if use_cloud else get_local_model(thinking_budget=thinking_budget)
        atlas = create_atlas_agent(model_client=model_client)

        if session.get("agent_state"):
            await atlas.load_state(session["agent_state"])

        yield {"type": "meta", "chat_id": active_chat}

        task = cls.build_task_payload(prompt, attachments, active_chat)

        accumulated_content = ""
        accumulated_thought = ""
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
                        accumulated_thought += thought_text
                        yield {"type": "thought", "content": thought_text}
                else:
                    accumulated_content += content
                    yield {"type": "chunk", "content": content}

            elif isinstance(message, ThoughtEvent):
                if message.content:
                    accumulated_thought += message.content
                    yield {"type": "thought", "content": message.content}

            elif isinstance(message, TaskResult) and not chunk_yielded:
                for msg in reversed(message.messages):
                    if isinstance(msg, TextMessage) and msg.source != "user":
                        accumulated_content += msg.content
                        yield {"type": "chunk", "content": msg.content}
                        break

        # Record Assistant Message
        assistant_msg = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": accumulated_content,
            "thought": accumulated_thought if accumulated_thought else None,
        }
        session["messages"].append(assistant_msg)
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        session["agent_state"] = await atlas.save_state()