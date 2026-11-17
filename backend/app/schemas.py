"""Request and response bodies for the REST API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PrivacyMode = Literal["local_only", "cloud_allowed"]
Role = Literal["superadmin", "admin", "user"]
Tier = Literal["local", "cheap", "strong"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth and users
class LoginIn(BaseModel):
    email: str
    password: str


class RegisterIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = ""
    password: str = Field(min_length=8)


class UserOut(ORM):
    id: str
    email: str
    name: str
    role: str
    is_active: bool
    allow_confidential_cloud: bool | None
    monthly_budget_usd: float | None
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreate(RegisterIn):
    role: Role = "user"


class UserUpdate(BaseModel):
    name: str | None = None
    password: str | None = Field(None, min_length=8)
    is_active: bool | None = None
    monthly_budget_usd: float | None = None
    clear_budget: bool = False
    # Superadmin only:
    role: Role | None = None
    allow_confidential_cloud: bool | None = None
    inherit_confidential_default: bool = False


# ---- model registry
class ModelIn(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,62}$")
    display_name: str = ""
    vendor: str
    model_id: str
    tier: Tier
    is_local: bool = False
    base_url: str | None = None
    context_window: int = Field(8192, ge=256)
    max_output_tokens: int = Field(2048, ge=16)
    price_in_per_mtok: float = Field(0.0, ge=0)
    price_out_per_mtok: float = Field(0.0, ge=0)
    params: dict = Field(default_factory=dict)
    enabled: bool = True


class ModelUpdate(BaseModel):
    display_name: str | None = None
    model_id: str | None = None
    tier: Tier | None = None
    base_url: str | None = None
    context_window: int | None = Field(None, ge=256)
    max_output_tokens: int | None = Field(None, ge=16)
    price_in_per_mtok: float | None = Field(None, ge=0)
    price_out_per_mtok: float | None = Field(None, ge=0)
    params: dict | None = None
    enabled: bool | None = None


class ModelOut(ORM):
    id: str
    name: str
    display_name: str
    vendor: str
    model_id: str
    tier: str
    is_local: bool
    base_url: str | None
    context_window: int
    max_output_tokens: int
    price_in_per_mtok: float
    price_out_per_mtok: float
    price_updated_at: datetime
    params: dict
    enabled: bool
    latency_ewma_ms: float
    unhealthy_until: datetime | None
    last_error: str | None


# ---- credentials and API keys
class CredentialIn(BaseModel):
    vendor: str
    label: str = ""
    api_key: str = Field(min_length=4)
    base_url: str | None = None
    api_version: str | None = None
    platform: bool = False  # superadmin only: shared key for the organisation


class CredentialOut(ORM):
    id: str
    user_id: str | None
    vendor: str
    label: str
    base_url: str | None
    api_version: str | None
    key_hint: str
    created_at: datetime


class ApiKeyIn(BaseModel):
    name: str = ""
    default_privacy_mode: PrivacyMode = "cloud_allowed"


class ApiKeyOut(ORM):
    id: str
    name: str
    prefix: str
    default_privacy_mode: str
    revoked: bool
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str  # shown exactly once


# ---- documents and chat
class DocumentOut(ORM):
    id: str
    filename: str
    label: str
    pages: int
    n_chunks: int
    ocr_pages: int = 0
    created_at: datetime


class SessionIn(BaseModel):
    title: str = "New chat"
    privacy_mode: PrivacyMode = "cloud_allowed"
    document_ids: list[str] = Field(default_factory=list)
    persist: bool = False


class SessionUpdate(BaseModel):
    title: str | None = None
    privacy_mode: PrivacyMode | None = None
    document_ids: list[str] | None = None
    persist: bool | None = None


class SessionOut(ORM):
    id: str
    title: str
    privacy_mode: str
    document_ids: list
    confidential: bool
    persist: bool
    created_at: datetime
    last_active_at: datetime


class MessageOut(ORM):
    id: str
    role: str
    content: str
    event_id: str | None
    meta: dict
    created_at: datetime


class ChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)
    consent: bool = False
    confidential: bool = False  # the user marks this message confidential
    model: str | None = None  # pin a registry model


class FeedbackIn(BaseModel):
    event_id: str
    correctness: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    usefulness: int = Field(ge=1, le=5)
    comment: str = ""


# ---- OpenAI-compatible router API
class OAIMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: str | list | None = None


class SmartRouteOptions(BaseModel):
    """Optional `smartroute` object in the request body."""

    privacy_mode: PrivacyMode | None = None
    consent: bool = False
    confidential: bool = False
    task: Literal["doc_qa", "summary", "explain", "chat"] | None = None
    cache: bool = True


class OAIChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "smartroute/auto"
    messages: list[OAIMessage] = Field(min_length=1)
    stream: bool = False
    max_tokens: int | None = Field(None, ge=1)
    max_completion_tokens: int | None = Field(None, ge=1)
    temperature: float | None = None
    smartroute: SmartRouteOptions | None = None
