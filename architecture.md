# Architecture: The Lenny Growth Assistant

This document describes the technical architecture: database schema, API contracts, component boundaries, ingestion/retrieval flow, agent routing, the model toggle, security, and deployment topology. See `PRD.md` for product rationale and `design.md` for UI/UX.

## 1. System Overview

```
                         ┌────────────────────────────┐
                         │        Frontend (React)     │
                         │  Chat Pane │ Artifact Viewer │
                         └──────────────┬──────────────┘
                                        │ REST / SSE
                         ┌──────────────▼──────────────┐
                         │        FastAPI Backend       │
                         │  routes: /chat /sessions      │
                         │  /artifacts /health /config    │
                         └───────┬───────────┬──────────┘
                                 │           │
                    ┌────────────▼───┐   ┌───▼─────────────┐
                    │   Agent Layer   │   │  LLM Client      │
                    │ (Claude Agent   │   │  Interface        │
                    │  SDK) - routes  │   │ ┌───────────────┐ │
                    │  to tools:      │◄──┤ │ OllamaClient  │ │
                    │ - retrieve      │   │ │ (default)     │ │
                    │ - ship30_essay  │   │ ├───────────────┤ │
                    │ - gen_artifact  │   │ │ AnthropicClient│ │
                    └───────┬─────────┘   │ │ OpenAI / Gemini │ │
                            │             │ └───────────────┘ │
                            │             └────────────────────┘
                  ┌─────────▼─────────────────────────┐
                  │           PostgreSQL                │
                  │  sessions | messages | artifacts     │
                  │  transcript_chunks (+ pgvector col)  │
                  └─────────▲─────────────────────────┘
                            │
                  ┌─────────┴─────────┐
                  │  Ingestion Script  │
                  │ (offline, one-off  │
                  │  or scheduled job) │
                  └─────────┬─────────┘
                            │
                  ┌─────────▼─────────┐
                  │ Lenny's Transcript │
                  │  GitHub Repo       │
                  └────────────────────┘
```

## 2. Database Schema (PostgreSQL)

```sql
-- One row per chat session
CREATE TABLE sessions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_label    TEXT,                 -- free-text identifier, no auth in scope
    model_provider TEXT NOT NULL DEFAULT 'ollama', -- 'ollama' | 'anthropic' | 'openai' | 'gemini'
    metadata      JSONB DEFAULT '{}'::jsonb
);

-- One row per chat message (user or assistant)
CREATE TABLE messages (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role          TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content       TEXT NOT NULL,
    citations     JSONB DEFAULT '[]'::jsonb,   -- [{chunk_id, episode, url}]
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_session ON messages(session_id, created_at);

-- Transcript chunks + embeddings (pgvector extension)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE transcript_chunks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id    TEXT NOT NULL,        -- source file / episode identifier
    episode_title TEXT,
    source_url    TEXT,                 -- traceability back to repo file
    chunk_index   INT NOT NULL,
    content       TEXT NOT NULL,
    embedding     VECTOR(384),          -- dim depends on embedding model chosen
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_embedding ON transcript_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Generated artifacts (markdown/html)
CREATE TABLE artifacts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    type          TEXT NOT NULL CHECK (type IN ('markdown','html')),
    title         TEXT,
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Notes**
- `pgvector` keeps the vector store in the same Postgres instance as everything else — one connection string, one backup story, simpler ops than a separate vector DB for a take-home scope.
- `citations` is denormalized JSONB on `messages` rather than a join table, since citations are a display concern tied to a specific generated answer, not an independently queried entity.
- `ivfflat` index assumes a moderate corpus size (thousands of chunks); fine for the demo subset, and reindexing is a one-line operation if the corpus grows.

## 3. API Contracts (FastAPI)

All responses follow a consistent envelope: `{ "data": ..., "error": null }` or `{ "data": null, "error": { "code": ..., "message": ... } }`.

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/health` | Liveness + dependency checks (DB, Ollama reachability, active provider). |
| `POST` | `/sessions` | Create a new session. Returns session metadata. |
| `GET`  | `/sessions` | List sessions ordered by recent activity (`?after=` and `?limit=` supported). |
| `GET`  | `/sessions/{id}` | Fetch session metadata. |
| `POST` | `/sessions/{id}/messages` | Send a user message; returns assistant reply + citations. Body: `{ "content": str }`. |
| `GET`  | `/sessions/{id}/messages` | List message history (`?after=` and `?limit=` supported). |
| `POST` | `/sessions/{id}/artifacts` | Request grounded artifact generation. Body: `{ "type": "ship30_essay" \| "markdown" \| "html", "topic": str? }`. |
| `GET`  | `/artifacts/{id}` | Fetch a stored artifact by id. |
| `GET`  | `/sessions/{id}/artifacts` | List artifacts generated in a session. |
| `GET`  | `/config/model` | Return currently active provider + available providers. |
| `PUT`  | `/config/model` | Switch active provider (`ollama` \| `anthropic` \| `openai` \| `gemini`). Validates the target is configured/reachable before switching. |

**Validation:** Pydantic models for every request/response body; 422 on schema violation, 4xx with structured `error.code` for domain errors (e.g. `NO_RELEVANT_CONTEXT`, `PROVIDER_UNAVAILABLE`), 5xx reserved for genuine infra failures.

## 4. Ingestion & Retrieval Flow

