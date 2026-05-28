"""
Application configuration using Pydantic Settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "System Health Check API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Deployment environment — attached to OTel resource attributes
    ENVIRONMENT: str = "development"

    # Health check defaults
    HEALTH_CHECK_TIMEOUT_SECONDS: float = 10.0
    HEALTH_CHECK_MAX_CONCURRENCY: int = 20

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # "json" or "text"

    # OTEL tracing
    # Set OTEL_ENABLED=true to activate tracing. Requires an OTLP-compatible
    # backend (Jaeger, Grafana Tempo, OTel Collector) at OTEL_EXPORTER_OTLP_ENDPOINT.
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_SERVICE_NAME: str = "system-health-api"

    # Pydantic v2 config — replaces the deprecated inner class Config
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()
