import asyncio
import logging
from typing import Optional, Tuple, List, Dict, Any
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.exceptions import TelegramAPIError
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import tempfile
import os
import re
from pathlib import Path
import pandas as pd
import urllib
import aiohttp
from utils import (
    BOT_TOKEN,
    BTN_CREATE_POLL,
    BTN_SUMMARY,
    BTN_CANCEL,
    BTN_REGISTER,
    USERS_FILE,
    BTN_HR,
    BTN_LIST_USERS,
    BTN_SUMMARY_Q,
    FRONTEND_BASE
)


# =======================
# Настройки / константы
# =======================
REFACTOR_REGEX = re.compile(r"(?<!\\)([_*\[\]()~`>#+\-=|{}.!])")



def load_users() -> Dict[str, str]:
    """Загрузить список пользователей (chat_id -> username)."""
    if USERS_FILE.exists():
        import json

        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_users(users: Dict[str, str]) -> None:
    """Сохранить словарь пользователей в users.json."""
    import json

    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def register_user(chat_id: int, username: str | None):
    """Добавить/обновить пользователя в файле."""
    users = load_users()
    users[str(chat_id)] = username or ""
    save_users(users)


def get_chat_id_by_username(username: str) -> Optional[int]:
    """Поиск chat_id по username из локального файла."""
    if not username:
        return None
    users = load_users()
    for chat_id, uname in users.items():
        if uname and uname.lower() == username.lower():
            return int(chat_id)
    return None



# =======================
# Шрифты (оставляю вашу реализацию)
# =======================
def find_font_paths() -> Tuple[Optional[str], Optional[str]]:
    candidate_paths = []
    here = Path(__file__).resolve().parent
    candidate_paths.append(here / "fonts" / "DejaVuSans.ttf")
    candidate_paths.append(here / "fonts" / "DejaVuSans-Bold.ttf")
    candidate_paths.append(Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    candidate_paths.append(Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
    candidate_paths.append(Path("/usr/local/share/fonts/DejaVuSans.ttf"))
    candidate_paths.append(Path("/usr/local/share/fonts/DejaVuSans-Bold.ttf"))
    candidate_paths.append(Path("/Library/Fonts/DejaVuSans.ttf"))
    candidate_paths.append(Path("/Library/Fonts/DejaVuSans-Bold.ttf"))
    candidate_paths.append(Path.home() / "Library" / "Fonts" / "DejaVuSans.ttf")
    candidate_paths.append(Path.home() / "Library" / "Fonts" / "DejaVuSans-Bold.ttf")
    candidate_paths.append(Path("C:/Windows/Fonts/DejaVuSans.ttf"))
    candidate_paths.append(Path("C:/Windows/Fonts/DejaVuSans-Bold.ttf"))

    existing = [p for p in candidate_paths if p.exists()]

    regular = None
    bold = None
    for p in existing:
        name = p.name.lower()
        if "bold" in name:
            if bold is None:
                bold = str(p)
        else:
            if regular is None:
                regular = str(p)
    return regular, bold


def register_dejavu_family(font_family_name: str = "DejaVuSansFamily") -> str:
    regular_path, bold_path = find_font_paths()
    if not regular_path:
        # если нет — просто вернём стандартное имя (ReportLab упадёт дальше) — но лучше сообщить.
        raise RuntimeError(
            "Не найден TTF-шрифт DejaVuSans. Положите DejaVuSans.ttf и DejaVuSans-Bold.ttf в ./fonts/ или установите системно."
        )
    reg_name = "DejaVuSans-Regular"
    bold_name = "DejaVuSans-Bold"
    pdfmetrics.registerFont(TTFont(reg_name, regular_path))
    if bold_path:
        pdfmetrics.registerFont(TTFont(bold_name, bold_path))
        registerFontFamily(
            reg_name,
            normal=reg_name,
            bold=bold_name,
            italic=reg_name,
            boldItalic=bold_name,
        )
    else:
        registerFontFamily(
            reg_name,
            normal=reg_name,
            bold=reg_name,
            italic=reg_name,
            boldItalic=reg_name,
        )
    return reg_name


# Попытка зарегистрировать шрифт при запуске (если у вас проблемы — поместите шрифты в ./fonts/)
try:
    FONT_NAME = register_dejavu_family()
except Exception as e:
    # Если шрифты не найдены — логируем, но не прерываем работу (PDF может упасть при сборке)
    FONT_NAME = None
    logging.warning("Не удалось зарегистрировать DejaVuSans: %s", e)


# =======================
# Бизнес-логика
# =======================


def markdown_formatter(text: str) -> str:
    return re.sub(REFACTOR_REGEX, lambda m: "\\" + m.group(1), text)


async def _build_token_url(token: str) -> str:
    """Собирает открываемую ссылку для FE. Ваш FE читает ?token=..."""
    base = FRONTEND_BASE.rstrip("/")
    # если нужен другой формат (например /access/<token>), поменяйте тут
    return f"{base}/?token={token}"

async def _load_employees_map() -> Dict[int, int]:
    """
    Возвращает map: internal employee id -> telegram_id.
    Предполагается, что /employees выдаёт объекты с полями {id, telegram_id}.
    """
    emps = await http_get("/employees?limit=100&offset=0")
    mapping: Dict[int, int] = {}
    for e in emps or []:
        try:
            internal_id = int(e.get("id"))
            tg_id = int(e.get("telegram_id"))
            mapping[internal_id] = tg_id
        except Exception:
            continue
    return mapping

async def notify_respondents_about_survey(bot: Bot, creation_result: dict) -> Tuple[int, List[str]]:
    """
    Отправляет персональные ссылки всем из batch_created.
    Возвращает (count_sent, errors).
    Ожидаемый формат creation_result:
    {
      "batch_created": [
        {"surveyId": "srv_1", "respondent_user_id": 6, "linkToken": "..."},
        ...
      ],
      "questions_count": 3
    }
    """
    batch = creation_result.get("batch_created") or []
    if not batch:
        return 0, ["batch_created пуст"]

    id2tg = await _load_employees_map()
    errors: List[str] = []
    sent = 0

    for item in batch:
        uid = item.get("respondent_user_id")
        token = item.get("linkToken")
        if uid is None or not token:
            errors.append(f"bad item: {item}")
            continue

        tg_id = id2tg.get(uid)
        if not tg_id:
            errors.append(f"нет telegram_id для respondent_user_id={uid}")
            continue

        url = await _build_token_url(token)
        msg = (
            "Вам назначен новый опрос 360°.\n"
            f"Перейдите по ссылке и заполните: {url}"
        )

        try:
            await bot.send_message(chat_id=tg_id, text=msg,
                                  parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            errors.append(f"send to {tg_id} failed: {e}")

    return sent, errors


def user_exists(user_id: str) -> bool:
    return user_id in load_users().values()


def create_poll_for_user(user_id: str) -> str:
    return f"Опрос для пользователя {user_id} успешно создан."


def create_summary_for_user(user_id: str) -> str:
    text = f"""Суммаризация по пользователю {user_id}:

Что хорошо:
Быстро вникает в контекст, быстро встает на рельсы.
Берет много на себя, тянет большой объем, иногда реально как локомотив. Видно, что за полгода сильно вырос.
Помогает команде, делится знаниями.
Внимателен к логике, аккуратно подходит к тестированию.
Имеются задатки хорошего инженера.

Зоны роста:
Требования: глубже прорабатывать детали до разработки, убирать противоречия, закрывать вопросы заранее.
Структура документов: выстраивать «от общего к частному».
Больше фокусироваться на сути, а не на форме.
Аккуратнее с регламентами разработки.
Коммуникация: в спорных моментах держать более спокойный, конструктивный тон, больше синхронизироваться с командой (иногда тяжело «остановить локомотив»).
Прокачать Python, а также практики тестирования и верификации изменений.

Заметка от коллеги: на проекте А сильные стороны было сложно увидеть из-за качества требований, но в целом прогресс заметный, потенциал высокий.
"""
    return text


def create_summary_pdf(user_id: str) -> str:
    text = create_summary_for_user(user_id)
    styles = getSampleStyleSheet()
    style_font = FONT_NAME if FONT_NAME else styles["Normal"].fontName
    russian_style = ParagraphStyle(
        "Russian",
        parent=styles["Normal"],
        fontName=style_font,
        fontSize=11,
        leading=14,
    )

    story = []
    for line in text.splitlines():
        if line.strip():
            story.append(Paragraph(line.strip(), russian_style))
            story.append(Spacer(1, 8))

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp_file.close()
    doc = SimpleDocTemplate(tmp_file.name, pagesize=A4)
    doc.build(story)
    return tmp_file.name


# =======================
# FSM
# =======================
class Form(StatesGroup):
    waiting_user_id_for_poll = State()
    waiting_user_id_for_summary = State()
    waiting_file_for_registration = State()  # новое состояние


# Новые FSM состояния для новой логики пресетов (в основе — вопросы)
class HRForm(StatesGroup):
    viewing_presets = State()  # показал список пресетов
    creating_preset_questions = (
        State()
    )  # ввод/выбор номеров вопросов для нового пресета
    creating_preset_name = State()  # ввод имени для пресета (подтверждение)
    creating_question_text = State()  # создание нового вопроса: текст
    creating_question_type = State()  # создание нового вопроса: тип
    creating_question_answers = State()  # создание нового вопроса: answer_fields
    viewing_preset_details = State()  # просмотр конкретного пресета перед отправкой
    confirming_send_preset = State()  # подтверждение отправки


class SurveyCreateForm(StatesGroup):
    # существовавшие шаги
    waiting_subject_user_id = State()
    waiting_reviewer_user_ids = State()
    waiting_review_type = State()
    waiting_question_ids = State()              # может быть пропущен, если создаём блок+вопросы
    waiting_deadline = State()
    waiting_notifications_before = State()
    waiting_anonymous = State()
    waiting_title = State()
    confirming = State()

    # НОВОЕ: ветка блок → вопросы → пресет
    waiting_block_decision = State()            # «Создать новый блок и вопросы?» Да/Нет
    waiting_block_name = State()
    waiting_new_question_text = State()
    waiting_new_question_type = State()
    waiting_new_question_answers = State()
    waiting_add_more_questions = State()

class SummaryComputeForm(StatesGroup):
    waiting_batch_id = State()
    waiting_model_name = State()
    waiting_prompt_version = State()


class LocalSummForm(StatesGroup):
    waiting_batch_id = State()
    waiting_system_prompt = State()
    waiting_user_prompt = State()


# =======================
# Keyboards
# =======================
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CREATE_POLL)],
            [KeyboardButton(text=BTN_SUMMARY)],
            [KeyboardButton(text=BTN_SUMMARY_Q)],
            [KeyboardButton(text=BTN_REGISTER)],
            [KeyboardButton(text=BTN_HR)],
            [KeyboardButton(text=BTN_LIST_USERS)],
        ],
        resize_keyboard=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True
    )


