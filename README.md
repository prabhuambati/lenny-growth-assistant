# The Lenny Growth Assistant

A grounded conversational assistant over Lenny's Podcast transcripts — ask product/growth questions, get cited answers, turn them into Ship 30/30-style essays, and view generated Markdown/HTML artifacts in an in-app viewer.

See also: [`PRD.md`](./PRD.md) (product rationale), [`architecture.md`](./architecture.md) (technical design), [`design.md`](./design.md) (UI/UX), [`deploy/DEPLOY_NOTES.md`](./deploy/DEPLOY_NOTES.md) (deployment detail).

## 1. Architecture Overview

```
Frontend (React/Vite, nginx in prod)
        │  REST (/api → proxied to backend)
        ▼
FastAPI backend  ──►  Agent layer (retrieval, Ship 30/30 skill, artifact generation)
        │                       │
        ▼                       ▼
PostgreSQL (sessions,    LLM Client (Ollama default; Anthropic/OpenAI optional,
messages, artifacts,     behind a config toggle with automatic fallback to Ollama)
transcript_chunks +
pgvector embeddings)
        ▲
        │
Ingestion script (offline) ── clones ChatPRD/lennys-podcast-transcripts,
                                chunks + embeds transcripts, upserts to Postgres
```

Full detail in `architecture.md` (schema, API contracts, security model, deployment topology).

## 2. Prerequisites

