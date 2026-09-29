import logging
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from app.agent import orchestrator
from app.config import get_settings
from app.database import get_db
from app.models import db_models
from app.models.schemas import (
    ArtifactResponse,
    CreateSessionRequest,
    GenerateArtifactRequest,
    MessageResponse,
    SendMessageRequest,
    SessionListResponse,
    SessionResponse,
)
from app.services.llm_client import Message, ProviderUnavailableError
from app.services import retrieval
from app.services.retrieval import RetrievalUnavailableError

log = logging.getLogger("sessions")
router = APIRouter(prefix="/sessions", tags=["sessions"])
artifacts_router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _get_session_or_404(db: DBSession, session_id: UUID) -> db_models.Session:
    session = db.get(db_models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "Session not found"})
    return session


@router.post("", response_model=SessionResponse, status_code=201)
def create_session(body: CreateSessionRequest, db: DBSession = Depends(get_db)):
    settings = get_settings()
    session = db_models.Session(user_label=body.user_label, model_provider=settings.model_provider)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("", response_model=SessionListResponse)
def list_sessions(
    after: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: DBSession = Depends(get_db),
):
    query = db.query(db_models.Session).order_by(
        db_models.Session.updated_at.desc(), db_models.Session.created_at.desc()
    )
    if after:
        anchor = db.get(db_models.Session, after)
        if anchor:
            query = query.filter(
                (db_models.Session.updated_at < anchor.updated_at)
                | (
                    (db_models.Session.updated_at == anchor.updated_at)
                    & (db_models.Session.created_at < anchor.created_at)
                )
            )
    items = query.limit(limit + 1).all()
    next_after = items[limit].id if len(items) > limit else None
    return {"items": items[:limit], "next_after": next_after}


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: UUID, db: DBSession = Depends(get_db)):
    return _get_session_or_404(db, session_id)


@router.get("/{session_id}/messages", response_model=list[MessageResponse])
def list_messages(
    session_id: UUID,
    after: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    db: DBSession = Depends(get_db),
):
    _get_session_or_404(db, session_id)
    query = (
        db.query(db_models.Message)
        .filter(db_models.Message.session_id == session_id)
        .order_by(db_models.Message.created_at, db_models.Message.id)
    )
    if after:
        anchor = db.get(db_models.Message, after)
        if anchor and anchor.session_id == session_id:
            query = query.filter(
                (db_models.Message.created_at > anchor.created_at)
                | (
                    (db_models.Message.created_at == anchor.created_at)
                    & (db_models.Message.id > anchor.id)
                )
            )
    return query.limit(limit).all()


@artifacts_router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: UUID, db: DBSession = Depends(get_db)):
    artifact = db.get(db_models.Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND", "message": "Artifact not found"})
    return artifact


@router.get("/{session_id}/artifacts", response_model=list[ArtifactResponse])
def list_artifacts(session_id: UUID, db: DBSession = Depends(get_db)):
    _get_session_or_404(db, session_id)
    return (
        db.query(db_models.Artifact)
        .filter(db_models.Artifact.session_id == session_id)
        .order_by(db_models.Artifact.created_at.desc())
        .all()
    )


@router.post("/{session_id}/messages", response_model=MessageResponse)
async def send_message(session_id: UUID, body: SendMessageRequest, db: DBSession = Depends(get_db)):
    session = _get_session_or_404(db, session_id)
    settings = get_settings()

    user_msg = db_models.Message(session_id=session_id, role="user", content=body.content)
    db.add(user_msg)
    db.flush()

    history_rows = (
        db.query(db_models.Message)
        .filter(db_models.Message.session_id == session_id)
        .order_by(db_models.Message.created_at)
        .all()
    )
    history = [Message(role=m.role, content=m.content) for m in history_rows[:-1]]  # exclude the just-added user msg

    try:
        reply_text, citations, provider_used = await orchestrator.handle_chat_turn(
            db, session_id, history, body.content, settings.model_provider, settings
        )
    except ProviderUnavailableError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={"code": "PROVIDER_UNAVAILABLE", "message": f"{exc.provider} is unavailable: {exc.detail}"},
        ) from exc
    except RetrievalUnavailableError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={"code": "RETRIEVAL_UNAVAILABLE", "message": str(exc)},
        ) from exc

    assistant_msg = db_models.Message(
        session_id=session_id, role="assistant", content=reply_text, citations=citations
    )
    db.add(assistant_msg)
    if orchestrator.is_ship30_request(body.content) and reply_text != orchestrator.INSUFFICIENT_EVIDENCE_REPLY:
        db.add(
            db_models.Artifact(
                session_id=session_id,
                type="markdown",
                title="Ship 30/30: " + body.content,
                content=reply_text,
            )
        )
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(assistant_msg)
    return assistant_msg