def presets_kb(presets: List[dict]) -> ReplyKeyboardMarkup:
    buttons = []
    for i, p in enumerate(presets, start=1):
        title = f"{i}. preset #{p.get('id')}"
        buttons.append([KeyboardButton(text=title)])
    buttons.append([KeyboardButton(text="Создать свой пресет")])
    buttons.append([KeyboardButton(text="Назад в меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def simple_kb(*labels: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=l)] for l in labels], resize_keyboard=True
    )


# =======================
# API / HTTP helpers
# =======================
API_BASE = "http://localhost:8000"


async def http_get(path: str):
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        url = API_BASE.rstrip("/") + path
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"GET {url} -> {resp.status}: {text}")
            try:
                return await resp.json()
            except Exception:
                return text


async def http_post(path: str, json_body: dict):
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        url = API_BASE.rstrip("/") + path

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=json_body, headers=headers) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"POST {url} -> {resp.status}: {text}")
            try:
                return await resp.json()
            except Exception:
                return text


# =======================
# Утилиты для отображения списков вопросов (строка)
# =======================

async def _fetch_reviews_for_batch(batch_id: int) -> dict:
    """
    Пытаемся получить сырой корпус отзывов для локального summarize-сервиса (8002).
    Возвращает объект формата:
    {
      "reviews": {
        "reviews": [
          {"sections": [{"title": "...", "text": "..."}, ...]}
        ]
      }
    }
    При отсутствии прямого эндпоинта — фоллбэк по stats.per_question из /v1/summaries/compute.
    """
    # 1) Пробуем специализированный эндпоинт, если он есть в вашем бэке:
    try:
        maybe = await http_get(f"/v1/summaries/reviews?batch_id={batch_id}")
        # ожидаем, что maybe уже в нужном формате или содержит ключ 'reviews'
        if isinstance(maybe, dict):
            if "reviews" in maybe and isinstance(maybe["reviews"], dict):
                return maybe  # уже готово
            # иногда бек может вернуть просто {"reviews": [...]} — завернём
            if "reviews" in maybe and isinstance(maybe["reviews"], list):
                return {"reviews": {"reviews": maybe["reviews"]}}
    except Exception:
        pass

    # 2) Фоллбэк: дергаем compute и составляем секции из per_question.sample
    try:
        comp = await http_post("/v1/summaries/compute", {
            "batch_id": batch_id,
            "model_name": "deepseek-chat",
            "prompt_version": 2
        })
        per_q = {}
        stats = comp.get("stats")
        if isinstance(stats, dict):
            per_q = stats.get("per_question") or {}
        sections = []
        # аккуратно по возрастанию ключей, если они строковые
        try:
            order = sorted((int(k) for k in per_q.keys()))
            iter_items = [(k, per_q.get(str(k)) or {}) for k in order]
        except Exception:
            iter_items = per_q.items()

        for qid, info in iter_items:
            title = info.get("question") or f"Q{qid}"
            text = info.get("sample") or ""
            if text:
                sections.append({"title": title, "text": text})

        if not sections:
            sections = [{"title": "empty", "text": ""}]

        return {"reviews": {"reviews": [{"sections": sections}]}}
    except Exception as e:
        raise RuntimeError(f"Не удалось получить данные для batch_id={batch_id}: {e}")


def render_questions_list(questions: List[dict], limit: int = 200) -> str:
    # Возвращает нумерованный список вопроса в формате "1. текст (id: 12)"
    lines = []
    for i, q in enumerate(questions, start=1):
        txt = (q.get("question_text") or "").replace("\n", " ")
        if len(txt) > 120:
            txt = txt[:117] + "..."
        lines.append(f"{i}. {txt} (id:{q.get('id')})")
        if len(lines) >= limit:
            break
    return "\n".join(lines) if lines else "(вопросов нет)"


async def start_local_summarize_by_batch(message: types.Message, state: FSMContext):
    await state.set_state(LocalSummForm.waiting_batch_id)
    await message.answer(
        "Локальная суммаризация по batch_id (порт 8002).\n"
        "Шаг 1/3 — введите batch_id (целое число):",
        reply_markup=cancel_kb(),
    )

async def lsb_batch_id(message: types.Message, state: FSMContext):
    bid = _parse_int(message.text)
    if bid is None or bid < 1:
        await message.answer("batch_id должен быть целым числом ≥ 1. Повторите ввод.")
        return
    await state.update_data(batch_id=bid)
    await state.set_state(LocalSummForm.waiting_system_prompt)
    await message.answer(
        "Шаг 2/3 — system_prompt (или отправьте 'по умолчанию' — будет пусто).",
        reply_markup=cancel_kb(),
    )

async def lsb_system_prompt(message: types.Message, state: FSMContext):
    sp = message.text.strip()
    if sp.lower() in ("по умолчанию", "default"):
        sp = ""
    await state.update_data(system_prompt=sp)
    await state.set_state(LocalSummForm.waiting_user_prompt)
    await message.answer(
        "Шаг 3/3 — user_prompt (или 'по умолчанию' — краткая русская выжимка).",
        reply_markup=cancel_kb(),
    )

# async def lsb_user_prompt(message: types.Message, state: FSMContext):
#     up = message.text.strip()
#     if up.lower() in ("по умолчанию", "default", ""):
#         up = "Суммаризируй кратко и по-русски."
#     data = await state.get_data()
#     batch_id = data["batch_id"]
#     system_prompt = data["system_prompt"]
#
#     # 1) Тянем текст по batch_id
#     try:
#         reviews_payload = await _fetch_reviews_for_batch(batch_id)
#     except Exception as e:
#         await state.clear()
#         await message.answer(f"Не удалось подтянуть текст по batch_id={batch_id}: {e}",
#                              reply_markup=main_menu_kb())
#         return
#
#     # 2) Собираем финальный payload для локального сервиса
#     payload = {
#         "reviews": reviews_payload.get("reviews") or {"reviews": []},
#         "system_prompt": system_prompt,
#         "user_prompt": up,
#     }
#     print(payload)
#
#     logging.info("[LOCAL-SUMM-BATCH] POST 8002/summarize for batch_id=%s", batch_id)
#
#     try:
#         result = await http_post("http://localhost:8002/summarize", payload)
#         print(result)
#     except Exception as e:
#         await state.clear()
#         await message.answer(f"Ошибка локальной суммаризации: {e}", reply_markup=main_menu_kb())
#         return
#
#     await state.clear()
#
#     summary = (result.get("summary") if isinstance(result, dict) else None) or str(result)
#     header = f"Суммаризация (batch_id={batch_id}):"
#     for chunk in _chunk_send_text(header + "\n\n" + summary):
#         await message.answer(chunk, reply_markup=main_menu_kb())

