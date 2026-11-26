"""Process-level settings read from environment variables (prefix SMARTROUTE_).

These are deployment facts (database URL, secrets, which detectors are installed).
Anything a superadmin should be able to change at runtime lives in
`app.core.policy_config.PolicyConfig`, stored in the database instead.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET = "dev-only-secret-change-me-before-production-use"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SMARTROUTE_", extra="ignore")

    env: str = "development"  # "development" | "production"
    database_url: str = "sqlite:///./smartroute.db"
    secret_key: str = INSECURE_SECRET  # signs login tokens
    encryption_key: str = ""  # Fernet key that encrypts stored provider API keys
    access_token_minutes: int = 480
    cors_origins: str = "http://localhost:3000"

    bootstrap_admin_email: str = "admin@smartroute.local"
    bootstrap_admin_password: str = ""

    # Local inference
    # 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first, and Ollama
    # listens on IPv4 only, which costs ~2 s per request before the fallback.
    ollama_base_url: str = "http://127.0.0.1:11434"
    local_model: str = "llama3.1:8b"
    seed_mock_models: bool | None = None  # default: on in development, off in production

    # Privacy detectors. Regex patterns are always on. A detector that is enabled here
    # but fails to load or run makes the scan fail, which blocks cloud dispatch.
    pii_presidio: bool = False
    pii_gliner: bool = False
    pii_gliner_model: str = "nvidia/gliner-pii"
    pii_gliner_threshold: float = 0.5
    pii_gliner_device: str = "auto"  # "auto" (GPU when available) | "cuda" | "cpu"
    pii_spacy_model: str = "en_core_web_lg"

    # OCR for photos and scanned PDFs: "off" | "vllm" | "mock" (development only).
    # The vLLM server must run inside the trusted boundary (localhost, private
    # network or a Docker service name); production refuses anything else.
    ocr_backend: str = "off"
    ocr_base_url: str = "http://localhost:8001/v1"
    ocr_model: str = "baidu/Unlimited-OCR"
    ocr_prompt: str = "<image>document parsing."
    ocr_max_tokens: int = 8192
    ocr_timeout_s: float = 300.0
    ocr_max_pages: int = 20  # scanned pages OCR'd per upload

    # Router features
    embeddings_enabled: bool = False
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    artifacts_dir: str = "./artifacts"

    # Limits
    max_upload_mb: int = 10
    max_pages: int = 100
    request_timeout_s: float = 120.0
    rate_limit_rpm: int = 120

    # Claude models that support it re-run a safety-declined request on a fallback model.
    # Turn off for benchmark runs so every answer comes from the model that was routed to.
    anthropic_refusal_fallbacks: bool = True

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def mock_models_enabled(self) -> bool:
        if self.seed_mock_models is None:
            return not self.is_production
        return self.seed_mock_models and not self.is_production

    def validate_for_startup(self) -> None:
        if not self.is_production:
            return
        problems = []
        if self.secret_key == INSECURE_SECRET or len(self.secret_key) < 32:
            problems.append("SMARTROUTE_SECRET_KEY must be set to a random value of at least 32 characters")
        if not self.encryption_key:
            problems.append("SMARTROUTE_ENCRYPTION_KEY must be set (see SETUP.md)")
        if not self.bootstrap_admin_password:
            problems.append("SMARTROUTE_BOOTSTRAP_ADMIN_PASSWORD must be set for the first start")
        if self.database_url.startswith("sqlite"):
            problems.append("SMARTROUTE_DATABASE_URL must point to PostgreSQL in production")
        backend = self.ocr_backend.lower()
        if backend not in ("off", "vllm", "mock"):
            problems.append("SMARTROUTE_OCR_BACKEND must be off, vllm or mock")
        if backend == "mock":
            problems.append("SMARTROUTE_OCR_BACKEND=mock is for development only")
        if backend == "vllm":
            from .core.ocr import is_local_endpoint

            if not is_local_endpoint(self.ocr_base_url):
                problems.append(
                    "SMARTROUTE_OCR_BASE_URL must be on this host or the private network: "
                    "document images may not leave the trusted boundary"
                )
        if problems:
            raise RuntimeError("Refusing to start in production:\n- " + "\n- ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
