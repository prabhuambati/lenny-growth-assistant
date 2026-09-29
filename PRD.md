# PRD: The Lenny Growth Assistant

## 1. User & Problem

**Primary user:** An internal operator at a product/growth team (PM, growth marketer, or founder) who wants fast, trustworthy answers to product and growth questions without reading through hundreds of hours of Lenny's Podcast transcripts themselves.

**Job to be done:** "When I have a product or growth question (pricing, retention, PLG motion, positioning, etc.), I want a grounded answer sourced from real operator interviews — plus the ability to turn that answer into a polished, shareable write-up — without having to search transcripts manually or trust an ungrounded LLM."

**Pain removed:**
- Manually searching/skimming podcast transcripts for relevant advice.
- Uncertainty about whether an LLM's answer is grounded in a real source or hallucinated.
- The extra step of turning a good answer into publishable content (essay, one-pager) — currently a separate, manual writing task.

## 2. Success Metric

**Primary (product) metric:** ≥ 80% of user questions receive an answer with at least one valid, correctly-cited transcript source (i.e., the citation actually exists in the source corpus and is topically relevant), measured against a fixed evaluation set of ~20 representative product/growth questions.

**Secondary (operational) metric:** Median end-to-end response latency under 8 seconds on the local Ollama path, so the assistant stays usable as a conversational tool rather than a batch job.

*(Rationale: grounding-accuracy is the core trust metric for a RAG product; latency is the core usability metric for local-model deployment, which the brief calls out as a known risk.)*

## 3. Assumptions

Because the client brief was intentionally incomplete, the following assumptions were made and should be validated with the client before further investment:

- The user is a single internal operator, not a multi-tenant external audience — so auth/roles are out of scope; sessions are enough to separate conversations.
- "Grounded strictly from Lenny's transcripts" means the assistant should not answer from general world knowledge when transcript evidence is insufficient — it should say so rather than guess.
- A representative subset of the transcript repository (not necessarily the full historical archive) is acceptable for the take-home demo, given time constraints; the ingestion pipeline is designed to scale to the full corpus later.
- "Ship 30 for 30 style" refers to the publicly documented format (hook, short punchy paragraphs, bolded key lines, one clear takeaway) rather than a proprietary internal style guide.
- Local Ollama is the required baseline experience; cloud LLM support is a "nice to have it work," not "must match local model quality."
- The client evaluator will run this on a normal developer laptop (not a GPU server), so model size choices for Ollama must be modest (e.g. a small/medium quantized model).

## 4. Scope

**In scope:**
- Grounded conversational Q&A over Lenny's Podcast transcripts, with session-based follow-up context.
- Source citation on every grounded answer (episode/transcript identifier).
- Explicit "insufficient evidence" fallback response when retrieval confidence is low.
- Ship 30 for 30 essay-generation skill, built as a structured tool rather than an ad hoc prompt.
- Markdown/HTML artifact generation with an in-app Artifact Viewer, rendered safely (sandboxed).
- Local LLM (Ollama with Llama 3.1 8B) as the default, mandatory path; optional Anthropic, OpenAI, and Google Gemini (`gemini-2.5-flash`) providers behind a config toggle. Gemini uses optional `GEMINI_API_KEY` and does not require billing for this project.
- Session and conversation persistence in PostgreSQL.
- Docker Compose–based one-command startup for the API and database.
- Baseline observability (structured logs) and graceful failure handling for missing keys, Ollama being down, empty retrieval, and DB connection loss.

**Out of scope (explicitly excluded, with rationale):**
- Multi-user auth, roles, and permissions — not needed for a single internal evaluator/demo; would add complexity without validating the core hypothesis.
- Ingesting and indexing the *entire* historical transcript archive — a representative subset is sufficient to prove the pipeline; full-corpus ingestion is a config change, not an architecture change.
- Fine-tuning or training a custom model — retrieval-augmented generation over an off-the-shelf model meets the grounding requirement without the cost/time of fine-tuning.
- Production-grade autoscaling, multi-region deployment, or CI/CD pipelines — this is a local/demo deployment target, not a production rollout.
- Rich collaborative features (sharing artifacts across users, commenting, version history on artifacts) — single-user, single-session artifact viewing satisfies the stated requirement.