async def lsb_user_prompt(message: types.Message, state: FSMContext):
    up = message.text.strip()
    if up.lower() in ("по умолчанию", "default", ""):
        up = "Суммаризируй кратко и по-русски."

    data = await state.get_data()
    batch_id = data["batch_id"]
    system_prompt = data["system_prompt"]

    # 1) Тянем сырьё по batch_id (как у вас уже сделано)
    try:
        reviews_payload = await _fetch_reviews_for_batch(batch_id)
    except Exception as e:
        await state.clear()
        await message.answer(f"Не удалось подтянуть текст по batch_id={batch_id}: {e}",
                             reply_markup=main_menu_kb())
        return

    # 2) Собираем плоский текст для inline-подстраховки
    sections = ((reviews_payload or {}).get("reviews") or {}).get("reviews") or []
    flat_lines = []
    for obj in sections:
        for sec in (obj.get("sections") or []):
            title = (sec.get("title") or "").strip()
            text = (sec.get("text") or "").strip()
            if title or text:
                flat_lines.append(f"{title}: {text}".strip(": "))

    inline_reviews = "\n".join(flat_lines) if flat_lines else ""

    # 3) Финальный payload — строго по спецификации + inline дублирование в user_prompt
    payload = {
        "reviews": reviews_payload.get("reviews") or {"reviews": []},
        "system_prompt": system_prompt,
        "user_prompt": f"{up}\n\n=== REVIEWS ===\n{inline_reviews}" if inline_reviews else up,
    }

    logging.info("[LOCAL-SUMM-BATCH] POST 8002/summarize for batch_id=%s", batch_id)

    try:
        result = await http_post("http://localhost:8002/summarize", payload)
    except Exception as e:
        await state.clear()
        await message.answer(f"Ошибка локальной суммаризации: {e}", reply_markup=main_menu_kb())
        return

    await state.clear()

    summary = (result.get("summary") if isinstance(result, dict) else None) or str(result)
    header = f"Суммаризация (batch_id={batch_id}):"
    for chunk in _chunk_send_text(header + "\n\n" + summary):
        await message.answer(chunk, reply_markup=main_menu_kb())




def build_survey_link(token: str, frontend_base: Optional[str] = None) -> str:
    """
    Строим ссылку для фронта с параметром ?token=<...>.
    Твой фронт читает token из query (?token=... или ?t=...), так что этого достаточно.
    """
    base = (frontend_base or FRONTEND_BASE).strip()
    parts = list(urlsplit(base))
    # сохраним уже имеющиеся query-параметры, если есть
    q = dict(parse_qsl(parts[3]))
    q["token"] = token
    parts[3] = urlencode(q)
    return urlunsplit(parts)


async def start_local_summarize(message: types.Message, state: FSMContext):
    await state.set_state(LocalSummForm.waiting_reviews_or_text)
    await message.answer(
        "Локальная суммаризация (порт 8002).\n"
        "Шаг 1/3 — пришлите *либо* готовый JSON (как в примере), *либо* обычный текст.\n"
        "Если пришлёте текст, я сам оберну его в формат `reviews`.",
        reply_markup=cancel_kb(),
    )

