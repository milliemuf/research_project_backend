"""
Configuration management for CodeFlow AI.

Loads settings from environment variables with sensible defaults.
"""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "CodeFlow AI"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # API Keys for LLM Providers
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"  # which local model to use; must exist in `ollama list`
    anthropic_model: str = "claude-haiku-4-5-20251001"  # cheap + capable
    openai_model: str = "gpt-4o-mini"  # cheaper than gpt-4 for paper-scale runs

    # Database
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/codeflow"
    redis_url: str = "redis://localhost:6379/0"

    # Neo4j Knowledge Graph
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # PBFT Consensus Configuration
    pbft_fault_tolerance: int = 1  # f value - tolerates f faulty agents
    consensus_timeout_ms: int = 5000  # Timeout for consensus rounds
    min_agents_for_consensus: int = 4  # Minimum 3f+1 for f=1

    # Security
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    @property
    def required_consensus_votes(self) -> int:
        """Calculate required votes for PBFT consensus: 2f + 1"""
        return (2 * self.pbft_fault_tolerance) + 1

    @property
    def min_total_agents(self) -> int:
        """Calculate minimum agents needed: 3f + 1"""
        return (3 * self.pbft_fault_tolerance) + 1


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience access
settings = get_settings()
