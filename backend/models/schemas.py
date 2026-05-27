from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum


class ModeEnum(str, Enum):
    original = "original"
    summary = "summary"


class GranularityEnum(str, Enum):
    brief = "brief"
    standard = "standard"
    detailed = "detailed"


class LlmSourceEnum(str, Enum):
    local = "local"
    api = "api"


class WhisperModelEnum(str, Enum):
    tiny = "tiny"
    base = "base"
    medium = "medium"


class ProcessRequest(BaseModel):
    url: str = Field(..., description="视频链接")
    mode: ModeEnum = Field(..., description="original 或 summary")
    granularity: GranularityEnum = Field(default=GranularityEnum.standard, description="总结粒度")
    llm_source: LlmSourceEnum = Field(default=LlmSourceEnum.local, description="LLM来源")
    whisper_model: WhisperModelEnum = Field(default=WhisperModelEnum.base, description="Whisper模型")


class ProcessResponse(BaseModel):
    task_id: str
    status: str = "queued"


class HistoryItem(BaseModel):
    id: str
    title: str
    url: str
    platform: str
    mode: str
    granularity: Optional[str] = None
    llm_source: Optional[str] = None
    created_at: str
    filename: str


class HistoryList(BaseModel):
    items: list[HistoryItem]


class ErrorResponse(BaseModel):
    detail: str
