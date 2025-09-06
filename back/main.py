import enum
from datetime import datetime, timezone
from typing import List, Optional, Literal, Dict, Any

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Query
from fastapi import status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from sqlalchemy import (
    BigInteger, SmallInteger, String, Text, ARRAY, Integer, ForeignKey,
    Index, UniqueConstraint, select, func, and_, literal_column
)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, relationship

# =========================
# Settings
# =========================

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    CORS_ALLOW_ORIGINS: List[str] = ["*"]

settings = Settings()

# =========================
# DB / ORM
# =========================

class Base(DeclarativeBase):
    pass

class UserInfo(Base):
    __tablename__ = "user_info"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    post: Mapped[int] = mapped_column(Integer, nullable=False)
    command_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

class Block(Base):
    __tablename__ = "block"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    block_name: Mapped[str] = mapped_column(String(255), nullable=False)

class Question(Base):
    __tablename__ = "question"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    block_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("block.id"), nullable=False, index=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    answer_fields: Mapped[str] = mapped_column(Text, nullable=False)

    block: Mapped[Block] = relationship()

class SurveyPreset(Base):
    __tablename__ = "survey_preset"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    questions: Mapped[List[int]] = mapped_column(ARRAY(BigInteger), nullable=False)

class Survey(Base):
    __tablename__ = "survey"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    deadline: Mapped[datetime] = mapped_column(nullable=False)
    notifications_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # расширенная настройка анонимности — добавим виртуально через API/метаданные, не меняя схему:
    # хранить будем в отдельной таблице-псевдонастройке, чтобы не ломать вашу схему
    # но чтобы сохранить строго вашу схему — положим флаг в notifications_before старшим битом.
    # Ниже реализуем хранение флага в таблице survey_meta.

class SurveyQuestion(Base):
    __tablename__ = "survey_question"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    survey_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (UniqueConstraint("question_id", "survey_id", name="survey_question_survey_id_question_id_idx"),)

class SurveyRespondent(Base):
    __tablename__ = "survey_respondent"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    survey_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "survey_id", name="survey_respondent_user_id_survey_id_idx"),)

class SurveyAnswer(Base):
    __tablename__ = "survey_answer"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    survey_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    question_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)

# Небольшая вспомогательная таблица для метаданных опроса (анонимность, тип 180/360, имя пресета)
from sqlalchemy import JSON
class SurveyMeta(Base):
    __tablename__ = "survey_meta"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    survey_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("survey.id"), nullable=False, unique=True, index=True)
    data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

# =========================
# Engine / Session
# =========================

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

# =========================
# Schemas (Pydantic)
# =========================

class EmployeeIn(BaseModel):
    telegram_id: int
    post: int
    command_id: int

class Employee(EmployeeIn):
    id: int

class BlockIn(BaseModel):
    block_name: str

class BlockOut(BlockIn):
    id: int

class QuestionIn(BaseModel):
    block_id: int
    question_text: str
    question_type: int = Field(..., description="Например: 0=текст, 1=шкала, 2=множественный выбор")
    answer_fields: str = Field(..., description="Схема полей/вариантов в JSON/CSV и т.п.")

class QuestionOut(QuestionIn):
    id: int

class PresetIn(BaseModel):
    questions: List[int]

class PresetOut(PresetIn):
    id: int

ReviewType = Literal["180", "360"]

class InitiateSurveyIn(BaseModel):
    subject_user_id: int
    reviewer_user_ids: List[int] = Field(default_factory=list, description="включая коллег и руководителя; для 360 самооценка добавится автоматически")
    review_type: ReviewType
    preset_id: Optional[int] = None
    selected_block_ids: Optional[List[int]] = None
    additional_question_ids: Optional[List[int]] = None
    deadline: datetime
    notifications_before: int = 0
    anonymous: bool = False
    preset_label: Optional[str] = None  # чтобы понимать какой пресет использовали (для отчётов)

class SurveyOut(BaseModel):
    id: int
    subject_user_id: int
    created_at: datetime
    deadline: datetime
    notifications_before: int
    anonymous: bool
    review_type: ReviewType
    participants_count: int
    questions_count: int
    preset_label: Optional[str] = None

class SurveyListItem(BaseModel):
    id: int
    created_at: datetime
    deadline: datetime
    participants_count: int
    completed_count: int
    status: Literal["pending", "in_progress", "completed"]
    reviewer_user_ids: List[int]

class AnswerIn(BaseModel):
    user_id: int
    question_id: int
    answer: str

class QuestionAggregate(BaseModel):
    question_id: int
    question_text: str
    answers: List[Dict[str, Any]]