async def ls_reviews_or_text(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    await state.update_data(_raw_payload=raw)
    await state.set_state(LocalSummForm.waiting_system_prompt)
    await message.answer(
        "Шаг 2/3 — system_prompt (или отправьте 'по умолчанию' чтобы оставить пустым).",
        reply_markup=cancel_kb(),
    )

async def ls_system_prompt(message: types.Message, state: FSMContext):
    sp = message.text.strip()
    if sp.lower() in ("по умолчанию", "default"):
        sp = ""
    await state.update_data(system_prompt=sp)
    await state.set_state(LocalSummForm.waiting_user_prompt)
    await message.answer(
        "Шаг 3/3 — user_prompt (или 'по умолчанию' для краткой русской выжимки).",
        reply_markup=cancel_kb(),
    )

async def ls_user_prompt(message: types.Message, state: FSMContext):
    up = message.text.strip()
    if up.lower() in ("по умолчанию", "default", ""):
        up = "Суммаризируй кратко и по-русски."
    data = await state.get_data()
    raw = data.get("_raw_payload", "")

    # Попробуем понять: это JSON из примера или обычный текст?
    payload: dict
    try:
        import json
        maybe = json.loads(raw)
        # Если это уже валидный объект и там есть ключи нужного формата — отправляем как есть, добивая промпты
        if isinstance(maybe, dict) and ("reviews" in maybe or "system_prompt" in maybe or "user_prompt" in maybe):
            maybe.setdefault("reviews", {"reviews": [{"sections": [{"title": "text", "text": ""}]}]})
            maybe["system_prompt"] = data.get("system_prompt", "")
            maybe["user_prompt"] = up
            payload = maybe
        else:
            raise ValueError("not expected shape")
    except Exception:
        # Это обычный текст — оборачиваем по контракту сервиса
        payload = {
            "reviews": {
                "reviews": [
                    {"sections": [{"title": "text", "text": raw}]}
                ]
            },
            "system_prompt": data.get("system_prompt", ""),
            "user_prompt": up,
        }

    logging.info("[LOCAL-SUMM] POST 8002/summarize payload_keys=%s",
                 list(payload.keys()))
    try:
        result = await http_post("http://localhost:8002/summarize", payload)
    except Exception as e:
        await state.clear()
        await message.answer(f"Ошибка локальной суммаризации: {e}", reply_markup=main_menu_kb())
        return

    await state.clear()

    summary = (result.get("summary") if isinstance(result, dict) else None) or str(result)
    for chunk in _chunk_send_text(summary):
        await message.answer(chunk, reply_markup=main_menu_kb())


def _chunk_send_text(text: str, max_len: int = 3500) -> List[str]:
    lines = text.splitlines()
    out, buf, size = [], [], 0
    for ln in lines:
        if size + len(ln) + 1 > max_len:
            out.append("\n".join(buf))
            buf, size = [], 0
        buf.append(ln)
        size += len(ln) + 1
    if buf:
        out.append("\n".join(buf))
    return out


def _parse_int(text: str) -> Optional[int]:
    try:
        return int(text.strip())
    except Exception:
        return None

def _parse_int_list(text: str) -> Optional[List[int]]:
    try:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if not parts:
            return []
        out = []
        for p in parts:
            if not p.isdigit():
                return None
            out.append(int(p))
        return out
    except Exception:
        return None

def _parse_bool_ru(text: str) -> Optional[bool]:
    t = text.strip().lower()
    if t in ("да", "true", "1", "y", "yes"):
        return True
    if t in ("нет", "false", "0", "n", "no"):
        return False
    return None

def _is_iso_datetime(text: str) -> bool:
    # ожидаем ISO вида 2025-09-12T00:54:33.189Z
    try:
        from datetime import datetime
        if text.endswith("Z"):
            datetime.fromisoformat(text[:-1])
            return True
        datetime.fromisoformat(text)  # допустим и без Z
        return True
    except Exception:
        return False



# =======================
# Handlers: старт/основные (unchanged)
# =======================
async def cmd_start(message: types.Message):
    register_user(message.from_user.id, message.from_user.username)
    await message.answer("Выберите действие:", reply_markup=main_menu_kb())


# =======================
# Создание опроса (новый мастёр)
# =======================
async def start_summary(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_user_id_for_summary)
    await message.answer(
        "Введите идентификатор пользователя для суммаризации:", reply_markup=cancel_kb()
    )


async def start_registration(message: types.Message, state: FSMContext): 
    await state.set_state(Form.waiting_file_for_registration)
    await message.answer( "Отправьте Excel-файл (.xlsx) с колонками: username, ФИО, email. Username — без ведущего @.", reply_markup=cancel_kb(), )


async def start_create_poll(message: types.Message, state: FSMContext):
    await state.set_state(SurveyCreateForm.waiting_subject_user_id)
    await message.answer(
        "Создаём опрос.\nШаг 1/8 — введите внутренний id оцениваемого (subject_user_id).",
        reply_markup=cancel_kb(),
    )

async def sc_subject_user_id(message: types.Message, state: FSMContext):
    val = _parse_int(message.text)
    if val is None:
        await message.answer("Нужно целое число. Введите subject_user_id ещё раз.")
        return
    await state.update_data(subject_user_id=val)
    await state.set_state(SurveyCreateForm.waiting_reviewer_user_ids)
    await message.answer("Шаг 2/8 — введите id ревьюеров через запятую (например: 2,3,5).")

async def sc_reviewer_user_ids(message: types.Message, state: FSMContext):
    vals = _parse_int_list(message.text)
    if vals is None or not vals:
        await message.answer("Список должен быть целыми числами через запятую (минимум один).")
        return
    await state.update_data(reviewer_user_ids=vals)
    await state.set_state(SurveyCreateForm.waiting_review_type)
    await message.answer("Шаг 3/8 — тип обзора (review_type): 180 или 360.")

async def sc_review_type(message: types.Message, state: FSMContext):
    t = message.text.strip()
    if t not in ("180", "360"):
        await message.answer("Поддерживаются только 180 или 360. Введите ещё раз.")
        return
    await state.update_data(review_type=t)

    # НОВОЕ: спросить — создать блок и вопросы сейчас?
    await state.set_state(SurveyCreateForm.waiting_block_decision)
    await message.answer(
        "Хотите сразу создать новый блок и вопросы для него? (Да/Нет)\n"
        "Если «Нет», вы введёте готовые question_id вручную.",
        reply_markup=cancel_kb(),
    )

async def sc_block_decision(message: types.Message, state: FSMContext):
    b = _parse_bool_ru(message.text)
    if b is None:
        await message.answer("Ответьте «Да» или «Нет».")
        return
    if b:
        # Создаём новый блок
        await state.set_state(SurveyCreateForm.waiting_block_name)
        await message.answer("Введите имя блока (block_name):", reply_markup=cancel_kb())
    else:
        # Старый путь: ручной ввод question_ids
        await state.set_state(SurveyCreateForm.waiting_question_ids)
        await message.answer(
            "Шаг 4/8 — введите id вопросов через запятую (пример: 1,4,7).",
            reply_markup=cancel_kb(),
        )

async def sc_block_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Имя блока не может быть пустым. Введите ещё раз.")
        return
    try:
        created_block = await http_post("/blocks", {"block_name": name})
        block_id = created_block.get("id")
        if block_id is None:
            raise RuntimeError(f"Некорректный ответ /blocks: {created_block}")
    except Exception as e:
        await state.clear()
        await message.answer(f"Не удалось создать блок: {e}", reply_markup=main_menu_kb())
        return

    await state.update_data(block_id=block_id, new_question_ids=[])
    await state.set_state(SurveyCreateForm.waiting_new_question_text)
    await message.answer(
        f"Блок создан (id={block_id}). Теперь создадим вопросы.\n"
        "Введите текст первого вопроса:",
        reply_markup=cancel_kb(),
    )

async def sc_new_question_text(message: types.Message, state: FSMContext):
    qtext = message.text.strip()
    if not qtext:
        await message.answer("Текст вопроса не может быть пустым. Введите ещё раз.")
        return
    await state.update_data(tmp_qtext=qtext)
    await state.set_state(SurveyCreateForm.waiting_new_question_type)
    await message.answer("Введите тип вопроса ('0' для текста и '1' для шкалы от 0 до 10):")

async def sc_new_question_type(message: types.Message, state: FSMContext):
    t = _parse_int(message.text)
    if t is None:
        await message.answer("Тип должен быть целым числом. Введите ещё раз.")
        return
    await state.update_data(tmp_qtype=t)
    await state.set_state(SurveyCreateForm.waiting_new_question_answers)
    await message.answer("Введите answer_fields (строка; как требует ваш API):")

async def sc_new_question_answers(message: types.Message, state: FSMContext):
    answers = message.text.strip()
    data = await state.get_data()
    block_id = data.get("block_id")
    qtext = data.get("tmp_qtext")
    qtype = data.get("tmp_qtype")
    if block_id is None or qtext is None or qtype is None:
        await state.clear()
        await message.answer("Внутренняя ошибка состояния. Начните заново.", reply_markup=main_menu_kb())
        return

    payload = {
        "block_id": block_id,
        "question_text": qtext,
        "question_type": qtype,
        "answer_fields": answers,
    }
    try:
        created_q = await http_post("/questions", payload)
        qid = created_q.get("id")
        if qid is None:
            raise RuntimeError(f"Некорректный ответ /questions: {created_q}")
    except Exception as e:
        await state.clear()
        await message.answer(f"Не удалось создать вопрос: {e}", reply_markup=main_menu_kb())
        return

    # добавляем id вопроса в список
    qids = data.get("new_question_ids", [])
    qids.append(qid)
    await state.update_data(new_question_ids=qids, tmp_qtext=None, tmp_qtype=None)

    # спросим — добавить ещё вопрос?
    await state.set_state(SurveyCreateForm.waiting_add_more_questions)
    await message.answer(
        f"Вопрос создан (id={qid}). Добавить ещё вопрос? (Да/Нет)",
        reply_markup=cancel_kb(),
    )

async def sc_add_more_questions(message: types.Message, state: FSMContext):
    b = _parse_bool_ru(message.text)
    if b is None:
        await message.answer("Ответьте «Да» или «Нет».")
        return
    if b:
        # новый вопрос в том же блоке
        await state.set_state(SurveyCreateForm.waiting_new_question_text)
        await message.answer("Введите текст следующего вопроса:", reply_markup=cancel_kb())
        return

    # Нет — закрываем набор вопросов, создаём пресет
    data = await state.get_data()
    qids = data.get("new_question_ids", [])
    if not qids:
        await state.clear()
        await message.answer("Нужно создать хотя бы один вопрос. Мастер завершён.", reply_markup=main_menu_kb())
        return

    try:
        created_preset = await http_post("/presets", {"questions": qids})
        preset_id = created_preset.get("id")
        if preset_id is None:
            raise RuntimeError(f"Некорректный ответ /presets: {created_preset}")
    except Exception as e:
        await state.clear()
        await message.answer(f"Не удалось создать пресет: {e}", reply_markup=main_menu_kb())
        return

    # Для мастера опроса нам нужны question_ids — используем только что созданные
    await state.update_data(question_ids=qids, created_preset_id=preset_id)
    # Идём дальше как будто пользователь ввёл question_ids
    await state.set_state(SurveyCreateForm.waiting_deadline)
    await message.answer(
        f"Пресет создан (id={preset_id}). Вопросы: {', '.join(map(str, qids))}\n"
        "Шаг 5/8 — дедлайн (deadline) в ISO-формате, напр.: 2025-09-12T00:54:33.189Z",
        reply_markup=cancel_kb(),
    )


async def sc_question_ids(message: types.Message, state: FSMContext):
    vals = _parse_int_list(message.text)
    if vals is None or not vals:
        await message.answer("Нужен непустой список id вопросов через запятую. Повторите ввод.")
        return
    await state.update_data(question_ids=vals)
    await state.set_state(SurveyCreateForm.waiting_deadline)
    await message.answer("Шаг 5/8 — дедлайн (ISO), напр.: 2025-09-12T00:54:33.189Z")

async def sc_deadline(message: types.Message, state: FSMContext):
    s = message.text.strip()
    if not _is_iso_datetime(s):
        await message.answer("Неверный формат. Введите ISO-дату, напр.: 2025-09-12T00:54:33.189Z")
        return
    await state.update_data(deadline=s)
    await state.set_state(SurveyCreateForm.waiting_notifications_before)
    await message.answer("Шаг 6/8 — notifications_before (целое число, 0 если не нужно).")

async def sc_notifications_before(message: types.Message, state: FSMContext):
    n = _parse_int(message.text)
    if n is None or n < 0:
        await message.answer("Нужно целое число ≥ 0. Введите ещё раз.")
        return
    await state.update_data(notifications_before=n)
    await state.set_state(SurveyCreateForm.waiting_anonymous)
    await message.answer("Шаг 7/8 — анонимный опрос? (Да/Нет)")

async def sc_anonymous(message: types.Message, state: FSMContext):
    b = _parse_bool_ru(message.text)
    if b is None:
        await message.answer("Ответьте «Да» или «Нет».")
        return
    await state.update_data(anonymous=b)
    await state.set_state(SurveyCreateForm.waiting_title)
    await message.answer("Шаг 8/8 — укажите заголовок опроса (title):")

async def sc_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    if not title:
        await message.answer("Заголовок не может быть пустым. Введите ещё раз.")
        return
    await state.update_data(title=title)
    data = await state.get_data()
    preview = (
        "Проверьте данные перед созданием:\n"
        f"- subject_user_id: {data['subject_user_id']}\n"
        f"- reviewer_user_ids: {', '.join(map(str, data['reviewer_user_ids']))}\n"
        f"- review_type: {data['review_type']}\n"
        f"- question_ids: {', '.join(map(str, data['question_ids']))}\n"
        f"- deadline: {data['deadline']}\n"
        f"- notifications_before: {data['notifications_before']}\n"
        f"- anonymous: {'Да' if data['anonymous'] else 'Нет'}\n"
        f"- title: {data['title']}\n\n"
        "Нажмите «Создать опрос» для отправки или «Отмена»."
    )
    await state.set_state(SurveyCreateForm.confirming)
    await message.answer(preview, reply_markup=simple_kb("Создать опрос", BTN_CANCEL))

async def sc_confirm(message: types.Message, state: FSMContext):
    if message.text.strip() != "Создать опрос":
        await message.answer("Нажмите «Создать опрос» или «Отмена».")
        return

    data = await state.get_data()
    payload = {
        "subject_user_id": data["subject_user_id"],
        "reviewer_user_ids": data["reviewer_user_ids"],
        "review_type": data["review_type"],
        "question_ids": data["question_ids"],
        "deadline": data["deadline"],
        "notifications_before": data["notifications_before"],
        "anonymous": data["anonymous"],
        "title": data["title"],
    }

    try:
        created = await http_post("/v1/surveys/initiate", payload)
        sent, errs = await notify_respondents_about_survey(message.bot, created)

    except Exception as e:
        await state.clear()
        await message.answer(
            f"Ошибка при создании опроса: {e}", reply_markup=main_menu_kb()
        )
        return

    await state.clear()

    # Итоговый отчёт
    report_lines = [
        "Опрос создан успешно.",
        # f"Ответ сервера: {created}",
        f"Оповещений отправлено: {sent}",
    ]
    if errs:
        report_lines.append("Замечания/ошибки при рассылке:")
        report_lines.extend(f"- {x}" for x in errs[:50])
    await message.answer("\n".join(report_lines), reply_markup=main_menu_kb())



async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_menu_kb())