## 5. Key Flows

1. **Start a new chat →** user opens the app, a new session is created and persisted.
2. **Ask a question →** query is embedded, top-k transcript chunks retrieved, LLM generates an answer grounded in those chunks, response includes source citations, message pair persisted to the session.
3. **Ask a follow-up →** prior session context is included, so the assistant can resolve references like "what about for enterprise pricing specifically?"
4. **Request an essay →** user asks the assistant to turn the current answer/topic into a Ship 30/30-style essay; the dedicated skill runs, checks length/structure rules, and returns the essay as a Markdown artifact.
5. **View an artifact →** the returned Markdown/HTML renders in the Artifact Viewer panel beside the chat, sandboxed from the rest of the app.
6. **Switch model provider →** evaluator toggles between Ollama, Anthropic, OpenAI, and Google Gemini via config/UI; the active provider and model are visibly indicated.
7. **Failure paths →** if retrieval returns nothing relevant, Ollama is unreachable, or the DB is down, the user sees a clear, specific error message instead of a silent failure or hallucinated answer.

## 6. Acceptance Criteria

- A new session can be created, and messages within it maintain context across at least 3 follow-up turns.
- Every grounded answer includes at least one identifiable transcript source; when no relevant transcript content exists, the assistant explicitly states it cannot answer from available material rather than guessing.
- The Ship 30/30 skill produces an essay within ±15% of ~1,250 words, with a hook, headings/bullets/bold emphasis, and one explicit takeaway.
- Generated Markdown/HTML artifacts render correctly in the Artifact Viewer without executing unsanitized scripts against the host app. Markdown disables raw HTML passthrough; HTML uses `sandbox="allow-scripts"` without `allow-same-origin`.
- The system runs end-to-end via a single documented startup command with Ollama as the active provider, with no cloud API key required for the local path to function.
- Switching the model provider via config does not require a code change or restart of unrelated services.
- The system returns a structured, human-readable error (not a crash) for each of: missing API key, unreachable Ollama, empty retrieval results, and lost DB connection.

## 7. Risks & Trade-offs

| Risk | Trade-off / Mitigation |
|---|---|
| Hallucination | Strict RAG grounding + explicit "insufficient evidence" fallback rather than best-effort guessing. |
| Latency (local models) | Ollama responses may be slower than cloud; mitigate with streaming output and a visible "thinking" state so the wait feels responsive. |
| Local model quality vs. cloud | Smaller local models may give shallower answers; this is documented openly rather than hidden, per the assignment's explicit ask. |
| Data leakage across sessions | Session-scoped context in Postgres; no cross-session memory by default. |
| Unsafe artifact rendering | Generated HTML is treated as fully untrusted; rendered in a sandboxed iframe with restricted permissions (no same-origin script execution against the host app). |
| Cost (cloud path) | Cloud provider use is opt-in via config, not default, to avoid unexpected spend during evaluation. |
| Incomplete transcript coverage (subset ingested for demo) | Documented explicitly as a scope choice; ingestion pipeline is designed to extend to the full corpus without architecture changes. |

## 8. Implementation Plan (Summary)

See `architecture.md` for full technical detail. At a high level, delivery proceeds in phases: (1) discovery & scoping — this PRD, (2) data ingestion pipeline for transcripts, (3) backend API and persistence, (4) agent/RAG layer with model toggle, (5) Ship 30/30 skill and artifact generation, (6) frontend chat UI and Artifact Viewer, (7) operational hardening (Docker, logging, failure handling), (8) tests, documentation, and demo recording.