- Docker + Docker Compose (v2)
- [Ollama](https://ollama.com/) installed and running **on your host machine** (not in Docker — see rationale in `deploy/DEPLOY_NOTES.md`)
- Python 3.11+ (only needed to run the ingestion script locally, outside the containers)
- ~4GB free disk for a small Ollama model + Python ML dependencies

## 3. Repository Structure

```
.
├── backend/                # FastAPI app, Dockerfile, requirements.txt, .env.example
├── frontend/                # React (Vite) app, Dockerfile, nginx.conf
├── deploy/
│   ├── db-init/              # SQL run on first Postgres startup (enables pgvector)
│   └── DEPLOY_NOTES.md
├── ingest.py                 # Transcript ingestion script (run outside Docker)
├── requirements-ingest.txt
├── docker-compose.yml
├── PRD.md
├── architecture.md
├── design.md
├── tests/                    # Automated and manual smoke-test plans
└── README.md
```

## 4. Environment Variables

Copy the template and fill in what you need:
```bash
cp backend/.env.example backend/.env
```

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | Overridden automatically by Docker Compose to point at the `db` service; only matters if running the backend outside Docker. |
| `MODEL_PROVIDER` | Yes | `ollama` | `ollama` \| `anthropic` \| `openai` \| `gemini`. |
| `OLLAMA_HOST` | Yes (for local path) | `http://localhost:11434` | Overridden to `http://host.docker.internal:11434` inside Docker Compose. |
| `OLLAMA_MODEL` | Yes | `llama3.1:8b` | Must be `ollama pull`-ed on the host first. |
| `ANTHROPIC_API_KEY` | No | empty | Only needed if you switch `MODEL_PROVIDER` to `anthropic`. |
| `OPENAI_API_KEY` | No | empty | Only needed if you switch `MODEL_PROVIDER` to `openai`. |
| `GEMINI_API_KEY` | No | empty | Optional Google Gemini key for `gemini-2.5-flash`; no billing is required by this project. |
| `CORS_ORIGINS` | No | localhost frontend origins | Comma-separated browser origins allowed to call the API. |
| `RETRIEVAL_TOP_K` | No | `5` | Chunks retrieved per query. |
| `RETRIEVAL_MIN_SIMILARITY` | No | `0.25` | Below this, the assistant returns "insufficient evidence" instead of guessing. |
| `NORMAL_CHAT_GENERATION_TIMEOUT_SECONDS` | No | `300` | Ollama normal-chat timeout; normal chat uses `num_ctx=4096` and `num_predict=256`. Ship 30/30 uses its separate timeout/settings. |

**No secrets are committed.** `.env` is gitignored; only `.env.example` (with non-secret defaults) is tracked.

## 5. Local Model Setup (Mandatory Path)

```bash
# Install Ollama: https://ollama.com/download
ollama serve                 # starts the Ollama server on :11434
ollama pull llama3.1:8b      # or any model that runs comfortably on your machine
```
Confirm it's reachable: `curl http://localhost:11434/api/tags`

## 6. Cloud Model Setup (Optional)

Set `MODEL_PROVIDER=gemini` and `GEMINI_API_KEY` in `backend/.env` to opt into Google Gemini (`gemini-2.5-flash`). Anthropic and OpenAI remain optional adapters. Providers can be switched at runtime from the UI or via `PUT /config/model`; missing Gemini credentials or exhausted free quota returns a structured provider error while Ollama remains available.

Ollama with Llama 3.1 8B is the mandatory local demo path and needs no cloud key. Ship 30/30 requests use the dedicated grounded skill, validate the essay, and persist it as a Markdown artifact. The Artifact Viewer renders Markdown without raw HTML passthrough and isolates HTML in an iframe with `sandbox="allow-scripts"` only.

## 7. Run Commands

### One-command startup (recommended)
```bash
docker compose up --build
```
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000 (`/health` for status)
- Postgres: localhost:5432 (user/pass: `postgres`/`postgres`, db: `lenny_assistant`)

### Ingest transcripts (run once, before your first real query)
The ingestion script talks directly to Postgres and runs outside the containers:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-ingest.txt
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/lenny_assistant
python ingest.py --repo-dir ./data/lennys-podcast-transcripts --limit 30   # drop --limit for the full corpus
```
Re-running this is safe — it upserts by `(episode_id, chunk_index)`, so nothing is duplicated.

### Run the backend without Docker (for development)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/lenny_assistant
uvicorn app.main:app --reload
```

### Run the frontend without Docker (for development)
```bash
cd frontend
npm install
npm run dev   # http://localhost:5173, proxies /api to http://localhost:8000
```

## 8. Tests

```bash
cd backend
pip install -r requirements.txt
pytest
```
See `tests/` for automated coverage (API contracts, retrieval, routing, persistence) and `tests/manual_test_plan.md` for the UI walkthrough.

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/health` returns `"ollama": false` | Ollama isn't running, or Docker can't reach the host | Run `ollama serve` on the host; on Linux confirm `host.docker.internal` resolves (compose sets this via `extra_hosts`). |
| Chat replies with "insufficient evidence" for everything | Ingestion hasn't run, or `transcript_chunks` is empty | Run the ingestion script (§7); check row count with `SELECT count(*) FROM transcript_chunks;`. |
| `docker compose up` fails on `db` with a missing `vector` type | pgvector init script didn't run (only runs on a fresh volume) | `docker compose down -v` then `up --build` again, or manually run `CREATE EXTENSION IF NOT EXISTS vector;`. |
| `PROVIDER_UNAVAILABLE` error when using cloud provider | Missing/invalid API key | Check `backend/.env`; the system will auto-fall back to Ollama, so also confirm Ollama is reachable. |
| Frontend loads but chat requests fail | Backend not up yet, or `/api` proxy misconfigured | Check `docker compose logs api`; confirm `/health` responds directly on :8000. |
| Ingestion script fails to clone the repo | No network access, or repo URL changed | Manually `git clone https://github.com/ChatPRD/lennys-podcast-transcripts.git` into the `--repo-dir` path and rerun with `--skip-clone`. |

## 10. Known Limitations / Scope Notes

See `PRD.md` §4 for the full, explicit scope-in/scope-out list. Headline items: single-user (no auth), a representative transcript subset by default (full corpus is a config change, not an architecture change), and cloud provider paths are lighter-tested than the mandatory local Ollama path.
