from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from main import (
    get_session,
    Survey, SurveyBatch, SurveyQuestion, Question,
    ReviewSummary, UserInfo
)
from sqlalchemy.dialects.postgresql import JSONB

v1 = APIRouter(prefix="/v1", tags=["Summaries"])

def _now() -> datetime:
    return datetime.now(timezone.utc)

# --------- Schemas ---------
class BatchProgressOut(BaseModel):
    batchId: int
    subject_user_id: int
    expectedRespondents: int
    responsesReceived: int
    deadlineISO: str
    allResponded: bool
    deadlinePassed: bool
    readyToSummarize: bool

class SummaryCreateIn(BaseModel):
    batch_id: int
    model_name: Optional[str] = None
    prompt_version: Optional[int] = None

class SummaryUpdateIn(BaseModel):
    status: Optional[str] = Field(None, description="queued|running|succeeded|failed")
    model_name: Optional[str] = None
    prompt_version: Optional[int] = None
    summary_text: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class SummaryOut(BaseModel):
    id: int
    batch_id: int
    subject_user_id: int
    status: str
    model_name: Optional[str] = None
    prompt_version: Optional[int] = None
    summary_text: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    
class BatchListItem(BaseModel):
    id: int
    subject_user_id: int
    review_type: str
    title: Optional[str] = None
    createdAtISO: str
    deadlineISO: str
    expectedRespondents: int
    responsesReceived: int
    readyToSummarize: bool

# --------- Helpers ---------
async def _batch_progress(db: AsyncSession, batch_id: int) -> BatchProgressOut:
    batch = await db.scalar(select(SurveyBatch).where(SurveyBatch.id == batch_id))
    if not batch:
        raise HTTPException(404, "Batch not found")

    expected = int(batch.expected_respondents)
    table = ReviewSummary.metadata.tables.get("survey_response")  # -> Table | None
    select_from_obj = table if table is not None else Survey  # ORM сущность тоже ок


    responses = await db.scalar(
        select(func.count())
        .select_from(select_from_obj)  # fallback
        .select_from(Survey)
        .join_from(Survey, select_from_obj, and_(False))  # no-op in PyCharm
    )
    # The above is just to placate static tools; real query below:
    responses = await db.scalar(
        select(func.count())
        .select_from(Survey)
        .join_from(Survey, ReviewSummary.__table__.metadata.tables["survey_response"],
                   Survey.id == ReviewSummary.__table__.metadata.tables["survey_response"].c.survey_id)
        .where(Survey.batch_id == batch_id)
    )

    responses = int(responses or 0)
    now = _now()
    all_responded = responses >= expected
    deadline_passed = now > batch.deadline
    ready = all_responded or deadline_passed

    return BatchProgressOut(
        batchId=batch.id,
        subject_user_id=batch.subject_user_id,
        expectedRespondents=expected,
        responsesReceived=responses,
        deadlineISO=batch.deadline.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        allResponded=all_responded,
        deadlinePassed=deadline_passed,
        readyToSummarize=ready,
    )