async def handle_user_id_for_poll(message: types.Message, state: FSMContext):
    user_id = _parse_user_id(message.text)
    if user_id is None:
        await message.answer(
            "Невалидный формат. Введите целое число идентификатора пользователя."
        )
        return
    if not user_exists(user_id):
        await message.answer(
            "Пользователь с таким идентификатором не найден. Проверьте ID и попробуйте снова."
        )
        return
    result = create_poll_for_user(user_id)
    await state.clear()
    await message.answer(result, reply_markup=main_menu_kb())


async def handle_user_id_for_summary(message: types.Message, state: FSMContext):
    user_id = _parse_user_id(message.text)
    if user_id is None:
        await message.answer(
            "Невалидный формат. Введите целое число идентификатора пользователя."
        )
        return
    if not user_exists(user_id):
        await message.answer(
            "Пользователь с таким идентификатором не найден. Проверьте ID и попробуйте снова."
        )
        return
    pdf_path = create_summary_pdf(user_id)
    await state.clear()
    await message.answer_document(
        FSInputFile(pdf_path),
        caption=f"Суммаризация по пользователю {user_id}",
        reply_markup=main_menu_kb(),
    )
    try:
        os.remove(pdf_path)
    except OSError:
        pass


async def show_registered_users(message: types.Message):
    """
    Показывает список зарегистрированных пользователей: 'ФИО, id'.
    Берёт данные из /employees?limit=100&offset=0
    """
    try:
        employees = await http_get("/employees?limit=100&offset=0")
        if not employees:
            await message.answer("Пока нет зарегистрированных пользователей.")
            return
    except Exception as e:
        await message.answer(f"Не удалось получить список пользователей: {e}")
        return

    lines: List[str] = []
    for emp in employees:
        first = (emp.get("first_name") or "").strip()
        last = (emp.get("last_name") or "").strip()
        fio = (f"{last} {first}").strip()
        if not fio:
            # Фолбэк если нет ФИО: используем username/email/telegram_id
            fio = emp.get("telegram") or emp.get("email") or str(emp.get("telegram_id") or "")
            fio = fio or "(без имени)"
        emp_id = emp.get("id")
        lines.append(f"{fio}, {emp_id}")

    # Telegram ограничение ~4096 символов — разобьём вывод на части
    chunk = []
    size = 0
    for line in lines:
        if size + len(line) + 1 > 3500:
            await message.answer("\n".join(chunk))
            chunk, size = [], 0
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        await message.answer("\n".join(chunk))

# ===== Summaries: compute =====
async def start_compute_summary(message: types.Message, state: FSMContext):
    await state.set_state(SummaryComputeForm.waiting_batch_id)
    await message.answer(
        "Суммаризация по вопросу.\n"
        "Шаг 1/3 — введите batch_id (целое число):",
        reply_markup=cancel_kb(),
    )

async def sc_batch_id(message: types.Message, state: FSMContext):
    bid = _parse_int(message.text)
    if bid is None or bid < 1:
        await message.answer("batch_id должен быть целым числом ≥ 1. Повторите ввод.")
        return
    await state.update_data(batch_id=bid)
    await state.set_state(SummaryComputeForm.waiting_model_name)
    await message.answer(
        "Шаг 2/3 — введите model_name или отправьте 'по умолчанию'.\n"
        "По умолчанию: deepseek-chat",
        reply_markup=cancel_kb(),
    )

async def sc_model_name(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    model = "deepseek-chat" if raw.lower() in ("", "по умолчанию", "default") else raw
    await state.update_data(model_name=model)
    await state.set_state(SummaryComputeForm.waiting_prompt_version)
    await message.answer(
        "Шаг 3/3 — введите prompt_version (целое) или отправьте 'по умолчанию'.\n"
        "По умолчанию: 2",
        reply_markup=cancel_kb(),
    )

async def sc_prompt_version(message: types.Message, state: FSMContext):
    raw = message.text.strip().lower()
    if raw in ("", "по умолчанию", "default"):
        pv = 2
    else:
        pv = _parse_int(raw)
        if pv is None or pv < 1:
            await message.answer("prompt_version должен быть целым числом ≥ 1 или 'по умолчанию'. Повторите ввод.")
            return

    data = await state.get_data()
    payload = {
        "batch_id": data["batch_id"],
        "model_name": data["model_name"],
        "prompt_version": pv,
    }

    try:
        result = await http_post("/v1/summaries/compute", payload)
    except Exception as e:
        await state.clear()
        await message.answer(f"Ошибка при суммаризации: {e}", reply_markup=main_menu_kb())
        return

    await state.clear()

    # Форматируем вывод
    summary_text = result.get("summary_text") or "(summary_text пуст)"
    stats = result.get("stats", {}) or {}
    per_q = (stats.get("per_question") or {}) if isinstance(stats, dict) else {}

    header = (
        "Суммаризация готова.\n"
        f"batch_id: {result.get('batch_id')}, subject_user_id: {result.get('subject_user_id')}\n"
        f"status: {result.get('status')}, model: {result.get('model_name')}, prompt_v: {result.get('prompt_version')}\n"
        f"created: {result.get('created_at')}, updated: {result.get('updated_at')}\n"
    )

    # Краткий блок per_question
    pq_lines = []
    try:
        # перебирать в порядке id
        for qid in sorted((int(k) for k in per_q.keys())):
            info = per_q.get(str(qid)) or {}
            title = info.get("question") or f"Q{qid}"
            n = info.get("n")
            sample = info.get("sample")
            pq_lines.append(f"- {title} — n={n}, sample: {sample}")
    except Exception:
        pass

    body = [header, "— — —", summary_text]
    if pq_lines:
        body.append("\nКратко по вопросам:")
        body.extend(pq_lines)

    full = "\n".join(body)

    # Разбиваем и отправляем
    for chunk in _chunk_send_text(full):
        await message.answer(chunk, reply_markup=main_menu_kb())



async def fetch_employee_telegram_id(employee_id: int, api_base: Optional[str] = None) -> Optional[int]:
    """
    Достаём Telegram ID респондента из твоего API.
    В примере нет фильтра по id, поэтому берём страницу и ищем локально.
    Если у тебя уже есть готовая функция — просто замени вызов этой функции на неё.
    """
    base = (api_base or API_BASE).rstrip("/")
    url = f"{base}/employees?limit=100&offset=0"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers={"accept": "application/json"}) as resp:
            resp.raise_for_status()
            data = await resp.json()

    # Ожидаем, что вернётся список сотрудников, каждый — словарь с полями как минимум id + одно из telegram_* полей
    # Подстраховка по нескольким возможным названиям поля телеграма
    candidates = data if isinstance(data, list) else data.get("items") or data.get("employees") or []
    for emp in candidates:
        try:
            if int(emp.get("id")) == int(employee_id):
                tg_id = (
                    emp.get("telegram_id")
                    or emp.get("tg_id")
                    or emp.get("telegramId")
                    or emp.get("telegram")
                    or emp.get("chat_id")
                )
                # приведём к int, если это строка
                return int(tg_id) if tg_id is not None else None
        except (ValueError, TypeError):
            continue
    return None