**Ingestion (offline script, re-runnable):**
1. Clone/pull the transcript repository.
2. For each transcript file: parse into semantically coherent chunks (target ~300–500 tokens, with slight overlap) rather than fixed-line splitting, to keep chunk boundaries at sentence/paragraph breaks.
3. Embed each chunk with a local embedding model (e.g. a small sentence-transformers model, to avoid a hard dependency on a cloud embeddings API).
4. Upsert into `transcript_chunks`, keyed by `(episode_id, chunk_index)` so re-running ingestion is idempotent — reruns update rather than duplicate.
5. Store `source_url`/`episode_id` on every chunk so every retrieval result is traceable back to its origin.

**Retrieval (at query time):**
1. Embed the user's query with the same embedding model used for ingestion.
2. `pgvector` cosine-similarity search for top-k (default k=5) chunks.
3. Apply a minimum similarity threshold; if nothing clears it, short-circuit to the "insufficient evidence" response rather than forcing an answer.
4. Pass retrieved chunks + conversation history to the LLM with an explicit instruction to answer only from provided context and to cite chunk sources.
5. Map cited chunks back to `episode_id`/`source_url` and attach as structured `citations` on the returned message.

**Refresh:** ingestion script is safe to re-run on a schedule or manually when the source repo updates; idempotent upsert means no duplicate chunks accumulate.

## 5. Agent Layer & Routing

The agent layer uses the official Claude Agent SDK runtime for Anthropic-selected sessions. Ollama remains the mandatory local/default provider and OpenAI remains an adapter in the existing provider abstraction; those paths do not require Anthropic credentials or the Claude runtime. The runtime sits behind `/sessions/{id}/messages` and `/sessions/{id}/artifacts` when Anthropic is selected and exposes three tools:

- **`retrieve_transcripts(query)`** — runs the retrieval flow above, returns chunks + citations. Used for every conversational turn.
- **`generate_ship30_essay(topic, grounded_context)`** — a structured skill (not a raw prompt) encoding the Ship 30/30 rules: hook opening, short paragraphs, headings/bullets/bold emphasis, ~1,250-word target, one explicit takeaway, and a final self-check step that verifies word count and structure before returning.
- **`generate_artifact(spec)`** — produces Markdown or a self-contained HTML/CSS snippet based on conversation context; output is stored via `/sessions/{id}/artifacts` and returned to the frontend for rendering.

**Routing logic:** the agent always calls `retrieve_transcripts` first for any product/growth question. If the user's message is instead a request like "turn this into an essay" or "make this a one-pager," the agent routes to the corresponding generation tool using the already-grounded conversation context, rather than re-retrieving from scratch.

## 6. Model Toggle (Cloud vs. Local)

A single `LLMClient` interface abstracts generation:

```python
class LLMClient(Protocol):
    async def generate(self, messages: list[Message], **kwargs) -> str: ...

class OllamaClient(LLMClient): ...      # default, mandatory for demo
class AnthropicClient(LLMClient): ...   # cloud, optional
class OpenAIClient(LLMClient): ...      # cloud, optional
class GeminiClient(LLMClient): ...      # optional Google Gemini REST adapter
```

- Active provider is set via `MODEL_PROVIDER` env var and can be changed at runtime via `PUT /config/model`. The current implementation stores this toggle in process memory, so a restart resets it and multi-worker deployments should put the setting in a shared store before production use.
- The frontend displays the active provider name in the runtime bar and new message/artifact requests use the active runtime provider.
- **Fallback behavior:** Anthropic and OpenAI retain fallback to Ollama. Gemini is explicit: missing `GEMINI_API_KEY`, an unreachable service, or exhausted free quota returns `PROVIDER_UNAVAILABLE` rather than silently changing providers. Ollama with Llama 3.1 8B remains the mandatory local path and works without cloud credentials.

## 7. Artifact Security Model

Generated HTML/Markdown is treated as **fully untrusted output**, since it originates from LLM generation and could contain injected script content.

- **Markdown** is rendered client-side via a Markdown renderer with raw HTML passthrough disabled — no `dangerouslySetInnerHTML` on raw model output.
- **HTML artifacts** are rendered inside a sandboxed `<iframe>` using `sandbox="allow-scripts"` only (no `allow-same-origin`) and a restrictive CSP that blocks network connections, form actions, frames, and non-data images. Any inline script cannot read cookies, local storage, or the DOM of the host application, and cannot make authenticated requests as the logged-in session.
- No artifact content is ever `eval`'d or injected directly into the main app's DOM.
- The Artifact Viewer explicitly documents in-UI what it permits (visual rendering, isolated scripts for interactivity) and what it blocks (access to host app state, cross-origin credentialed requests, storage access).

## 8. Deployment Topology

- **Local/demo target:** `docker-compose.yml` brings up the FastAPI app and PostgreSQL (with `pgvector` extension pre-enabled via init script). Ollama runs as a host-level dependency (documented separately, since cross-platform Ollama containerization is unreliable within this scope) — the backend connects to it via `OLLAMA_HOST` (default `http://host.docker.internal:11434`).
- **Environment configuration:** `.env.example` documents all required/optional variables (`DATABASE_URL`, `MODEL_PROVIDER`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `ANTHROPIC_API_KEY` [optional], `OPENAI_API_KEY` [optional], `GEMINI_API_KEY` [optional], and `CORS_ORIGINS`) with safe, non-secret defaults.
- **Observability:** structured JSON logs (request id, session id, provider used, retrieval hit count, latency) at each layer — API, agent, retrieval, DB — so failures can be traced to the responsible component.
- **Resilience:** `/health` checks DB connectivity and Ollama reachability independently and reports each; missing cloud keys degrade gracefully (provider marked unavailable, not a startup crash); empty retrieval results produce the "insufficient evidence" response path rather than an error.