async def _ensure_summary_row(db: AsyncSession, batch_id: int) -> ReviewSummary:
    existing = await db.scalar(select(ReviewSummary).where(ReviewSummary.batch_id == batch_id))
    if existing:
        return existing
    batch = await db.scalar(select(SurveyBatch).where(SurveyBatch.id == batch_id))
    if not batch:
        raise HTTPException(404, "Batch not found")
    rs = ReviewSummary(
        batch_id=batch_id,
        subject_user_id=batch.subject_user_id,
        status="queued",
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(rs)
    await db.commit()
    await db.refresh(rs)
    return rs

# --------- Endpoints ---------
@v1.get("/batches/{batchId}/progress", response_model=BatchProgressOut)
async def get_batch_progress(batchId: int, db: AsyncSession = Depends(get_session)):
    return await _batch_progress(db, batchId)

@v1.get("/summaries", response_model=List[SummaryOut])
async def list_summaries(
    subject_user_id: Optional[int] = Query(None),
    batch_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    q = select(ReviewSummary).order_by(ReviewSummary.created_at.desc()).limit(limit).offset(offset)
    if subject_user_id is not None:
        q = q.where(ReviewSummary.subject_user_id == subject_user_id)
    if batch_id is not None:
        q = q.where(ReviewSummary.batch_id == batch_id)
    if status is not None:
        q = q.where(ReviewSummary.status == status)
    rows = (await db.execute(q)).scalars().all()
    return [SummaryOut(
        id=r.id, batch_id=r.batch_id, subject_user_id=r.subject_user_id, status=r.status,
        model_name=r.model_name, prompt_version=r.prompt_version, summary_text=r.summary_text,
        stats=r.stats, error=r.error, created_at=r.created_at, updated_at=r.updated_at,
        started_at=r.started_at, completed_at=r.completed_at
    ) for r in rows]

@v1.get("/summaries/{summaryId}", response_model=SummaryOut)
async def get_summary(summaryId: int, db: AsyncSession = Depends(get_session)):
    r = await db.scalar(select(ReviewSummary).where(ReviewSummary.id == summaryId))
    if not r:
        raise HTTPException(404, "Summary not found")
    return SummaryOut(
        id=r.id, batch_id=r.batch_id, subject_user_id=r.subject_user_id, status=r.status,
        model_name=r.model_name, prompt_version=r.prompt_version, summary_text=r.summary_text,
        stats=r.stats, error=r.error, created_at=r.created_at, updated_at=r.updated_at,
        started_at=r.started_at, completed_at=r.completed_at
    )

@v1.post("/summaries", response_model=SummaryOut, status_code=201)
async def create_summary(payload: SummaryCreateIn, db: AsyncSession = Depends(get_session)):
    prog = await _batch_progress(db, payload.batch_id)
    rs = await _ensure_summary_row(db, payload.batch_id)
    # Keep queued unless caller wants to immediately mark running; caller can PATCH
    if payload.model_name is not None: rs.model_name = payload.model_name
    if payload.prompt_version is not None: rs.prompt_version = payload.prompt_version
    rs.updated_at = _now()
    await db.commit(); await db.refresh(rs)
    return await get_summary(rs.id, db)

@v1.patch("/summaries/{summaryId}", response_model=SummaryOut)
async def update_summary(summaryId: int, payload: SummaryUpdateIn, db: AsyncSession = Depends(get_session)):
    rs = await db.scalar(select(ReviewSummary).where(ReviewSummary.id == summaryId))
    if not rs:
        raise HTTPException(404, "Summary not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rs, k, v)
    rs.updated_at = _now()
    await db.commit(); await db.refresh(rs)
    return await get_summary(rs.id, db)

@v1.delete("/summaries/{summaryId}", status_code=204)
async def delete_summary(summaryId: int, db: AsyncSession = Depends(get_session)):
    rs = await db.scalar(select(ReviewSummary).where(ReviewSummary.id == summaryId))
    if not rs:
        raise HTTPException(404, "Summary not found")
    await db.delete(rs); await db.commit()
    return

@v1.get("/summaries/ready", response_model=List[SummaryOut])
async def list_ready_summaries(db: AsyncSession = Depends(get_session)):
    # Return batches that are ready (progress.readyToSummarize) and have a summary row in queued/running/absent
    batch_rows = (await db.execute(select(SurveyBatch.id))).scalars().all()
    out: List[SummaryOut] = []
    for bid in batch_rows:
        prog = await _batch_progress(db, bid)
        if not prog.readyToSummarize:
            continue
        rs = await db.scalar(select(ReviewSummary).where(ReviewSummary.batch_id == bid))
        if not rs:
            rs = await _ensure_summary_row(db, bid)
        if rs.status in ("queued", "running"):
            out.append(await get_summary(rs.id, db))
    return out

# -----------------------------
# Reference synchronous compute
# -----------------------------
class ComputeIn(BaseModel):
    batch_id: int
    model_name: Optional[str] = None
    prompt_version: Optional[int] = None

@v1.post("/summaries/compute", response_model=SummaryOut)
async def compute_summary(payload: ComputeIn, db: AsyncSession = Depends(get_session)):
    # Preconditions
    prog = await _batch_progress(db, payload.batch_id)
    if not prog.readyToSummarize:
        raise HTTPException(409, "Batch not ready to summarize")

    rs = await _ensure_summary_row(db, payload.batch_id)
    rs.status = "running"
    if payload.model_name: rs.model_name = payload.model_name
    if payload.prompt_version is not None: rs.prompt_version = payload.prompt_version
    rs.started_at = _now(); rs.updated_at = rs.started_at
    await db.commit(); await db.refresh(rs)

    # Aggregate answers across all surveys in the batch
    #  - avg rating per question_id
    #  - collect text answers
    surveys = (await db.execute(select(Survey.id).where(Survey.batch_id == payload.batch_id))).scalars().all()
    if not surveys:
        rs.status = "failed"; rs.error = "No surveys in batch"; rs.completed_at = _now(); rs.updated_at = rs.completed_at
        await db.commit(); await db.refresh(rs)
        return await get_summary(rs.id, db)

    # Fetch responses JSONB
    resp_table = ReviewSummary.__table__.metadata.tables["survey_response"]
    rows = (await db.execute(
        select(resp_table.c.answers)
        .where(resp_table.c.survey_id.in_(surveys))
    )).all()

    # Fetch questions (we need text by qid)
    q_rows = (await db.execute(
        select(Question.id, Question.question_text, Question.question_type, Question.answer_fields)
        .join(SurveyQuestion, SurveyQuestion.question_id == Question.id)
        .where(SurveyQuestion.survey_id.in_(surveys))
        .group_by(Question.id, Question.question_text, Question.question_type, Question.answer_fields)
        .order_by(Question.id)
    )).all()
    q_map = {qid: (qtext, qtype, afields) for (qid, qtext, qtype, afields) in q_rows}

    import statistics
    ratings: Dict[int, List[int]] = {}
    texts: Dict[int, List[str]] = {}

    for (answers,) in rows:
        if not answers: continue
        for k, v in answers.items():
            if not k.startswith("q"): continue
            try:
                qid = int(k[1:])
            except Exception:
                continue
            qmeta = q_map.get(qid)
            if not qmeta:
                continue
            _, qtype, _ = qmeta
            if qtype == 1:
                if isinstance(v, int):
                    ratings.setdefault(qid, []).append(v)
                elif isinstance(v, str) and v.isdigit():
                    ratings.setdefault(qid, []).append(int(v))
            else:
                if isinstance(v, str) and v.strip():
                    texts.setdefault(qid, []).append(v.strip())

    stats: Dict[str, Any] = {"per_question": {}}
    lines: List[str] = []
    for qid, (qtext, qtype, _) in q_map.items():
        entry: Dict[str, Any] = {"question_id": qid, "question": qtext, "type": qtype}
        if qtype == 1:
            vals = ratings.get(qid, [])
            if vals:
                entry["n"] = len(vals)
                entry["avg"] = round(sum(vals) / len(vals), 2)
                entry["median"] = statistics.median(vals)
                lines.append(f"- {qtext} — avg {entry['avg']} (n={entry['n']})")
            else:
                entry["n"] = 0
                lines.append(f"- {qtext} — no ratings")
        else:
            comms = texts.get(qid, [])
            entry["n"] = len(comms)
            if comms:
                sample = "; ".join(comms[:3])
                entry["sample"] = sample
                lines.append(f"- {qtext} — {len(comms)} comments (e.g., {sample})")
            else:
                lines.append(f"- {qtext} — no comments")
        stats["per_question"][str(qid)] = entry

    # Simple reference summary text (LLM can replace later)
    header = f"360° Summary for subject {prog.subject_user_id} (batch {prog.batchId})\n"
    header += f"Responses: {prog.responsesReceived}/{prog.expectedRespondents}; Deadline: {prog.deadlineISO}\n\n"
    summary_text = header + "\n".join(lines) if lines else header + "No data."

    rs.summary_text = summary_text
    rs.stats = stats
    rs.status = "succeeded"
    rs.completed_at = _now()
    rs.updated_at = rs.completed_at

    await db.commit(); await db.refresh(rs)
    return await get_summary(rs.id, db)


@v1.get("/batches", response_model=List[BatchListItem])
async def list_batches(
    subject_user_id: Optional[int] = Query(None),
    readyOnly: bool = Query(False, description="Return only batches ready to summarize"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    # 1) load batches
    q = (
        select(SurveyBatch)
        .order_by(SurveyBatch.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if subject_user_id is not None:
        q = q.where(SurveyBatch.subject_user_id == subject_user_id)

    batches: List[SurveyBatch] = (await db.execute(q)).scalars().all()
    if not batches:
        return []

    batch_ids = [b.id for b in batches]

    # 2) responses count per batch (via survey_response table without ORM class)
    resp_table = ReviewSummary.__table__.metadata.tables["survey_response"]
    counts_rows = (
        await db.execute(
            select(Survey.batch_id, func.count())
            .select_from(Survey)
            .join(resp_table, Survey.id == resp_table.c.survey_id)
            .where(Survey.batch_id.in_(batch_ids))
            .group_by(Survey.batch_id)
        )
    ).all()
    counts_map = {bid: int(cnt) for bid, cnt in counts_rows}

    # 3) build output
    now = datetime.now(timezone.utc)
    out: List[BatchListItem] = []
    for b in batches:
        responses = counts_map.get(b.id, 0)
        ready = (responses >= int(b.expected_respondents)) or (now > b.deadline)
        if readyOnly and not ready:
            continue

        out.append(
            BatchListItem(
                id=b.id,
                subject_user_id=b.subject_user_id,
                review_type=b.review_type,
                title=b.title,
                createdAtISO=b.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                deadlineISO=b.deadline.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                expectedRespondents=int(b.expected_respondents),
                responsesReceived=responses,
                readyToSummarize=ready,
            )
        )
    return out
