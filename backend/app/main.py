"""FastAPI application entry point."""
from fastapi import FastAPI

app = FastAPI(
    title="Strategic Lead Matrix API",
    description="AI-driven commercial energy lead qualification",
    version="0.1.0",
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Simple liveness probe for Docker and load balancers."""
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint — confirms the API is running."""
    return {"message": "Strategic Lead Matrix API is running"}