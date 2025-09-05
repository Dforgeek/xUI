import asyncio
from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app import database, models, schemas, crud, tasks
from app.database import get_session, create_db_and_tables
from typing import List
import uvicorn

app = FastAPI(title="360-survey-service")

@app.on_event("startup")
async def on_startup():
    await create_db_and_tables()
    # optional: seed test data for convenience (only if empty)
    async with database.AsyncSessionLocal() as session:
        res = await session.execute(models.User.__table__.select().limit(1))
        if res.first() is None:
            # seed sample department and users
            dept = models.Department(name="Engineering")
            session.add(dept)
            await session.flush()
            mgr = models.User(name="Manager Ivan", telegram_id=1001, is_manager=True, department_id=dept.id)
            u1 = models.User(name="Alice", telegram_id=2001, is_manager=False, department_id=dept.id)
            u2 = models.User(name="Bob", telegram_id=2002, is_manager=False, department_id=dept.id)
            session.add_all([mgr, u1, u2])
            await session.commit()
            print("Seeded sample data.")

@app.post("/start-360", response_model=schemas.SurveyOut)
async def start_360(req: schemas.Start360Request, background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_session)):
    # 1) найти менеджера по telegram id
    manager = await crud.get_user_by_telegram(session, req.manager_telegram_id)
    if not manager or not manager.is_manager:
        raise HTTPException(status_code=404, detail="Manager not found")
    if not manager.department_id:
        raise HTTPException(status_code=400, detail="Manager has no department assigned")
    # 2) собрать всех в отделе (кроме менеджера)
    users = await crud.get_users_by_department(session, manager.department_id)
    employees = [u for u in users if u.id != manager.id]
    # 3) создать survey
    survey = await crud.create_survey(session, manager.id, manager.department_id)
    # 4) создать invitations и запустить асинхронные отправки заглушкой
    for u in employees:
        inv = await crud.create_invitation(session, survey.id, u.id)
        # background отправка (заглушка)
        background_tasks.add_task(tasks.send_survey_to_user, session, inv.id, u.telegram_id)
    return survey

@app.post("/respond")
async def respond(req: schemas.RespondRequest, session: AsyncSession = Depends(get_session)):
    # endpoint для респондента — записать ответ
    # (в реальности ответы придут через форму/телеграм воркер)
    resp = await crud.record_response(session, req.invitation_id, req.content)
    return {"status": "ok", "response_id": resp.id}

@app.post("/remind/{survey_id}")
async def remind(survey_id: int, background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_session)):
    # триггер для отправки напоминаний незавершившимся
    # ставим статус reminding
    from sqlalchemy import update
    await session.execute(update(models.Survey).where(models.Survey.id == survey_id).values(status="reminding"))
    await session.commit()
    background_tasks.add_task(tasks.remind_unanswered, session, survey_id)
    return {"status": "reminders_scheduled"}

@app.post("/finalize/{survey_id}")
async def finalize(survey_id: int, session: AsyncSession = Depends(get_session)):
    # собрать все ответы и вызвать LLM
    summary = await tasks.finalize_and_summarize(session, survey_id)
    return {"survey_id": survey_id, "summary": summary}

@app.get("/survey/{survey_id}/invitations", response_model=List[schemas.InvitationOut])
async def list_invitations(survey_id: int, session: AsyncSession = Depends(get_session)):
    q = await session.execute(models.Invitation.__table__.select().where(models.Invitation.survey_id == survey_id))
    rows = q.fetchall()
    # простой маппинг — лучше вернуть ORM объекты
    res = []
    for r in rows:
        # r is a RowProxy — map manually
        res.append({
            "id": r.id,
            "survey_id": r.survey_id,
            "user_id": r.user_id,
            "sent_at": r.sent_at,
            "responded_at": r.responded_at,
            "reminder_sent": r.reminder_sent
        })
    return res

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

