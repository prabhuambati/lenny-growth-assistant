# Manual Smoke-Test Plan

Run these checks after starting the database, backend, frontend, and Ollama according to the README.

## 1. Runtime health

- Open the frontend at `http://localhost:5173`.
- Confirm the runtime bar shows database health and Ollama availability.
- Open `http://localhost:8000/health` and confirm it returns a structured `data` payload.

## 2. Sessions

- Reload the frontend and confirm the previous conversation remains selected.
- Click **New Chat** and confirm the new conversation appears in the sidebar.
- Switch between two conversations and confirm messages remain session-scoped.
- Delete or clear the stored browser session ID, reload, and confirm a new chat is created.

## 3. Grounded chat

- Ask a question clearly covered by an ingested transcript.
- Confirm the answer displays at least one episode citation.
- Ask an unrelated question and confirm the assistant says it lacks sufficient transcript evidence.
- Stop Ollama or make the provider unavailable and confirm the UI shows a readable provider error without leaving a duplicate user message after retry.

## 4. Provider configuration

- Switch between configured providers from the runtime bar.
- Send a message after switching and confirm the request uses the newly selected provider.
- Try selecting a provider without credentials and confirm the selection is rejected without changing the active provider.

## 5. Artifacts

- Request a Ship 30/30 essay from a grounded conversation.
- Confirm the artifact appears in the viewer and contains citations, headings, and a takeaway.
- Request Markdown or HTML from a grounded topic.
- Confirm HTML renders in the isolated preview and cannot make network requests.
- Verify `GET /artifacts/{id}` returns the stored artifact.

## 6. Ingestion

- Run `python ingest.py --skip-clone --repo-dir <checkout> --limit 0` and confirm zero episodes are selected.
- Re-run ingestion after shortening one transcript and verify stale chunks for that episode are removed.
- Run against an existing non-Git directory without `--skip-clone` and confirm the command returns a targeted error.