async def expand_and_format_message(batch_item: Dict[str, Any]) -> tuple[int, str]:
    """
    Возвращает (tg_chat_id, text) для отправки.
    batch_item: {"surveyId":"srv_1","respondent_user_id":6,"linkToken":"..."}
    """
    link = build_survey_link(batch_item["linkToken"])
    tg_id = await fetch_employee_telegram_id(int(batch_item["respondent_user_id"]))
    if tg_id is None:
        raise RuntimeError(
            f"Не найден Telegram ID у пользователя id={batch_item['respondent_user_id']}"
        )

    text = (
        "Вам назначен опрос 360°.\n"
        "Перейдите по ссылке и заполните форму:\n"
        f"{link}\n\n"
        "Если ссылка не открывается, попробуйте другой браузер."
    )
    return tg_id, text



async def notify_respondent_about_survey(batch_item: Dict[str, Any]) -> None:
    """
    batch_item ожидается в формате:
    {
      "surveyId": "srv_1",
      "respondent_user_id": 6,
      "linkToken": "fmAbCkoB0uTIuJckaTJoBmMvPJFf-Au-"
    }
    """
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в окружении")

    link_token = batch_item["linkToken"]
    respondent_id = int(batch_item["respondent_user_id"])

    # 1) Собираем ссылку для фронта
    link = build_survey_link(link_token)

    # 2) Находим Telegram ID респондента
    tg_id = await fetch_employee_telegram_id(respondent_id)
    if tg_id is None:
        raise RuntimeError(f"Не найден Telegram ID у пользователя id={respondent_id}")

    # 3) Шлём сообщение
    text = (
        "Вам назначен опрос 360°.\n"
        "Перейдите по ссылке и заполните форму:\n"
        f"{link}\n\n"
        "Если ссылка не открывается, попробуйте из другого браузера."
    )

    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(chat_id=tg_id, text=text, disable_web_page_preview=True)
    except TelegramAPIError as e:
        raise RuntimeError(f"Ошибка отправки сообщения в Telegram: {e!s}")
    finally:
        await bot.session.close()


async def handle_registration_file(message: types.Message, state: FSMContext):
    if not message.document:
        await message.answer("Пожалуйста, отправьте файл в формате .xlsx.", reply_markup=cancel_kb())
        return

    file_name = message.document.file_name or "file"
    if not (file_name.lower().endswith(".xlsx") or file_name.lower().endswith(".xls")):
        await message.answer("Файл должен быть Excel (.xlsx или .xls). Попробуйте снова.", reply_markup=cancel_kb())
        return

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_name).suffix)
    tmp_path = tmp.name
    tmp.close()

    bot: Bot = message.bot

    # --- скачивание файла ---
    try:
        download = getattr(message.document, "download", None)
        if callable(download):
            await message.document.download(destination_file=tmp_path)
        else:
            file_obj = await bot.get_file(message.document.file_id)
            file_path = file_obj.file_path
            download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

            def _download_sync():
                urllib.request.urlretrieve(download_url, tmp_path)

            await asyncio.get_event_loop().run_in_executor(None, _download_sync)
    except Exception as e:
        await state.clear()
        await message.answer(f"Не удалось скачать файл: {e}", reply_markup=main_menu_kb())
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return
    # --- конец скачивания ---

    # Чтение Excel
    try:
        df = pd.read_excel(tmp_path, engine="openpyxl")
    except Exception as e:
        await state.clear()
        await message.answer(f"Не удалось прочитать Excel: {e}", reply_markup=main_menu_kb())
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return

    try:
        os.remove(tmp_path)
    except OSError:
        pass

    # Нормализация колонок
    col_map = {}
    for col in df.columns:
        low = str(col).strip().lower()
        if low == "username":
            col_map["username"] = col
        elif low in ("фио", "fio"):
            col_map["fio"] = col
        elif low == "email":
            col_map["email"] = col

    if "username" not in col_map:
        await state.clear()
        await message.answer("В файле отсутствует колонка 'username'. Убедитесь, что она есть и попробуйте снова.", reply_markup=main_menu_kb())
        return

    send_template = "привет, {fio}!"  # можно менять
    successes = []
    failures = {}

    async with aiohttp.ClientSession() as session:
        for idx, row in df.iterrows():
            raw_username = row[col_map["username"]]
            if pd.isna(raw_username):
                failures[f"row_{idx}"] = "username пустой"
                continue

            username = str(raw_username).strip().lstrip("@")
            if not username:
                failures[f"row_{idx}"] = "username оказался пустым после очистки"
                continue

            # ФИО
            fio_val = str(row[col_map["fio"]]).strip() if "fio" in col_map else ""
            parts = fio_val.split(" ", 1) if fio_val else []
            last_name = parts[0] if parts else ""
            first_name = parts[1] if len(parts) > 1 else ""

            email_val = str(row[col_map["email"]]).strip() if "email" in col_map else None

            chat_id = get_chat_id_by_username(username)
            if chat_id is None:
                failures[username] = "user not found in local db (он не нажимал /start у бота)"
                continue

            send_text = send_template.format(fio=fio_val) if fio_val else "привет мир"
            try:
                await bot.send_message(chat_id=chat_id, text=send_text)
            except TelegramAPIError as e:
                failures[username] = f"send_message TelegramAPIError: {e}"
                continue
            except Exception as e:
                failures[username] = f"send_message Exception: {e}"
                continue

            # Формируем JSON для POST
            payload = {
                "telegram_id": chat_id,
                "post": 0,
                "command_id": 0,
                "first_name": first_name,
                "last_name": last_name,
                "email": email_val,
                "telegram": username
            }

            try:
                async with session.post("http://localhost:8000/employees", json=payload) as resp:
                    if resp.status != 201:
                        failures[username] = f"POST error {resp.status}: {await resp.text()}"
                        continue
            except Exception as e:
                failures[username] = f"POST exception: {e}"
                continue

            successes.append(username)
            await asyncio.sleep(0.05)

    # Формируем отчёт
    total = len(successes) + len(failures)
    report_lines = [
        f"Обработано записей: {total}",
        f"Отправлено успешно: {len(successes)}",
        f"Ошибок: {len(failures)}",
    ]
    if successes:
        report_lines.append("Успешные username (первые 50): " + ", ".join(successes[:50]))
    if failures:
        report_lines.append("Ошибки (username -> причина):")
        for u, reason in list(failures.items())[:50]:
            report_lines.append(f"- {u} -> {reason}")

    await state.clear()
    await message.answer("\n".join(report_lines), reply_markup=main_menu_kb())



