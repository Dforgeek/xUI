from sqlalchemy import select, insert, update
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from typing import List

async def get_user_by_telegram(session: AsyncSession, telegram_id: int):
    q = select(models.User).where(models.User.telegram_id == telegram_id)
    res = await session.execute(q)
    return res.scalars().first()

async def get_users_by_department(session: AsyncSession, department_id: int):
    q = select(models.User).where(models.User.department_id == department_id)
    res = await session.execute(q)
    return res.scalars().all()

async def create_survey(session: AsyncSession, manager_id: int, department_id: int):
    survey = models.Survey(manager_id=manager_id, department_id=department_id)
    session.add(survey)
    await session.commit()
    await session.refresh(survey)
    return survey

async def create_invitation(session: AsyncSession, survey_id: int, user_id: int):
    inv = models.Invitation(survey_id=survey_id, user_id=user_id)
    session.add(inv)
    await session.commit()
    await session.refresh(inv)
    return inv

async def mark_invitation_sent(session: AsyncSession, invitation_id: int):
    q = update(models.Invitation).where(models.Invitation.id == invitation_id).values(sent_at=func.now())
    await session.execute(q)
    await session.commit()

async def record_response(session: AsyncSession, invitation_id: int, content: str):
    resp = models.Response(invitation_id=invitation_id, content=content)
    session.add(resp)
    inv_q = update(models.Invitation).where(models.Invitation.id == invitation_id).values(responded_at=func.now())
    await session.execute(inv_q)
    await session.commit()
    await session.refresh(resp)
    return resp

async def get_unanswered_invitations(session: AsyncSession, survey_id: int):
    q = select(models.Invitation).where(models.Invitation.survey_id == survey_id).where(models.Invitation.responded_at.is_(None))
    res = await session.execute(q)
    return res.scalars().all()

async def set_reminder_sent(session: AsyncSession, invitation_id: int):
    q = update(models.Invitation).where(models.Invitation.id == invitation_id).values(reminder_sent=True)
    await session.execute(q)
    await session.commit()

async def get_responses_for_survey(session: AsyncSession, survey_id: int):
    q = select(models.Response).join(models.Invitation).where(models.Invitation.survey_id == survey_id)
    res = await session.execute(q)
    return res.scalars().all()

async def set_survey_summary(session: AsyncSession, survey_id: int, summary: str):
    q = update(models.Survey).where(models.Survey.id == survey_id).values(summary=summary, status="finalized")
    await session.execute(q)
    await session.commit()

