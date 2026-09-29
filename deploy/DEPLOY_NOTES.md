# Deployment Notes (Docker Compose)

## Layout
Place these at the repository root:
```
docker-compose.yml
deploy/db-init/001-enable-pgvector.sql
backend/            (Dockerfile, app/, requirements.txt, .env.example)
```

## One-command startup
```bash
cp backend/.env.example backend/.env      # edit if adding cloud provider keys
ollama serve                              # on the HOST machine, not in Docker
ollama pull llama3.1:8b                   # or whichever OLLAMA_MODEL you configured
docker compose up --build
```
- API available at `http://localhost:8000` (`/health` to verify).
- Postgres available at `localhost:5432` for local inspection (`psql`, DBeaver, etc.).

## Why Ollama isn't in Docker
Containerizing Ollama with reliable GPU/Metal acceleration differs significantly
across macOS, Windows, and Linux, and is out of scope for a take-home demo timeline.
Running it on the host is simpler, faster, and the more common way people already
run Ollama day-to-day. The `api` service reaches it via `host.docker.internal`,
which is wired for both Docker Desktop (macOS/Windows) and Linux (via `extra_hosts`).

## Running ingestion
The ingestion script talks to Postgres directly and isn't part of the always-on
compose services (it's a one-off/occasional job, not a server). Run it against
the same database Docker Compose started:

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/lenny_assistant
pip install -r requirements-ingest.txt
python ingest.py --repo-dir ./data/lennys-podcast-transcripts --limit 30
```

## First-run gotcha
The `deploy/db-init/*.sql` scripts only run automatically the **first** time the
Postgres data volume is created. If you already ran `docker compose up` before
adding the pgvector init script, either:
```bash
docker compose down -v   # WARNING: wipes local dev data, fine pre-launch
docker compose up --build
```
or manually run `CREATE EXTENSION IF NOT EXISTS vector;` once via `psql`.
