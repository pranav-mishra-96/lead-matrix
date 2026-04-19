"""FastAPI application entry point."""
from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Strategic Lead Matrix API",
    description="AI-driven commercial energy lead qualification",
    version="0.1.0",
    debug=not settings.is_production,
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Simple liveness probe for Docker and load balancers."""
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint — confirms the API is running."""
    return {
        "message": "Strategic Lead Matrix API is running",
        "environment": settings.environment,
        "model": settings.openai_model,
    }