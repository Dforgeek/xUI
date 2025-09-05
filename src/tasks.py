import asyncio
from app.llm_client import summarize_responses
from app import crud
from sqlalchemy.ext.asyncio import AsyncSession

# заглушки "отправки" — замените интеграцией с телеграм-воркером
async def send_survey_to_user(session: AsyncSession, invitation_id: int, user_telegram_id: int):
    # здесь реальная логика: POST к воркеру телеграм, kafka, etc.
    # Для демо — лог и записать sent_at
    print(f"[send_survey_to_user] invitation={invitation_id} -> telegram_id={user_telegram_id}")
    # mark sent_at
    from sqlalchemy import func, update
    q = update(crud.models.Invitation).where(crud.models.Invitation.id == invitation_id).values(sent_at=func.now())
    await session.execute(q)
    await session.commit()

async def send_reminder_to_user(session: AsyncSession, invitation_id: int, user_telegram_id: int):
    print(f"[send_reminder_to_user] REMINDER invitation={invitation_id} -> telegram_id={user_telegram_id}")
    await crud.set_reminder_sent(session, invitation_id)

async def run_send_all(session: AsyncSession, survey_id: int):
    # отправить всем приглашения
    invitations = await session.execute(
        crud.select(crud.models.Invitation).where(crud.models.Invitation.survey_id == survey_id)
    )
    invitations = invitations.scalars().all()
    tasks = []
    for inv in invitations:
        tasks.append(send_survey_to_user(session, inv.id, inv.user.telegram_id))
    await asyncio.gather(*tasks)

async def remind_unanswered(session: AsyncSession, survey_id: int):
    unanswered = await crud.get_unanswered_invitations(session, survey_id)
    for inv in unanswered:
        # отправить напоминание
        await send_reminder_to_user(session, inv.id, inv.user.telegram_id)

async def finalize_and_summarize(session: AsyncSession, survey_id: int):
    responses = await crud.get_responses_for_survey(session, survey_id)
    texts = [r.content for r in responses]
    summary = await summarize_responses(texts)
    await crud.set_survey_summary(session, survey_id, summary)
    return summary