class SurveyAggregateOut(BaseModel):
    survey_id: int
    anonymous: bool
    review_type: ReviewType
    total_respondents: int
    responded: int
    by_question: List[QuestionAggregate]

# =========================
# App
# =========================

app = FastAPI(title="360 Survey Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Employees
# =========================

@app.post("/employees", response_model=Employee, status_code=201)
async def create_employee(payload: EmployeeIn, db: AsyncSession = Depends(get_session)):
    obj = UserInfo(**payload.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return Employee(id=obj.id, **payload.model_dump())

@app.get("/employees", response_model=List[Employee])
async def list_employees(
    db: AsyncSession = Depends(get_session),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    res = await db.execute(select(UserInfo).limit(limit).offset(offset))
    rows = res.scalars().all()
    return [Employee(id=r.id, telegram_id=r.telegram_id, post=r.post, command_id=r.command_id) for r in rows]

@app.put("/employees/{employee_id}", response_model=Employee)
async def update_employee(employee_id: int, payload: EmployeeIn, db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(UserInfo).where(UserInfo.id == employee_id))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(404, "Employee not found")
    for k, v in payload.model_dump().items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    return Employee(id=obj.id, telegram_id=obj.telegram_id, post=obj.post, command_id=obj.command_id)

@app.delete("/employees/{employee_id}", status_code=204)
async def delete_employee(employee_id: int, db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(UserInfo).where(UserInfo.id == employee_id))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(404, "Employee not found")
    await db.delete(obj)
    await db.commit()
    return

# = Excel import =
from openpyxl import load_workbook
@app.post("/employees/import-xlsx", response_model=Dict[str, int])
async def import_employees_xlsx(file: UploadFile = File(...), db: AsyncSession = Depends(get_session)):
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Upload an .xlsx file")
    wb = load_workbook(filename=file.file, read_only=True)
    ws = wb.active
    # ожидаем столбцы: telegram_id, post, command_id (в первой строке — заголовки)
    headers = [str(c.value).strip() if c.value is not None else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    try:
        idx_tg = headers.index("telegram_id")
        idx_post = headers.index("post")
        idx_cmd = headers.index("command_id")
    except ValueError:
        raise HTTPException(400, "Header row must contain telegram_id, post, command_id")
    created = 0
    for row in ws.iter_rows(min_row=2):
        tg = row[idx_tg].value
        post = row[idx_post].value
        cmd = row[idx_cmd].value
        if tg is None or post is None or cmd is None:
            continue
        db.add(UserInfo(telegram_id=int(tg), post=int(post), command_id=int(cmd)))
        created += 1
    await db.commit()
    return {"created": created}

# =========================
# Blocks & Questions & Presets (управление библиотекой)
# =========================

@app.post("/blocks", response_model=BlockOut, status_code=201)
async def create_block(payload: BlockIn, db: AsyncSession = Depends(get_session)):
    obj = Block(**payload.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return BlockOut(id=obj.id, **payload.model_dump())

@app.get("/blocks", response_model=List[BlockOut])
async def list_blocks(db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(Block))
    return [BlockOut(id=b.id, block_name=b.block_name) for b in res.scalars().all()]

@app.post("/questions", response_model=QuestionOut, status_code=201)
async def create_question(payload: QuestionIn, db: AsyncSession = Depends(get_session)):
    # ensure block exists
    exists = await db.scalar(select(func.count()).select_from(Block).where(Block.id == payload.block_id))
    if not exists:
        raise HTTPException(400, "block_id not found")
    obj = Question(**payload.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return QuestionOut(id=obj.id, **payload.model_dump())

@app.put("/questions/{question_id}", response_model=QuestionOut)
async def update_question(question_id: int, payload: QuestionIn, db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(Question).where(Question.id == question_id))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(404, "Question not found")
    for k, v in payload.model_dump().items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    return QuestionOut(id=obj.id, **payload.model_dump())

@app.get("/questions", response_model=List[QuestionOut])
async def list_questions(
    db: AsyncSession = Depends(get_session),
    block_id: Optional[int] = None
):
    stmt = select(Question)
    if block_id:
        stmt = stmt.where(Question.block_id == block_id)
    res = await db.execute(stmt)
    return [QuestionOut(id=q.id, block_id=q.block_id, question_text=q.question_text,
                        question_type=q.question_type, answer_fields=q.answer_fields)
            for q in res.scalars().all()]

@app.post("/presets", response_model=PresetOut, status_code=201)
async def create_preset(payload: PresetIn, db: AsyncSession = Depends(get_session)):
    # validate questions exist
    if payload.questions:
        count = await db.scalar(select(func.count()).select_from(Question).where(Question.id.in_(payload.questions)))
        if count != len(payload.questions):
            raise HTTPException(400, "Some question IDs do not exist")
    obj = SurveyPreset(questions=payload.questions)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return PresetOut(id=obj.id, questions=obj.questions)

@app.put("/presets/{preset_id}", response_model=PresetOut)
async def update_preset(preset_id: int, payload: PresetIn, db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(SurveyPreset).where(SurveyPreset.id == preset_id))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(404, "Preset not found")
    obj.questions = payload.questions
    await db.commit()
    await db.refresh(obj)
    return PresetOut(id=obj.id, questions=obj.questions)

@app.get("/presets", response_model=List[PresetOut])
async def list_presets(db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(SurveyPreset))
    return [PresetOut(id=p.id, questions=p.questions) for p in res.scalars().all()]

# =========================
# Survey init / list / answers / aggregate
# =========================

async def build_question_ids(
    db: AsyncSession,
    preset_id: Optional[int],
    selected_block_ids: Optional[List[int]],
    additional_question_ids: Optional[List[int]],
) -> List[int]:
    qids: List[int] = []
    if preset_id:
        preset = await db.scalar(select(SurveyPreset).where(SurveyPreset.id == preset_id))
        if not preset:
            raise HTTPException(400, "preset_id not found")
        qids.extend(preset.questions)
    if selected_block_ids:
        res = await db.execute(select(Question.id).where(Question.block_id.in_(selected_block_ids)))
        qids.extend([r[0] for r in res.all()])
    if additional_question_ids:
        qids.extend(additional_question_ids)
    # уникализируем, сохраняем порядок
    seen = set()
    ordered = []
    for q in qids:
        if q not in seen:
            seen.add(q)
            ordered.append(q)
    if not ordered:
        raise HTTPException(400, "No questions selected")
    return ordered

@app.post("/surveys/initiate", response_model=SurveyOut, status_code=201)
async def initiate_survey(payload: InitiateSurveyIn, db: AsyncSession = Depends(get_session)):
    # validate subject
    subj_exists = await db.scalar(select(func.count()).select_from(UserInfo).where(UserInfo.id == payload.subject_user_id))
    if not subj_exists:
        raise HTTPException(400, "subject_user_id not found")

    # validate reviewers
    if payload.reviewer_user_ids:
        count = await db.scalar(select(func.count()).select_from(UserInfo).where(UserInfo.id.in_(payload.reviewer_user_ids)))
        if count != len(payload.reviewer_user_ids):
            raise HTTPException(400, "Some reviewer_user_ids do not exist")

    # build questions
    question_ids = await build_question_ids(db, payload.preset_id, payload.selected_block_ids, payload.additional_question_ids)

    now = datetime.now(timezone.utc)
    survey = Survey(
        subject_user_id=payload.subject_user_id,
        created_at=now,
        deadline=payload.deadline,
        notifications_before=payload.notifications_before,
    )
    db.add(survey)
    await db.flush()  # get survey.id

    # link questions
    db.add_all([SurveyQuestion(survey_id=survey.id, question_id=qid) for qid in question_ids])

    # respondents: reviewers + (self if 360)
    respondents = set(payload.reviewer_user_ids or [])
    if payload.review_type == "360":
        respondents.add(payload.subject_user_id)
    db.add_all([SurveyRespondent(survey_id=survey.id, user_id=uid) for uid in respondents])

    # meta
    meta = {
        "anonymous": payload.anonymous,
        "review_type": payload.review_type,
        "preset_label": payload.preset_label,
        "preset_id": payload.preset_id,
        "selected_block_ids": payload.selected_block_ids or [],
        "additional_question_ids": payload.additional_question_ids or [],
    }
    db.add(SurveyMeta(survey_id=survey.id, data=meta))

    await db.commit()
    await db.refresh(survey)

    return SurveyOut(
        id=survey.id,
        subject_user_id=survey.subject_user_id,
        created_at=survey.created_at,
        deadline=survey.deadline,
        notifications_before=survey.notifications_before,
        anonymous=payload.anonymous,
        review_type=payload.review_type,
        participants_count=len(respondents),
        questions_count=len(question_ids),
        preset_label=payload.preset_label
    )

@app.get("/surveys/by-subject/{user_id}", response_model=List[SurveyListItem])
async def list_surveys_by_subject(user_id: int, db: AsyncSession = Depends(get_session)):
    # fetch surveys
    res = await db.execute(select(Survey).where(Survey.subject_user_id == user_id).order_by(Survey.created_at.desc()))
    surveys = res.scalars().all()
    out: List[SurveyListItem] = []
    for s in surveys:
        # participants
        cnt_participants = await db.scalar(select(func.count()).select_from(SurveyRespondent).where(SurveyRespondent.survey_id == s.id))
        # who are they
        reviewers_res = await db.execute(select(SurveyRespondent.user_id).where(SurveyRespondent.survey_id == s.id))
        reviewer_ids = [r[0] for r in reviewers_res.all()]
        # completed: считаем «ответившим» тех, у кого есть хотя бы один ответ
        resp_count = await db.scalar(
            select(func.count(func.distinct(SurveyAnswer.user_id)))
            .where(SurveyAnswer.survey_id == s.id)
        )
        status_str: Literal["pending", "in_progress", "completed"]
        if resp_count == 0:
            status_str = "pending"
        elif resp_count < cnt_participants:
            status_str = "in_progress"
        else:
            status_str = "completed"
        out.append(SurveyListItem(
            id=s.id, created_at=s.created_at, deadline=s.deadline,
            participants_count=cnt_participants, completed_count=resp_count,
            status=status_str, reviewer_user_ids=reviewer_ids
        ))
    return out

@app.post("/surveys/{survey_id}/answers", status_code=201)
async def submit_answer(survey_id: int, payload: AnswerIn, db: AsyncSession = Depends(get_session)):
    # validate respondent belongs to survey
    belongs = await db.scalar(
        select(func.count()).select_from(SurveyRespondent)
        .where(and_(SurveyRespondent.survey_id == survey_id, SurveyRespondent.user_id == payload.user_id))
    )
    if not belongs:
        raise HTTPException(400, "User is not a respondent of this survey")
    # validate question belongs to survey
    q_ok = await db.scalar(
        select(func.count()).select_from(SurveyQuestion)
        .where(and_(SurveyQuestion.survey_id == survey_id, SurveyQuestion.question_id == payload.question_id))
    )
    if not q_ok:
        raise HTTPException(400, "Question is not part of this survey")
    db.add(SurveyAnswer(survey_id=survey_id, user_id=payload.user_id,
                        question_id=payload.question_id, answer=payload.answer))
    await db.commit()
    return {"ok": True}

@app.get("/surveys/{survey_id}/aggregate", response_model=SurveyAggregateOut)
async def aggregate_survey(survey_id: int, db: AsyncSession = Depends(get_session)):
    # meta
    meta = await db.scalar(select(SurveyMeta).where(SurveyMeta.survey_id == survey_id))
    if not meta:
        raise HTTPException(404, "Survey not found")
    anonymous = bool(meta.data.get("anonymous", False))
    review_type: ReviewType = meta.data.get("review_type", "180")  # type: ignore

    # counts
    total_resp = await db.scalar(select(func.count()).select_from(SurveyRespondent).where(SurveyRespondent.survey_id == survey_id))
    responded = await db.scalar(select(func.count(func.distinct(SurveyAnswer.user_id))).where(SurveyAnswer.survey_id == survey_id))

    # questions
    q_res = await db.execute(
        select(Question.id, Question.question_text)
        .join(SurveyQuestion, SurveyQuestion.question_id == Question.id)
        .where(SurveyQuestion.survey_id == survey_id)
        .order_by(Question.id)
    )
    q_map = {qid: qtext for qid, qtext in q_res.all()}

    # answers grouped by question
    a_res = await db.execute(
        select(SurveyAnswer.question_id, SurveyAnswer.user_id, SurveyAnswer.answer)
        .where(SurveyAnswer.survey_id == survey_id)
        .order_by(SurveyAnswer.question_id, SurveyAnswer.user_id)
    )
    by_q: Dict[int, List[Dict[str, Any]]] = {}
    for qid, uid, ans in a_res.all():
        item = {"answer": ans}
        if not anonymous:
            item["user_id"] = uid
        by_q.setdefault(qid, []).append(item)

    agg = []
    for qid, qtext in q_map.items():
        agg.append(QuestionAggregate(
            question_id=qid,
            question_text=qtext,
            answers=by_q.get(qid, [])
        ))

    return SurveyAggregateOut(
        survey_id=survey_id,
        anonymous=anonymous,
        review_type=review_type,
        total_respondents=total_resp or 0,
        responded=responded or 0,
        by_question=agg
    )

# =========================
# Health
# =========================
@app.get("/healthz")
async def health():
    return {"status": "ok"}
