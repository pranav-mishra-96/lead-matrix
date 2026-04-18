# Strategic Lead Matrix

An autonomous AI agent that qualifies commercial energy leads through natural dialogue.

Built as a full-stack Proof of Concept with FastAPI (Python) and React (TypeScript),
orchestrated by LangGraph for reliable multi-variable conversation management.

## Status

🚧 Work in progress — under active development.

## Architecture

- **Backend:** FastAPI + LangGraph + OpenAI (GPT-4o-mini)
- **Frontend:** React + TypeScript + Vite
- **Database:** PostgreSQL 16
- **Cache / Session:** Redis 7
- **Orchestration:** Docker Compose

## Quick Start

```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
docker compose up --build
```

Then open http://localhost:5173 in your browser.

## Documentation

- Architecture decisions — see `docs/architecture.md` *(coming soon)*
- API reference — see http://localhost:8000/docs when running
- Evaluation suite — see `backend/tests/eval/` *(coming soon)*