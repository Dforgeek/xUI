from pathlib import Path
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")

BTN_CREATE_POLL = "Создать опрос по пользователю"
BTN_SUMMARY = "Вызвать суммаризацию о пользователе"
BTN_CANCEL = "Отмена"
BTN_REGISTER = "Зарегистрировать пользователей"
USERS_FILE = Path("users.json")
API_BASE = "http://localhost:8000"
BTN_HR = "HR: Опросы"
