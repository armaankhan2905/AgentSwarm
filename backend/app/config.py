"""Validated server configuration. Credentials never belong in API responses."""

from functools import lru_cache
from ipaddress import ip_address
import base64
import binascii
import json
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        address = ip_address(host)
        return address.is_loopback or bool(
            getattr(address, "ipv4_mapped", None)
            and address.ipv4_mapped.is_loopback
        )
    except ValueError:
        return False


def validate_http_url(value: str, *, https_only: bool = False) -> str:
    parsed = urlsplit(value)
    schemes = {"https"} if https_only else {"http", "https"}
    if (
        parsed.scheme not in schemes
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Expected an HTTP(S) URL without credentials, query, or fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL port") from exc
    return value.rstrip("/")


def is_service_role_key(value: str) -> bool:
    """Detect the standard Supabase service-role JWT without verifying it."""
    try:
        payload = value.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        body = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        return body.get("role") == "service_role"
    except (IndexError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    database_url: str = "sqlite:///./agentswarm.db"
    auth_mode: str = "local"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080"
    llm_provider: str = "openai"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    tavily_api_key: str = ""
    openalex_api_key: str = ""
    openalex_email: str = ""
    max_concurrent_sessions: int = Field(default=2, ge=1, le=16)
    max_queued_sessions: int = Field(default=100, ge=1, le=1000)
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    max_pdf_pages: int = Field(default=200, ge=1, le=2000)
    max_document_chars: int = Field(default=2_000_000, ge=1000, le=10_000_000)
    max_documents_per_user: int = Field(default=100, ge=1, le=1000)
    max_document_bytes_per_user: int = Field(default=500 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024 * 1024)
    max_document_chars_per_user: int = Field(default=50_000_000, ge=1000, le=1_000_000_000)
    max_selected_document_chars: int = Field(default=8_000_000, ge=1000, le=100_000_000)
    max_active_sessions_per_user: int = Field(default=5, ge=1, le=100)
    max_total_sessions_per_user: int = Field(default=500, ge=1, le=10000)
    max_history_items: int = Field(default=100, ge=1, le=500)
    max_pdf_concurrency: int = Field(default=2, ge=1, le=8)
    connectivity_cooldown_seconds: float = Field(default=60, ge=1, le=3600)
    request_body_timeout_seconds: float = Field(default=60, ge=5, le=600)
    max_json_bytes: int = Field(default=128 * 1024, ge=1024, le=1024 * 1024)
    connectivity_timeout_seconds: float = Field(default=15, ge=1, le=60)

    @field_validator("auth_mode")
    @classmethod
    def auth_mode_valid(cls, value: str) -> str:
        if value not in {"local", "supabase"}:
            raise ValueError("AUTH_MODE must be local or supabase")
        return value

    @field_validator("database_url")
    @classmethod
    def database_valid(cls, value: str) -> str:
        if value.startswith("postgres://"):
            value = "postgresql+psycopg://" + value[len("postgres://"):]
        elif value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://"):]
        if not value.startswith(("sqlite:///", "postgresql+psycopg://")):
            raise ValueError("DATABASE_URL must use SQLite or PostgreSQL (psycopg)")
        return value

    @field_validator("llm_base_url")
    @classmethod
    def llm_url_valid(cls, value: str) -> str:
        if not value:
            return value
        validated = validate_http_url(value)
        parsed = urlsplit(validated)
        if parsed.scheme == "http" and not is_loopback(parsed.hostname):
            raise ValueError("LLM_BASE_URL must use HTTPS unless it targets a loopback development service")
        return validated

    @field_validator("llm_provider")
    @classmethod
    def provider_valid(cls, value: str) -> str:
        value = value.lower()
        if value not in {"openai", "openai-compatible", "gemini"}:
            raise ValueError("LLM_PROVIDER must be openai, openai-compatible, or gemini")
        return value

    @field_validator("supabase_url")
    @classmethod
    def supabase_url_valid(cls, value: str) -> str:
        return validate_http_url(value, https_only=True) if value else value

    @field_validator("cors_origins")
    @classmethod
    def cors_valid(cls, value: str) -> str:
        for origin in filter(None, (part.strip() for part in value.split(","))):
            validated = validate_http_url(origin)
            if urlsplit(validated).path not in {"", "/"}:
                raise ValueError("CORS_ORIGINS must contain origins, not paths")
        return value

    @model_validator(mode="after")
    def validate_server(self) -> "Settings":
        if not self.llm_model:
            self.llm_model = "gemini-2.5-flash" if self.llm_provider == "gemini" else "gpt-4o-mini"
        if not self.llm_base_url:
            self.llm_base_url = "https://generativelanguage.googleapis.com/v1beta" if self.llm_provider == "gemini" else "https://api.openai.com/v1"
        if self.auth_mode == "supabase" and not (self.supabase_url and self.supabase_anon_key):
            raise ValueError("Supabase authentication requires SUPABASE_URL and SUPABASE_ANON_KEY")
        if self.auth_mode == "supabase" and is_service_role_key(self.supabase_anon_key):
            raise ValueError("SUPABASE_ANON_KEY must be the public anon key, never a service_role key")
        if self.auth_mode == "supabase" and any(
            urlsplit(origin).scheme != "https" and not is_loopback(urlsplit(origin).hostname)
            for origin in self.origins
        ):
            raise ValueError("Supabase deployments require HTTPS CORS origins outside loopback development")
        if self.auth_mode == "local":
            if any(not is_loopback(urlsplit(origin).hostname) for origin in self.origins):
                raise ValueError("Local single-user mode only permits loopback CORS origins")
        return self

    @property
    def origins(self) -> list[str]:
        return [item.strip().rstrip("/") for item in self.cors_origins.split(",") if item.strip()]

    def missing_credentials(self, source_types: list[str]) -> list[str]:
        missing = []
        if not self.llm_api_key.strip():
            missing.append("LLM_API_KEY")
        if "web" in source_types and not self.tavily_api_key.strip():
            missing.append("TAVILY_API_KEY")
        return missing

    def public_status(self) -> dict:
        return {
            "auth_mode": self.auth_mode,
            "integrations": {
                "llm": {"provider": self.llm_provider, "model": self.llm_model, "configured": bool(self.llm_api_key)},
                "tavily": {"configured": bool(self.tavily_api_key)},
                "openalex": {"configured": True, "api_key_configured": bool(self.openalex_api_key), "email_configured": bool(self.openalex_email)},
                "supabase": {"configured": bool(self.supabase_url and self.supabase_anon_key)},
            },
            "limits": {
                "max_concurrent_sessions": self.max_concurrent_sessions,
                "max_queued_sessions": self.max_queued_sessions,
                "max_upload_bytes": self.max_upload_bytes,
                "max_pdf_pages": self.max_pdf_pages,
                "max_document_chars": self.max_document_chars,
                "max_documents_per_user": self.max_documents_per_user,
                "max_document_bytes_per_user": self.max_document_bytes_per_user,
                "max_document_chars_per_user": self.max_document_chars_per_user,
                "max_selected_document_chars": self.max_selected_document_chars,
                "max_active_sessions_per_user": self.max_active_sessions_per_user,
                "max_total_sessions_per_user": self.max_total_sessions_per_user,
                "max_history_items": self.max_history_items,
            },
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
