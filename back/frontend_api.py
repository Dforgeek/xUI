"""
One-Block Survey API — v1 endpoints, token auth, deadline enforcement, JSONB answers

Add this module next to your existing FastAPI app (or merge into main.py).
It:
- Introduces 3 new endpoints per your OpenAPI:
  GET    /v1/surveys/access/{linkToken}
  POST   /v1/surveys/{surveyId}/responses
  PATCH  /v1/surveys/{surveyId}/responses/{responseId}
- Adds models: SurveyLinkToken, SurveyResponse (+ optional column on SurveyQuestion)
- Validates tokens, enforces deadlines (410), and validates answers (422)
- Uses stable Block IDs: "q{question_id}" and a synthetic "profile" block

If you keep your old routes, this file can be imported and mounted onto the same app.
Search for "### WIRE INTO EXISTING APP" below.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Path, Security, Query
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy import (
    BigInteger,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    select,
    func,
    and_,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload, joinedload

# ---------------------------------------------------------------------------
# Bring in your Session + Base + existing models via imports OR paste below
# You already have Base, SessionLocal, and models in main.py. We'll import them.
# From your existing project structure:
#   from main import Base, Survey, SurveyQuestion, Question, UserInfo, get_session
# If you merge this file into main.py, remove these imports and use in-file names.
# ---------------------------------------------------------------------------
try:
    from main import (
        Base,
        Survey,
        SurveyQuestion,
        Question,
        UserInfo,
        get_session,
        InitiateSurveyBatchOut, 
        InitiateSurveyIn, 
        InitiatedPersonalSurvey, 
        SurveyBatch,      
        ReviewSummary
    )
except Exception as _e:
    raise RuntimeError(
        "Import this module only after your current main.py is importable. "
        "Alternatively, paste this content directly into main.py.\n"
        f"Original import error: {_e}"
    )

# =========================
# New DB Models
# =========================

class SurveyLinkToken(Base):
    __tablename__ = "survey_link_token"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    survey_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("survey.id", ondelete="CASCADE"), nullable=False)
    respondent_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_info.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_access_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    survey: Mapped["Survey"] = relationship(lazy="joined")
    respondent: Mapped["UserInfo"] = relationship(lazy="joined")

class SurveyResponse(Base):
    __tablename__ = "survey_response"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    survey_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("survey.id", ondelete="CASCADE"), nullable=False, index=True)
    respondent_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_info.id", ondelete="CASCADE"), nullable=False, index=True)
    link_token: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    answers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint("survey_id", "respondent_user_id", name="uq_response_unique_per_respondent"),)

    survey: Mapped["Survey"] = relationship(lazy="joined")
    respondent: Mapped["UserInfo"] = relationship(lazy="joined")

# Optional flag for per-question optionality
# Add a column to SurveyQuestion: optional bool default false
if not hasattr(SurveyQuestion, "optional"):
    # This attribute mapping allows SQLAlchemy to work even before migration runs; column must be added in DB.
    SurveyQuestion.optional = mapped_column(Boolean, nullable=False, default=False)  # type: ignore

# Optional title on Survey
if not hasattr(Survey, "title"):
    Survey.title = mapped_column(String(255), nullable=True, default=None)  # type: ignore

# =========================
# Security / Dependencies
# =========================

LinkTokenHeader = APIKeyHeader(name="X-Survey-Token", auto_error=False)

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

async def get_link_or_401(
    token: Optional[str] = Security(LinkTokenHeader),
    db: AsyncSession = Depends(get_session)
) -> SurveyLinkToken:
    if not token:
        raise HTTPException(status_code=401, detail="Missing X-Survey-Token")
    link = await db.scalar(select(SurveyLinkToken).where(SurveyLinkToken.token == token))
    if not link or link.is_revoked:
        raise HTTPException(status_code=401, detail="Invalid token")
    return link

# ----- Envelope DTOs -----
class RespondentOut(BaseModel):
    respondentId: str
    firstName: str
    lastName: str
    email: Optional[str] = None
    telegram: Optional[str] = None

class SubjectOut(BaseModel):
    subjectId: str
    firstName: str
    lastName: str

class BlockBase(BaseModel):
    id: str
    type: str
    name: str
    optional: bool = False
    answerText: Optional[str] = None

class BlockProfile(BlockBase):
    type: Literal["profile"] = "profile"

class BlockRating(BlockBase):
    type: Literal["rating"] = "rating"
    question: str
    min: int = 1
    max: int = 10

class BlockText(BlockBase):
    type: Literal["text"] = "text"
    prompt: str
    placeholder: Optional[str] = None
    minLength: Optional[int] = None

BlockOut = BlockProfile | BlockRating | BlockText

class SurveyOut(BaseModel):
    surveyId: str
    title: str
    deadlineISO: str
    respondent: RespondentOut
    subject: SubjectOut
    blocks: List[BlockOut]

class SurveyEnvelope(BaseModel):
    nowISO: str
    isClosed: bool
    survey: SurveyOut
    # NEW: present when a response already exists for this link
    response: Optional[ExistingResponseOut] = None


class ClientMeta(BaseModel):
    userAgent: Optional[str] = None
    timezone: Optional[str] = None
    startedAtISO: Optional[str] = None
    submittedAtISO: Optional[str] = None

class ResponseSubmission(BaseModel):
    answers: Dict[str, Any]
    client: Optional[ClientMeta] = None

class ResponseCreated(BaseModel):
    responseId: str
    surveyId: str
    submittedAtISO: str
    version: int

class ResponseUpdate(BaseModel):
    answersDelta: Dict[str, Any]
    client: Optional[ClientMeta] = None

class ResponseUpdated(BaseModel):
    responseId: str
    surveyId: str
    updatedAtISO: str
    version: int
    
    
class ExistingResponseOut(BaseModel):
    responseId: str
    version: int
    submittedAtISO: Optional[str] = None
    updatedAtISO: Optional[str] = None
    finalized: Optional[bool] = None
# =========================
# Surveys 
# =========================

class SurveyListRespondent(BaseModel):
    userId: int
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    telegram: Optional[str] = None

class SurveyListSubject(BaseModel):
    userId: int
    firstName: Optional[str] = None
    lastName: Optional[str] = None

class SurveyListItemOut(BaseModel):
    surveyId: str
    createdAtISO: str
    deadlineISO: str
    isClosed: bool
    reviewType: str
    title: Optional[str] = None
    subject: SurveyListSubject
    respondent: SurveyListRespondent
    hasResponse: bool
    responseVersion: Optional[int] = None
    linkToken: Optional[str] = None  # only when includeLinks=true


# ----- Helpers -----

# Eager loader for token + related rows (prevents MissingGreenlet)
async def _load_linked_context(db: AsyncSession, link_token: str) -> tuple[SurveyLinkToken, Survey, UserInfo, UserInfo]:
    link = await db.scalar(
        select(SurveyLinkToken)
        .options(
            joinedload(SurveyLinkToken.survey).joinedload(Survey.subject_user),
            joinedload(SurveyLinkToken.survey).joinedload(Survey.respondent_user),
            joinedload(SurveyLinkToken.respondent),
        )
        .where(
            SurveyLinkToken.token == link_token,
            SurveyLinkToken.is_revoked.is_(False),
        )
    )
    if not link:
        raise HTTPException(401, "Invalid token")

    survey = link.survey
    subject = survey.subject_user
    respondent = link.respondent or survey.respondent_user
    return link, survey, subject, respondent

# Build blocks for the envelope from SurveyQuestion/Question
async def _build_blocks(db: AsyncSession, survey_id: int) -> list[BlockOut]:
    rows = (
        await db.execute(
            select(
                SurveyQuestion.question_id,
                SurveyQuestion.optional,
                Question.question_text,
                Question.question_type,
                Question.answer_fields,
            )
            .join(Question, Question.id == SurveyQuestion.question_id)
            .where(SurveyQuestion.survey_id == survey_id)
            .order_by(Question.id)
        )
    ).all()

    blocks: list[BlockOut] = []
    for qid, optional, qtext, qtype, afields in rows:
        bid = f"q{qid}"
        name = (qtext or "").split("\n", 1)[0][:80] or f"Question {qid}"

        # defaults
        min_v, max_v, placeholder, min_len = 1, 10, None, None
        try:
            meta = json.loads(afields) if afields else {}
            min_v = int(meta.get("min", min_v))
            max_v = int(meta.get("max", max_v))
            placeholder = meta.get("placeholder")
            if meta.get("minLength") is not None:
                min_len = int(meta.get("minLength"))
        except Exception:
            pass

        if qtype == 1:  # rating
            blocks.append(
                BlockRating(
                    id=bid, type="rating", name=name, optional=bool(optional),
                    question=qtext, min=min_v, max=max_v
                )
            )
        else:  # text
            blocks.append(
                BlockText(
                    id=bid, type="text", name=name, optional=bool(optional),
                    prompt=qtext, placeholder=placeholder, minLength=min_len
                )
            )
    return blocks

async def _validate_answers_against_blocks(answers: Dict[str, Any], blocks: List[BlockOut]) -> None:
    bmap: Dict[str, BlockOut] = {b.id: b for b in blocks}
    for bid, val in answers.items():
        if bid not in bmap:
            raise HTTPException(422, detail=f"Unknown block id: {bid}")
        b = bmap[bid]
        if isinstance(b, BlockRating):
            if val is None and not b.optional:
                raise HTTPException(422, detail=f"Block {bid} is required")
            if val is not None:
                if not isinstance(val, int):
                    raise HTTPException(422, detail=f"Block {bid} must be integer")
                if not (b.min <= val <= b.max):
                    raise HTTPException(422, detail=f"Block {bid} out of range [{b.min},{b.max}]")
        elif isinstance(b, BlockText):
            if val is None and not b.optional:
                raise HTTPException(422, detail=f"Block {bid} is required")
            if val is not None:
                if not isinstance(val, str):
                    raise HTTPException(422, detail=f"Block {bid} must be string")
                if b.minLength is not None and len(val) < b.minLength:
                    raise HTTPException(422, detail=f"Block {bid} minLength={b.minLength}")
        else:
            if val is not None:
                raise HTTPException(422, detail=f"Block {bid} is not answerable")

# ----- Router -----
v1 = APIRouter(prefix="/v1")

@v1.get("/surveys/access/{linkToken}", response_model=SurveyEnvelope, tags=["Surveys"])
async def get_survey_by_link_token(
    linkToken: str = Path(...),
    db: AsyncSession = Depends(get_session),
):
    link, survey, subject, respondent = await _load_linked_context(db, linkToken)

    now = _now_utc()
    if now > survey.deadline:
        raise HTTPException(410, "Survey deadline has passed")

    await db.execute(
        update(SurveyLinkToken).where(SurveyLinkToken.id == link.id).values(last_access_at=now)
    )
    await db.commit()

    blocks = await _build_blocks(db, survey.id)
    title = survey.title or (f"{survey.review_type.upper()} Engineering 360" if survey.review_type else "360 Survey")

    # Новое: подставляем текст уже данных ответов прямо в блоки
    existing = await db.scalar(
        select(SurveyResponse).where(
            and_(
                SurveyResponse.survey_id == survey.id,
                SurveyResponse.respondent_user_id == respondent.id,
            )
        )
    )
    if existing and existing.answers:
        amap = dict(existing.answers)
        for b in blocks:
            raw = amap.get(b.id)
            if raw is None:
                continue
            # Для rating кладём число как строку; для text — сам текст
            if isinstance(b, BlockText):
                b.answerText = raw
            elif isinstance(b, BlockRating):
                b.answerText = str(raw)
        # NEW: if there is an existing response, expose its identifiers for PATCH
    resp_meta: Optional[ExistingResponseOut] = None
    if existing:
        resp_meta = ExistingResponseOut(
            responseId=f"rsp_{existing.id}",
            version=int(existing.version),
            submittedAtISO=_iso(existing.submitted_at) if existing.submitted_at else None,
            updatedAtISO=_iso(existing.updated_at) if existing.updated_at else None,
            finalized=bool(existing.finalized),
        )


    return SurveyEnvelope(
        nowISO=_iso(now),
        isClosed=False,  # you can keep raising 410 above if deadline passed
        survey=SurveyOut(
            surveyId=f"srv_{survey.id}",
            title=title,
            deadlineISO=_iso(survey.deadline),
            respondent=RespondentOut(
                respondentId=f"usr_{respondent.id}",
                firstName=respondent.first_name or str(respondent.id),
                lastName=respondent.last_name or "",
                email=respondent.email,
                telegram=respondent.telegram,
            ),
            subject=SubjectOut(
                subjectId=f"usr_{subject.id}",
                firstName=subject.first_name or str(subject.id),
                lastName=subject.last_name or "",
            ),
            blocks=blocks,
        ),
        response=resp_meta,  # NEW
    )


@v1.post("/surveys/{surveyId}/responses", response_model=ResponseCreated, status_code=201, tags=["Responses"])
async def create_response(
    surveyId: str,
    payload: ResponseSubmission,
    link: SurveyLinkToken = Depends(get_link_or_401),
    db: AsyncSession = Depends(get_session),
):
    try:
        sid = int(surveyId.split("_", 1)[1])
    except Exception:
        raise HTTPException(400, "Invalid surveyId format")

    if link.survey_id != sid:
        raise HTTPException(403, "Token not allowed for this survey")

    now = _now_utc()
    if now > link.survey.deadline:
        raise HTTPException(410, "Survey deadline passed")

    blocks = await _build_blocks(db, sid)
    await _validate_answers_against_blocks(payload.answers, blocks)

    existing = await db.scalar(
        select(SurveyResponse).where(
            and_(
                SurveyResponse.survey_id == sid,
                SurveyResponse.respondent_user_id == link.respondent_user_id,
            )
        )
    )
    if existing:
        raise HTTPException(409, "Response already exists; use PATCH to update")

    rsp = SurveyResponse(
        survey_id=sid,
        respondent_user_id=link.respondent_user_id,
        link_token=link.token,
        version=1,
        answers=payload.answers or {},
        submitted_at=now,
        updated_at=now,
        finalized=False,
    )
    db.add(rsp)
    await db.commit()
    await db.refresh(rsp)
    try:
        batch_id = link.survey.batch_id
        if batch_id:
            now2 = _now_utc()
            expected = await db.scalar(
                select(SurveyBatch.expected_respondents).where(SurveyBatch.id == batch_id)
            )
            responded = await db.scalar(
                select(func.count())
                .select_from(SurveyResponse)
                .join(Survey, Survey.id == SurveyResponse.survey_id)
                .where(Survey.batch_id == batch_id)
            )
            deadline = await db.scalar(
                select(SurveyBatch.deadline).where(SurveyBatch.id == batch_id)
            )

            ready = (
                (responded is not None and expected is not None and int(responded) >= int(expected))
                or (deadline and now2 > deadline)
            )

            if ready:
                exists = await db.scalar(
                    select(func.count())
                    .select_from(ReviewSummary)
                    .where(ReviewSummary.batch_id == batch_id)
                )
                if not exists:
                    db.add(
                        ReviewSummary(
                            batch_id=batch_id,
                            subject_user_id=link.survey.subject_user_id,
                            status="queued",
                            created_at=now2,
                            updated_at=now2,
                        )
                    )
                    await db.commit()
    except Exception:
        # Don't block respondent flow if this fails.
        pass
    return ResponseCreated(
        responseId=f"rsp_{rsp.id}",
        surveyId=f"srv_{sid}",
        submittedAtISO=_iso(now),
        version=rsp.version,
    )

@v1.patch("/surveys/{surveyId}/responses/{responseId}", response_model=ResponseUpdated, tags=["Responses"])
async def update_response(
    surveyId: str,
    responseId: str,
    payload: ResponseUpdate,
    link: SurveyLinkToken = Depends(get_link_or_401),
    db: AsyncSession = Depends(get_session),
):
    try:
        sid = int(surveyId.split("_", 1)[1])
        rid = int(responseId.split("_", 1)[1])
    except Exception:
        raise HTTPException(400, "Invalid id format")

    if link.survey_id != sid:
        raise HTTPException(403, "Token not allowed")

    rsp = await db.scalar(
        select(SurveyResponse).where(
            and_(
                SurveyResponse.id == rid,
                SurveyResponse.survey_id == sid,
                SurveyResponse.respondent_user_id == link.respondent_user_id,
            )
        )
    )
    if not rsp:
        raise HTTPException(404, "Response not found")

    now = _now_utc()
    if now > rsp.survey.deadline:
        raise HTTPException(409, "Response locked (deadline passed)")
    if rsp.finalized:
        raise HTTPException(409, "Response locked (finalized)")

    blocks = await _build_blocks(db, sid)
    await _validate_answers_against_blocks(payload.answersDelta, blocks)

    merged = dict(rsp.answers)
    for k, v in payload.answersDelta.items():
        merged[k] = v  # keep nulls for optional omitted
    rsp.answers = merged
    rsp.version = int(rsp.version) + 1
    rsp.updated_at = now

    await db.commit()
    await db.refresh(rsp)

    return ResponseUpdated(
        responseId=f"rsp_{rsp.id}",
        surveyId=f"srv_{sid}",
        updatedAtISO=_iso(now),
        version=rsp.version,
    )

@v1.get("/surveys", response_model=List[SurveyListItemOut], tags=["Surveys"])
async def list_surveys(
    subject_user_id: Optional[int] = Query(None),
    respondent_user_id: Optional[int] = Query(None),
    includeLinks: bool = Query(False),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    # 1) Load surveys with related users eagerly to avoid lazy loads in async
    q = (
        select(Survey)
        .options(
            selectinload(Survey.subject_user),     # <- eager-load subject
            selectinload(Survey.respondent_user),  # <- eager-load respondent
        )
    )
    if subject_user_id is not None:
        q = q.where(Survey.subject_user_id == subject_user_id)
    if respondent_user_id is not None:
        q = q.where(Survey.respondent_user_id == respondent_user_id)

    q = q.order_by(Survey.created_at.desc()).limit(limit).offset(offset)
    surveys: List[Survey] = (await db.execute(q)).scalars().all()

    if not surveys:
        return []

    survey_ids = [s.id for s in surveys]

    # 2) Map max response version per survey (hasResponse / responseVersion)
    ver_rows = (
        await db.execute(
            select(SurveyResponse.survey_id, func.max(SurveyResponse.version))
            .where(SurveyResponse.survey_id.in_(survey_ids))
            .group_by(SurveyResponse.survey_id)
        )
    ).all()
    version_map: Dict[int, Optional[int]] = {sid: (int(ver) if ver is not None else None) for sid, ver in ver_rows}

    # 3) Optionally fetch a token per survey (latest by created_at)
    token_map: Dict[int, str] = {}
    if includeLinks:
        tok_rows = (
            await db.execute(
                select(SurveyLinkToken.survey_id, SurveyLinkToken.token)
                .where(SurveyLinkToken.survey_id.in_(survey_ids))
                .order_by(SurveyLinkToken.survey_id, SurveyLinkToken.created_at.desc())
            )
        ).all()
        # keep first (latest) token per survey
        for sid, tok in tok_rows:
            if sid not in token_map:
                token_map[sid] = tok

    # 4) Build response without triggering any more I/O
    now = datetime.now(timezone.utc)
    out: List[SurveyListItemOut] = []
    for s in surveys:
        subj = s.subject_user
        resp = s.respondent_user
        out.append(
            SurveyListItemOut(
                surveyId=f"srv_{s.id}",
                createdAtISO=s.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                deadlineISO=s.deadline.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                isClosed=now > s.deadline,
                reviewType=s.review_type,
                title=s.title,
                subject=SurveyListSubject(
                    userId=subj.id,
                    firstName=getattr(subj, "first_name", None),
                    lastName=getattr(subj, "last_name", None),
                ),
                respondent=SurveyListRespondent(
                    userId=resp.id,
                    firstName=getattr(resp, "first_name", None),
                    lastName=getattr(resp, "last_name", None),
                    email=getattr(resp, "email", None),
                    telegram=getattr(resp, "telegram", None),
                ),
                hasResponse=s.id in version_map,
                responseVersion=version_map.get(s.id),
                linkToken=token_map.get(s.id) if includeLinks else None,
            )
        )
    return out



@v1.post("/surveys/initiate", response_model=InitiateSurveyBatchOut, status_code=201, tags=["Surveys"])
async def initiate_survey(payload: InitiateSurveyIn, db: AsyncSession = Depends(get_session)):
    # Validate subject
    subject_exists = await db.scalar(
        select(func.count()).select_from(UserInfo).where(UserInfo.id == payload.subject_user_id)
    )
    if not subject_exists:
        raise HTTPException(400, "subject_user_id not found")

    # Reviewers (unique, auto-include subject for 360)
    if not payload.reviewer_user_ids:
        raise HTTPException(400, "reviewer_user_ids must contain at least one user")
    seen: Set[int] = set()
    reviewers: List[int] = []
    for uid in payload.reviewer_user_ids:
        if uid not in seen:
            seen.add(uid)
            reviewers.append(uid)
    if payload.review_type == "360" and payload.subject_user_id not in seen:
        reviewers.append(payload.subject_user_id)

    # Validate reviewers
    count_reviewers = await db.scalar(
        select(func.count()).select_from(UserInfo).where(UserInfo.id.in_(reviewers))
    )
    if count_reviewers != len(reviewers):
        raise HTTPException(400, "Some reviewer_user_ids do not exist")

    # Validate questions
    if not payload.question_ids:
        raise HTTPException(400, "No questions selected")
    q_seen, question_ids = set(), []
    for qid in payload.question_ids:
        if qid not in q_seen:
            q_seen.add(qid)
            question_ids.append(qid)
    q_count = await db.scalar(select(func.count()).select_from(Question).where(Question.id.in_(question_ids)))
    if q_count != len(question_ids):
        raise HTTPException(400, "Some question_ids do not exist")

    now = datetime.now(timezone.utc)

    # NEW: Create the batch
    batch = SurveyBatch(
        subject_user_id=payload.subject_user_id,
        review_type=payload.review_type,
        title=payload.title,
        created_at=now,
        deadline=payload.deadline,
        notifications_before=payload.notifications_before,
        anonymous=payload.anonymous,
        expected_respondents=len(reviewers),
    )
    db.add(batch)
    await db.flush()  # get batch.id

    # Create per-respondent surveys within this batch
    created: List[InitiatedPersonalSurvey] = []
    for respondent_id in reviewers:
        survey = Survey(
            batch_id=batch.id,
            subject_user_id=payload.subject_user_id,
            respondent_user_id=respondent_id,
            created_at=now,
            deadline=payload.deadline,
            notifications_before=payload.notifications_before,
            anonymous=payload.anonymous,
            review_type=payload.review_type,
            title=payload.title,
        )
        db.add(survey)
        await db.flush()

        db.add_all([SurveyQuestion(survey_id=survey.id, question_id=qid) for qid in question_ids])

        token = await create_link_token(db, survey_id=survey.id, respondent_user_id=respondent_id)
        created.append(
            InitiatedPersonalSurvey(
                surveyId=f"srv_{survey.id}", respondent_user_id=respondent_id, linkToken=token
            )
        )

    await db.commit()
    return InitiateSurveyBatchOut(batch_created=created, questions_count=len(question_ids))


# # Mount under your existing FastAPI app
# app.include_router(v1)

# =========================
# WIRE INTO EXISTING APP
# =========================

# # If running inside main.py, you already have `app`. If importing, mount onto the existing app.
# app: FastAPI = _existing_app
# app.include_router(router)

# =========================
# UTIL: simple token factory (optional helper you can call elsewhere)
# =========================
async def create_link_token(db: AsyncSession, survey_id: int, respondent_user_id: int) -> str:
    token = secrets.token_urlsafe(24)
    db.add(
        SurveyLinkToken(
            token=token,
            survey_id=survey_id,
            respondent_user_id=respondent_user_id,
            created_at=_now_utc(),
            is_revoked=False,
        )
    )
    await db.commit()
    return token


__all__ = ["v1"]
