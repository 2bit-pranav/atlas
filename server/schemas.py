"""Request bodies of the API, as Pydantic models."""


from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateChat(BaseModel):
    title: str = ""
    #: `web`, or `extension` for a chat started in the browser side panel.
    source: str = "web"
    page_url: str = ""
    page_title: str = ""


class Page(BaseModel):
    """The tab a side-panel message is about. Its presence turns on the page tools."""

    url: str = ""
    title: str = ""


class RenameChat(BaseModel):
    title: str


class SendMessage(BaseModel):
    text: str = ""
    files: list[dict[str, Any]] = Field(default_factory=list)
    #: Quoted passages {"file", "path", "quote"}: the former preview panel made them; older turns keep them.
    refs: list[dict[str, Any]] = Field(default_factory=list)
    thinking: bool | None = None
    page: Page | None = None


class RetryTurn(BaseModel):
    thinking: bool | None = None
    page: Page | None = None


class EditTurn(BaseModel):
    text: str
    files: list[dict[str, Any]] | None = None
    refs: list[dict[str, Any]] | None = None
    thinking: bool | None = None
    page: Page | None = None


class SelectTurn(BaseModel):
    delta: int = 0


class Answer(BaseModel):
    allow: bool
    scope: Literal["once", "chat"] = "once"


class ProfileBody(BaseModel):
    text: str


class FillBody(BaseModel):
    #: [{id, label, type, options?, required?}]; never the fields' contents.
    fields: list[dict[str, Any]]
    title: str = ""


class ImportFile(BaseModel):
    url: str


class TableBody(BaseModel):
    rows: list[list[str]]
    title: str = ""
    url: str = ""
    format: str = "xlsx"
    #: Where to save; the extension's setting. Default: Downloads/Atlas.
    folder: str = ""


class CallResult(BaseModel):
    """What the client did for a client call: anything, or `error`."""

    model_config = {"extra": "allow"}


__all__ = ["Answer", "CallResult", "CreateChat", "EditTurn", "FillBody", "ImportFile", "Page", "ProfileBody", "RenameChat", "RetryTurn", "SelectTurn", "SendMessage", "TableBody"]