# =======================
# HR: новая логика — пресеты собираются из вопросов
# =======================
async def hr_start_presets(message: types.Message, state: FSMContext):
    """
    Точка входа HR: показать список пресетов и возможность создать новый пресет (с любым количеством вопросов).
    """
    try:
        presets = await http_get("/presets")
    except Exception as e:
        await message.answer(
            f"Ошибка при получении пресетов: {e}", reply_markup=main_menu_kb()
        )
        return

    # presets — список объектов, где, согласно вашему curl- примеру, есть поле "questions": [ids] и "id"
    mapping = (
        {str(i): p["id"] for i, p in enumerate(presets, start=1)} if presets else {}
    )
    await state.set_state(HRForm.viewing_presets)
    await state.update_data(presets=presets, preset_index_map=mapping)
    # Текст предварительный: покажем кратко пресеты и предложим варианты
    if presets:
        preview_lines = []
        for i, p in enumerate(presets, start=1):
            qcount = len(p.get("questions") or [])
            preview_lines.append(f"{i}. preset #{p.get('id')} — {qcount} вопросов")
        text = (
            "Существующие пресеты:\n"
            + "\n".join(preview_lines)
            + "\n\nВыберите номер пресета для просмотра/рассылки, либо создайте свой пресет."
        )
    else:
        text = "Пресетов не найдено. Создайте свой пресет."

    await message.answer(text, reply_markup=presets_kb(presets or []))