@router.post("/{session_id}/artifacts", response_model=ArtifactResponse)
async def generate_artifact(session_id: UUID, body: GenerateArtifactRequest, db: DBSession = Depends(get_db)):
    session = _get_session_or_404(db, session_id)
    settings = get_settings()

    history_rows = (
        db.query(db_models.Message)
        .filter(db_models.Message.session_id == session_id)
        .order_by(db_models.Message.created_at)
        .all()
    )
    context = "\n".join(f"{m.role}: {m.content}" for m in history_rows)

    if body.type != "ship30_essay" and settings.model_provider != "anthropic":
        grounding_query = body.topic or next(
            (m.content for m in reversed(history_rows) if m.role == "user"),
            context[-2000:],
        )
        try:
            grounding_chunks = retrieval.retrieve(db, grounding_query, top_k=settings.retrieval_top_k)
        except RetrievalUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "RETRIEVAL_UNAVAILABLE", "message": str(exc)},
            ) from exc
        if not grounding_chunks:
            raise HTTPException(
                status_code=422,
                detail={"code": "NO_RELEVANT_CONTEXT", "message": orchestrator.INSUFFICIENT_EVIDENCE_REPLY},
            )
        context += "\n\nGrounded transcript evidence:\n" + orchestrator._normal_chat_context(grounding_chunks)

    try:
        if body.type == "ship30_essay":
            topic = body.topic or context[-2000:]
            if settings.model_provider == "anthropic":
                agent_result = await orchestrator.handle_anthropic_agent(
                    db, topic, [Message(role=m.role, content=m.content) for m in history_rows], settings, "artifact"
                )
                if not agent_result.chunks or not agent_result.text.strip():
                    raise HTTPException(
                        status_code=422,
                        detail={"code": "NO_RELEVANT_CONTEXT", "message": orchestrator.INSUFFICIENT_EVIDENCE_REPLY},
                    )
                content = agent_result.text
            else:
                result = await orchestrator.handle_ship30_essay(
                    db, topic, settings.model_provider, settings
                )
                if result.insufficient_evidence or not result.essay:
                    raise HTTPException(
                        status_code=422,
                        detail={"code": "NO_RELEVANT_CONTEXT", "message": orchestrator.INSUFFICIENT_EVIDENCE_REPLY},
                    )
                if not result.validation.valid:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "ARTIFACT_VALIDATION_FAILED",
                            "message": "The generated Ship 30/30 draft did not pass validation: "
                            + ", ".join(result.validation.issues),
                        },
                    )
                content = result.essay
            artifact_type = "markdown"
        else:
            if settings.model_provider == "anthropic":
                agent_result = await orchestrator.handle_anthropic_agent(
                    db, context, [Message(role=m.role, content=m.content) for m in history_rows], settings, "artifact"
                )
                if not agent_result.chunks or not agent_result.text.strip():
                    raise HTTPException(
                        status_code=422,
                        detail={"code": "NO_RELEVANT_CONTEXT", "message": orchestrator.INSUFFICIENT_EVIDENCE_REPLY},
                    )
                content = agent_result.text
            else:
                content = await orchestrator.handle_artifact_generation(
                    db, body.type, context, settings.model_provider, settings
                )
            artifact_type = body.type
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "PROVIDER_UNAVAILABLE", "message": f"{exc.provider} is unavailable: {exc.detail}"},
        ) from exc
    except RetrievalUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "RETRIEVAL_UNAVAILABLE", "message": str(exc)},
        ) from exc

    artifact = db_models.Artifact(
        session_id=session_id, type=artifact_type, title=body.topic, content=content
    )
    db.add(artifact)
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(artifact)
    return artifact
