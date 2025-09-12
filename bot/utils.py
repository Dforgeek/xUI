from pathlib import Path
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")

BTN_CREATE_POLL = "Создать опрос по пользователю"
BTN_SUMMARY = "Вызвать суммаризацию о пользователе"
BTN_CANCEL = "Отмена"
BTN_REGISTER = "Зарегистрировать пользователей"
USERS_FILE = Path("users.json")
API_BASE = os.getenv("API_BASE")
FRONTEND_BASE = os.getenv("FRONTEND_BASE")
BTN_HR = "HR: Опросы"
BTN_LIST_USERS = "Список пользователей"
BTN_SUMMARY_Q = "Суммаризация по вопросу"
