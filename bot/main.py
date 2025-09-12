import asyncio
import logging
from typing import Optional, Tuple, List, Dict
from aiogram import Bot, Dispatcher, F, types
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
import tempfile
import os
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
    BTN_HR
)


# =======================
# Настройки / константы
# =======================


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


# =======================
# Keyboards
# =======================
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CREATE_POLL)],
            [KeyboardButton(text=BTN_SUMMARY)],
            [KeyboardButton(text=BTN_REGISTER)],
            [KeyboardButton(text=BTN_HR)],
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
    url = API_BASE.rstrip("/") + path
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()


async def http_post(path: str, json_body: dict):
    url = API_BASE.rstrip("/") + path
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=json_body) as resp:
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


# =======================
# Handlers: старт/основные (unchanged)
# =======================
async def cmd_start(message: types.Message):
    register_user(message.from_user.id, message.from_user.username)
    await message.answer("Выберите действие:", reply_markup=main_menu_kb())


async def start_create_poll(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_user_id_for_poll)
    await message.answer(
        "Введите идентификатор пользователя для создания опроса:",
        reply_markup=cancel_kb(),
    )


async def start_summary(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_user_id_for_summary)
    await message.answer(
        "Введите идентификатор пользователя для суммаризации:", reply_markup=cancel_kb()
    )


async def start_registration(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_file_for_registration)
    await message.answer(
        "Отправьте Excel-файл (.xlsx) с колонками: username, ФИО, email. Username — без ведущего @.",
        reply_markup=cancel_kb(),
    )


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


# =======================
# Регистрация Excel (unchanged)
# =======================
async def handle_registration_file(message: types.Message, state: FSMContext):
    if not message.document:
        await message.answer(
            "Пожалуйста, отправьте файл в формате .xlsx.", reply_markup=cancel_kb()
        )
        return

    file_name = message.document.file_name or "file"
    if not (file_name.lower().endswith(".xlsx") or file_name.lower().endswith(".xls")):
        await message.answer(
            "Файл должен быть Excel (.xlsx или .xls). Попробуйте снова.",
            reply_markup=cancel_kb(),
        )
        return

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_name).suffix)
    tmp_path = tmp.name
    tmp.close()

    bot: Bot = message.bot

    # --- скачивание файла (поддержка разных версий aiogram) ---
    try:
        download = getattr(message.document, "download", None)
        if callable(download):
            await message.document.download(destination_file=tmp_path)
        else:
            # fallback: get_file + прямой запрос к Telegram file API
            file_obj = await bot.get_file(message.document.file_id)
            file_path = file_obj.file_path
            download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

            def _download_sync():
                urllib.request.urlretrieve(download_url, tmp_path)

            await asyncio.get_event_loop().run_in_executor(None, _download_sync)
    except Exception as e:
        await state.clear()
        await message.answer(
            f"Не удалось скачать файл: {e}", reply_markup=main_menu_kb()
        )
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
        await message.answer(
            f"Не удалось прочитать Excel: {e}", reply_markup=main_menu_kb()
        )
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return

    # удаляем временный xlsx
    try:
        os.remove(tmp_path)
    except OSError:
        pass

    # Нормализация колонок (ищем username, ФИО (fio), email)
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
        await message.answer(
            "В файле отсутствует колонка 'username'. Убедитесь, что она есть и попробуйте снова.",
            reply_markup=main_menu_kb(),
        )
        return

    # Подготовка рассылки
    send_template = "привет, {fio}!"  # можно менять; {fio} заменится если есть
    successes = []
    failures = {}

    # Проходим по строкам
    for idx, row in df.iterrows():
        raw_username = row[col_map["username"]]
        if pd.isna(raw_username):
            failures[f"row_{idx}"] = "username пустой"
            continue
        username = str(raw_username).strip()
        if username.startswith("@"):
            username = username[1:]
        if not username:
            failures[f"row_{idx}"] = "username оказался пустым после очистки"
            continue

        # формируем персонализованный текст, если есть ФИО
        fio_val = None
        if "fio" in col_map:
            raw_fio = row[col_map["fio"]]
            if not pd.isna(raw_fio):
                fio_val = str(raw_fio).strip()
        if fio_val:
            send_text = send_template.format(fio=fio_val)
        else:
            send_text = "привет мир"

        # Попытка разрешить username -> chat (get_chat может вернуть chat.id)
        chat_id = get_chat_id_by_username(username)

        if chat_id is None:
            failures[username] = (
                "user not found in local db (он не нажимал /start у бота)"
            )
            continue

        # Если получили numeric chat_id — пробуем отправить
        try:
            await bot.send_message(chat_id=chat_id, text=send_text)
            successes.append(username)
        except TelegramAPIError as e:
            failures[username] = f"send_message TelegramAPIError: {e}"
        except Exception as e:
            failures[username] = f"send_message Exception: {e}"

        # Небольшая задержка, чтобы не перегружать API (можно уменьшить/увеличить при необходимости)
        await asyncio.sleep(0.05)

    # Формируем отчёт
    total = len(successes) + len(failures)
    report_lines = [
        f"Обработано записей: {total}",
        f"Отправлено успешно: {len(successes)}",
        f"Ошибок: {len(failures)}",
    ]
    if successes:
        report_lines.append(
            "Успешные username (первые 50): " + ", ".join(successes[:50])
        )
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
    all_questions = data.get("all_questions", [])
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
    data_prev = await state.get_data()
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

    # HR navigation entry button
    dp.message.register(hr_start_presets, F.text == BTN_HR)

    # Обработка ввода ID по состояниям
    dp.message.register(handle_user_id_for_poll, Form.waiting_user_id_for_poll)
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

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        import traceback

        print("Ошибка при запуске бота:")
        traceback.print_exc()
        input("Нажмите Enter, чтобы закрыть окно...")
