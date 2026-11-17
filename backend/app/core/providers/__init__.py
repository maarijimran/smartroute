"""Vendor presets and the adapter factory.

A vendor names where a model lives (and which key unlocks it); an adapter is the
wire protocol. Several vendors share the OpenAI-compatible adapter, which is why
provider count and adapter count differ.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...config import get_settings
from .base import ChatRequest, ChatResult, CredentialSpec, ModelSpec, Provider, ProviderError

__all__ = [
    "VENDORS",
    "ChatRequest",
    "ChatResult",
    "CredentialSpec",
    "ModelSpec",
    "Provider",
    "ProviderError",
    "build_provider",
    "vendor_needs_key",
]

DEFAULT_AZURE_API_VERSION = "2024-10-21"


@dataclass(frozen=True)
class Vendor:
    label: str
    adapter: str  # "openai_compat" | "azure_openai" | "anthropic" | "ollama" | "mock"
    base_url: str | None = None
    needs_key: bool = True
    needs_base_url: bool = False  # the credential must supply the endpoint
    max_tokens_field: str = "max_tokens"


VENDORS: dict[str, Vendor] = {
    "ollama": Vendor("Ollama (local)", "ollama", needs_key=False),
    "anthropic": Vendor("Anthropic Claude", "anthropic"),
    "openai": Vendor("OpenAI", "openai_compat", "https://api.openai.com/v1", max_tokens_field="max_completion_tokens"),
    "gemini": Vendor("Google Gemini", "openai_compat", "https://generativelanguage.googleapis.com/v1beta/openai"),
    "azure_openai": Vendor(
        "Azure OpenAI", "azure_openai", needs_base_url=True, max_tokens_field="max_completion_tokens"
    ),
    "openrouter": Vendor("OpenRouter", "openai_compat", "https://openrouter.ai/api/v1"),
    "groq": Vendor("Groq", "openai_compat", "https://api.groq.com/openai/v1"),
    "deepseek": Vendor("DeepSeek", "openai_compat", "https://api.deepseek.com/v1"),
    "together": Vendor("Together AI", "openai_compat", "https://api.together.xyz/v1"),
    "openai_compatible": Vendor("Other OpenAI-compatible endpoint", "openai_compat", needs_base_url=True),
    "mock": Vendor("Mock (no model, development only)", "mock", needs_key=False),
}


def vendor_needs_key(vendor: str) -> bool:
    return VENDORS[vendor].needs_key


def build_provider(spec: ModelSpec, cred: CredentialSpec | None) -> Provider:
    settings = get_settings()
    vendor = VENDORS.get(spec.vendor)
    if vendor is None:
        raise ProviderError(f"unknown vendor '{spec.vendor}'")
    timeout = settings.request_timeout_s

    if vendor.adapter == "mock":
        if settings.is_production:
            raise ProviderError("mock models are disabled in production")
        from .mock import MockProvider

        return MockProvider(is_local=spec.is_local)

    if vendor.adapter == "ollama":
        from .http_adapters import OllamaProvider

        return OllamaProvider(spec.base_url or settings.ollama_base_url, timeout)

    if cred is None:
        raise ProviderError(f"no API key available for vendor '{spec.vendor}'")
    base_url = spec.base_url or cred.base_url or vendor.base_url

    if vendor.adapter == "anthropic":
        from .anthropic_adapter import AnthropicProvider

        return AnthropicProvider(cred.api_key, timeout, base_url, settings.anthropic_refusal_fallbacks)

    if not base_url:
        raise ProviderError(f"vendor '{spec.vendor}' needs an endpoint URL on the credential or the model")

    if vendor.adapter == "azure_openai":
        from .http_adapters import AzureOpenAIProvider

        return AzureOpenAIProvider(
            base_url, cred.api_key, cred.api_version or DEFAULT_AZURE_API_VERSION, timeout, vendor.max_tokens_field
        )

    from .http_adapters import OpenAICompatProvider

    return OpenAICompatProvider(base_url, cred.api_key, timeout, vendor.max_tokens_field)