async def hr_handle_presets_choice(message: types.Message, state: FSMContext):
    """
    Обработка выбора пресета или команды "Создать свой пресет".
    """
    text = message.text.strip()
    if text == "Создать свой пресет":
        # Начинаем flow создания пресета (сбор вопросов)
        # Загружаем все вопросы для выбора
        try:
            questions = await http_get("/questions")
        except Exception as e:
            await message.answer(
                f"Не удалось загрузить список вопросов: {e}",
                reply_markup=main_menu_kb(),
            )
            await state.clear()
            return

        if not questions:
            # если вопросов нет — предлагаем создать вопрос
            await state.set_state(HRForm.creating_question_text)
            await message.answer(
                "Вопросов ещё нет. Введите текст нового вопроса (начнём создание вопроса):",
                reply_markup=cancel_kb(),
            )
            return

        # Сохраняем mapping index->question_id
        q_map = {str(i): q["id"] for i, q in enumerate(questions, start=1)}
        await state.update_data(all_questions=questions, question_index_map=q_map)
        await state.set_state(HRForm.creating_preset_questions)

        list_text = render_questions_list(questions)
        instructions = (
            "Введите номера вопросов через запятую (например: 1,3,5) чтобы включить их в новый пресет.\n"
            "Можно ввести диапазон через дефис (например 2-5) или комбинацию (1,3-4,7).\n"
            "Если хотите сначала создать новый вопрос — нажмите 'Создать свой вопрос'.\n"
            "Для отмены — нажмите 'Назад в меню'.\n\n"
            "Список вопросов:\n" + list_text
        )
        kb = simple_kb("Создать свой вопрос", "Назад в меню")
        await message.answer(instructions, reply_markup=kb)
        return

    if text == "Назад в меню":
        await state.clear()
        await message.answer("Вернулся в меню.", reply_markup=main_menu_kb())
        return

    # Ожидаем, что ввели номер пресета, возможно с форматом "1. preset #id"
    data = await state.get_data()
    mapping = data.get("preset_index_map", {})
    # Попробуем извлечь цифру в начале
    key = None
    if text.split(".")[0].isdigit():
        key = text.split(".")[0]
    elif text.isdigit():
        key = text
    else:
        # Пользователь ввёл что-то непонятное
        await message.answer(
            "Невалидный ввод. Введите номер пресета из списка, 'Создать свой пресет' или 'Назад в меню'."
        )
        return

    preset_id = mapping.get(key)
    if preset_id is None:
        await message.answer("Пресет с таким номером не найден. Попробуйте снова.")
        return

    # Показать детали пресета (список вопросов) и предложить отправку
    try:
        presets = await http_get("/presets")
        preset_obj = next((p for p in presets if p.get("id") == preset_id), None)
        if not preset_obj:
            await message.answer(
                "Не удалось найти пресет на сервере.", reply_markup=main_menu_kb()
            )
            await state.clear()
            return
        question_ids = preset_obj.get("questions", []) or []
        all_questions = await http_get("/questions")
        preset_questions = [q for q in all_questions if q.get("id") in question_ids]
    except Exception as e:
        await message.answer(
            f"Ошибка при получении данных пресета: {e}", reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    text_preview = (
        "Пресет #" + str(preset_id) + ":\n" + render_questions_list(preset_questions)
    )
    await state.update_data(
        selected_preset_id=preset_id, selected_preset_questions=preset_questions
    )
    await state.set_state(HRForm.viewing_preset_details)
    await message.answer(
        text_preview
        + "\n\nНажмите 'Отправить всем' чтобы разослать тексты вопросов или 'Назад в меню'.",
        reply_markup=simple_kb("Отправить всем", "Назад в меню"),
    )


async def hr_handle_creating_preset_questions(
    message: types.Message, state: FSMContext
):
    """
    Пользователь вводит номера вопросов (можно диапазоны) для нового пресета.
    """
    text = message.text.strip()
    if text == "Создать свой вопрос":
        await state.set_state(HRForm.creating_question_text)
        await message.answer("Введите текст нового вопроса:", reply_markup=cancel_kb())
        return
    if text == "Назад в меню":
        await state.clear()
        await message.answer("Отмена. Вернулся в меню.", reply_markup=main_menu_kb())
        return

    # разбор ввода: поддерживаем "1,3-5,7"
    def parse_selection(s: str) -> List[int]:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        nums: List[int] = []
        for part in parts:
            if "-" in part:
                a, b = part.split("-", 1)
                if a.strip().isdigit() and b.strip().isdigit():
                    a_i = int(a.strip())
                    b_i = int(b.strip())
                    if a_i <= b_i:
                        nums.extend(list(range(a_i, b_i + 1)))
                    else:
                        nums.extend(list(range(b_i, a_i + 1)))
                else:
                    raise ValueError("Диапазон содержит нечисловые значения.")
            else:
                if part.isdigit():
                    nums.append(int(part))
                else:
                    raise ValueError("Номер должен быть числом.")
        return sorted(set(nums))

    data = await state.get_data()
    qmap = data.get("question_index_map", {})
    data.get("all_questions", [])
    try:
        sel_numbers = parse_selection(text)
    except Exception as e:
        await message.answer(
            f"Не удалось распарсить выбор: {e}. Введите номера через запятую или диапазоны."
        )
        return

    # Перевод номеров в ids — проверка диапазона
    selected_ids = []
    for num in sel_numbers:
        key = str(num)
        qid = qmap.get(key)
        if qid is None:
            await message.answer(f"Номер {num} вне диапазона. Попробуйте снова.")
            return
        selected_ids.append(qid)

    # Сохраняем выбор и просим имя пресета
    await state.update_data(new_preset_question_ids=selected_ids)
    await state.set_state(HRForm.creating_preset_name)
    await message.answer(
        f"Выбрано {len(selected_ids)} вопросов для пресета. Введите имя (описание) пресета:",
        reply_markup=cancel_kb(),
    )


async def hr_create_preset_name(message: types.Message, state: FSMContext):
    """
    Получаем имя пресета и создаём его через POST /presets с {"questions":[ids]}
    """
    name = message.text.strip()
    if not name:
        await message.answer("Имя пресета не должно быть пустым.")
        return

    data = await state.get_data()
    qids = data.get("new_preset_question_ids", [])
    if not qids:
        await message.answer(
            "Не выбраны вопросы для пресета. Начните создание пресета заново.",
            reply_markup=main_menu_kb(),
        )
        await state.clear()
        return

    # Ваш API curl показывает, что /presets принимает {"questions":[0]}
    # Мы постим вопросы, а имя можно не передавать, если бэкенд не поддерживает его.
    # Чтобы сохранить имя — можно отправить дополнительное поле "name" если бэкенд поддержит.
    payload = {"questions": qids, "name": name}
    try:
        created = await http_post("/presets", payload)
    except Exception as e:
        await message.answer(
            f"Не удалось создать пресет: {e}", reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(f"Пресет создан: {created}", reply_markup=main_menu_kb())


async def hr_create_question_text(message: types.Message, state: FSMContext):
    """
    Создание нового вопроса (флоу): текст -> тип -> answer_fields
    """
    text = message.text.strip()
    if not text:
        await message.answer("Текст вопроса не должен быть пустым.")
        return
    await state.update_data(new_question_text=text)
    await state.set_state(HRForm.creating_question_type)
    await message.answer(
        "Введите тип вопроса (число, например 0):", reply_markup=cancel_kb()
    )


async def hr_create_question_type(message: types.Message, state: FSMContext):
    t = message.text.strip()
    if not t.isdigit():
        await message.answer("Тип должен быть числом. Попробуйте снова.")
        return
    await state.update_data(new_question_type=int(t))
    await state.set_state(HRForm.creating_question_answers)
    await message.answer(
        "Введите answer_fields (строка; в формате, принятом в вашем API):",
        reply_markup=cancel_kb(),
    )


async def hr_create_question_answers(message: types.Message, state: FSMContext):
    answers = message.text.strip()
    data = await state.get_data()
    qtext = data.get("new_question_text")
    qtype = data.get("new_question_type")
    if not qtext or qtype is None:
        await message.answer(
            "Внутренняя ошибка: отсутствуют данные вопроса. Попробуйте создать вопрос заново.",
            reply_markup=main_menu_kb(),
        )
        await state.clear()
        return

    payload = {
        "block_id": 0,  # блок не используется в новой логике; API требует поле block_id — ставим 0 или другой дефолт
        "question_text": qtext,
        "question_type": qtype,
        "answer_fields": answers,
    }
    try:
        created = await http_post("/questions", payload)
    except Exception as e:
        await message.answer(
            f"Не удалось создать вопрос: {e}", reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    # После создания вопроса возвращаемся к созданию пресета, если в state был flow создания пресета
    await state.get_data()
    # Если до создания вопроса мы были в процессе выбора вопросов — загрузим все вопросы снова и попросим выбрать
    await state.clear()
    await message.answer(
        f"Вопрос создан: {created}\nЕсли хотите, начните создание пресета заново (HR: Опросы).",
        reply_markup=main_menu_kb(),
    )


async def hr_viewing_preset_details(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text == "Отправить всем":
        data = await state.get_data()
        preset_id = data.get("selected_preset_id")
        if preset_id is None:
            await message.answer("Не выбран пресет.", reply_markup=main_menu_kb())
            await state.clear()
            return
        # подтверждение отправки
        await state.set_state(HRForm.confirming_send_preset)
        await message.answer(
            "Подтвердите отправку пресета всем пользователям (Отправить всем / Отмена):",
            reply_markup=simple_kb("Отправить всем", "Отмена"),
        )
        return
    if text == "Назад в меню":
        await state.clear()
        await message.answer("Вернулся в меню.", reply_markup=main_menu_kb())
        return
    await message.answer(
        "Используйте кнопки: Отправить всем / Назад в меню.",
        reply_markup=simple_kb("Отправить всем", "Назад в меню"),
    )


async def hr_confirm_send(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text == "Отмена":
        await state.clear()
        await message.answer("Отправка отменена.", reply_markup=main_menu_kb())
        return
    if text != "Отправить всем":
        await message.answer("Нажмите 'Отправить всем' или 'Отмена'.")
        return

    data = await state.get_data()
    preset_id = data.get("selected_preset_id")
    if preset_id is None:
        await message.answer(
            "Не выбран пресет для отправки.", reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    try:
        # Получаем пресет и вопросы
        presets = await http_get("/presets")
        preset_obj = next((p for p in presets if p.get("id") == preset_id), None)
        if not preset_obj:
            raise RuntimeError("Preset not found on server")
        question_ids = preset_obj.get("questions", [])
        all_questions = await http_get("/questions")
        questions = [q for q in all_questions if q.get("id") in question_ids]
    except Exception as e:
        await message.answer(
            f"Не удалось получить данные пресета: {e}", reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    # Формируем текст оповещения: просто перечисление текстов вопросов
    text_to_send = [f"Опрос (пресет #{preset_id}):"]
    for q in questions:
        text_to_send.append(q.get("question_text") or "(пустой текст)")
    payload_text = "\n\n".join(text_to_send)

    users = load_users()
    successes = []
    failures = {}
    bot = message.bot
    for sid, uname in users.items():
        try:
            await bot.send_message(chat_id=int(sid), text=payload_text)
            successes.append(sid)
        except Exception as e:
            failures[sid] = str(e)
        await asyncio.sleep(0.05)

    report = f"Отправлено: {len(successes)}. Ошибки: {len(failures)}"
    await state.clear()
    await message.answer(report, reply_markup=main_menu_kb())


# =======================
# Утилиты
# =======================
def _parse_user_id(text: str) -> Optional[str]:
    try:
        return text.strip()
    except Exception:
        return None


# =======================
# Main / регистрация хендлеров
# =======================
async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise RuntimeError("Установите переменную окружения BOT_TOKEN с токеном бота.")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Команды и кнопки
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(start_create_poll, F.text == BTN_CREATE_POLL)
    dp.message.register(start_summary, F.text == BTN_SUMMARY)
    dp.message.register(start_registration, F.text == BTN_REGISTER)
    dp.message.register(cancel_handler, F.text == BTN_CANCEL)
    dp.message.register(show_registered_users, F.text == BTN_LIST_USERS)


    # HR navigation entry button
    dp.message.register(hr_start_presets, F.text == BTN_HR)

    # Обработка ввода ID по состояниям
    dp.message.register(sc_subject_user_id, SurveyCreateForm.waiting_subject_user_id)
    dp.message.register(sc_reviewer_user_ids, SurveyCreateForm.waiting_reviewer_user_ids)
    dp.message.register(sc_review_type, SurveyCreateForm.waiting_review_type)
    dp.message.register(sc_question_ids, SurveyCreateForm.waiting_question_ids)
    dp.message.register(sc_deadline, SurveyCreateForm.waiting_deadline)
    dp.message.register(sc_notifications_before, SurveyCreateForm.waiting_notifications_before)
    dp.message.register(sc_anonymous, SurveyCreateForm.waiting_anonymous)
    dp.message.register(sc_title, SurveyCreateForm.waiting_title)
    dp.message.register(sc_confirm, SurveyCreateForm.confirming)

    # === Ветка блок → вопросы → пресет (как у тебя уже есть) ===
    dp.message.register(sc_block_decision, SurveyCreateForm.waiting_block_decision)
    dp.message.register(sc_block_name, SurveyCreateForm.waiting_block_name)
    dp.message.register(sc_new_question_text, SurveyCreateForm.waiting_new_question_text)
    dp.message.register(sc_new_question_type, SurveyCreateForm.waiting_new_question_type)
    dp.message.register(sc_new_question_answers, SurveyCreateForm.waiting_new_question_answers)
    dp.message.register(sc_add_more_questions, SurveyCreateForm.waiting_add_more_questions)

    dp.message.register(handle_user_id_for_summary, Form.waiting_user_id_for_summary)

    # Обработчик загрузки Excel при регистрации пользователей
    dp.message.register(handle_registration_file, Form.waiting_file_for_registration)

    # HR navigation handlers (states)
    dp.message.register(hr_handle_presets_choice, HRForm.viewing_presets)
    dp.message.register(
        hr_handle_creating_preset_questions, HRForm.creating_preset_questions
    )
    dp.message.register(hr_create_preset_name, HRForm.creating_preset_name)
    dp.message.register(hr_create_question_text, HRForm.creating_question_text)
    dp.message.register(hr_create_question_type, HRForm.creating_question_type)
    dp.message.register(hr_create_question_answers, HRForm.creating_question_answers)
    dp.message.register(hr_viewing_preset_details, HRForm.viewing_preset_details)
    dp.message.register(hr_confirm_send, HRForm.confirming_send_preset)

    # dp.message.register(start_compute_summary, F.text == BTN_SUMMARY_Q)
    # dp.message.register(sc_batch_id, SummaryComputeForm.waiting_batch_id)
    # dp.message.register(sc_model_name, SummaryComputeForm.waiting_model_name)
    # dp.message.register(sc_prompt_version, SummaryComputeForm.waiting_prompt_version)

    dp.message.register(start_local_summarize_by_batch, F.text == BTN_SUMMARY_Q)

    # dp.message.register(ls_reviews_or_text, LocalSummForm.waiting_reviews_or_text)
    # dp.message.register(ls_system_prompt, LocalSummForm.waiting_system_prompt)
    # dp.message.register(ls_user_prompt, LocalSummForm.waiting_user_prompt)
    dp.message.register(lsb_batch_id, LocalSummForm.waiting_batch_id)
    dp.message.register(lsb_system_prompt, LocalSummForm.waiting_system_prompt)
    dp.message.register(lsb_user_prompt, LocalSummForm.waiting_user_prompt)


    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        import traceback

        print("Ошибка при запуске бота:")
        traceback.print_exc()
        input("Нажмите Enter, чтобы закрыть окно...")
