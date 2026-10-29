#!/usr/bin/env python3
"""
ربات آموزشی تلگرام: بخش‌ها (پنل‌ها) ← درس‌ها ← قدم‌ها
- محتوا کامل از داخل خود تلگرام (/admin) اضافه می‌شود، بدون دست‌زدن به کد.
- دستورهای ترمینال داخل بلوک کد (<pre>) می‌روند و با یک لمس کپی می‌شوند.
- متغیرهای {IP} {USER} {GITHUB_USER} {REPO_URL} {REPO_NAME} در متن درس‌ها
  خودکار با اطلاعات هر کاربر جایگزین می‌شوند.
- اشتراک: درس‌های رایگان باز، بقیه قفل. تأیید پرداخت فعلاً دستی توسط ادمین.

اجرا:  BOT_TOKEN=... ADMIN_IDS=123456789 python bot.py
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import logging
import os
import re
import time

import aiosqlite
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message)

# ───────────────────────── تنظیمات ─────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in re.split(r"[,\s]+", os.getenv("ADMIN_IDS", "")) if x.strip().isdigit()}
DB_PATH = os.getenv("DB_PATH", "bot.db")
# هشدار: با PROTECT_CONTENT=1 کاربر دیگر نمی‌تواند متن/کد را کپی کند. پیش‌فرض خاموش.
PROTECT = os.getenv("PROTECT_CONTENT", "0") == "1"

WELCOME = (
    "👋 سلام! اینجا قدم‌به‌قدم یاد می‌گیری چطور با گیت‌هاب و سرور و هوش مصنوعی کار کنی.\n\n"
    "💡 اول از «⚙️ تنظیمات من» آی‌پی سرورت رو ثبت کن تا همه‌ی دستورها با اطلاعات خودت آماده بشن.\n"
    "هر دستوری که توی کادر کد دیدی، رویش بزن تا کپی بشه."
)
DEFAULT_PAY_TEXT = (
    "💎 <b>اشتراک</b>\n\n"
    "با خرید اشتراک همه‌ی درس‌ها باز می‌شن.\n"
    "قیمت و روش پرداخت رو ادمین با /admin ← «متن پرداخت» تنظیم می‌کنه."
)

DB: aiosqlite.Connection

# ───────────────────────── دیتابیس ─────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS sections(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, pos INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS lessons(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
  title TEXT NOT NULL, is_free INTEGER NOT NULL DEFAULT 0, pos INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS steps(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  text TEXT NOT NULL DEFAULT '', photo TEXT, cmd TEXT, pos INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY, name TEXT, server_ip TEXT, server_user TEXT,
  github_user TEXT, repo_url TEXT, sub_until INTEGER NOT NULL DEFAULT 0, joined INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


async def q_all(sql: str, args: tuple = ()):
    async with DB.execute(sql, args) as cur:
        return await cur.fetchall()


async def q_one(sql: str, args: tuple = ()):
    async with DB.execute(sql, args) as cur:
        return await cur.fetchone()


async def q_run(sql: str, args: tuple = ()) -> int:
    cur = await DB.execute(sql, args)
    await DB.commit()
    return cur.lastrowid


async def next_pos(table: str, where: str = "1=1", args: tuple = ()) -> int:
    row = await q_one(f"SELECT COALESCE(MAX(pos),0)+1 AS n FROM {table} WHERE {where}", args)
    return row["n"]


async def get_setting(key: str, default: str = "") -> str:
    row = await q_one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


async def set_setting(key: str, value: str) -> None:
    await q_run(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


async def get_user(uid: int, name: str = ""):
    row = await q_one("SELECT * FROM users WHERE user_id=?", (uid,))
    if not row:
        await q_run("INSERT INTO users(user_id,name,joined) VALUES(?,?,?)", (uid, name, int(time.time())))
        row = await q_one("SELECT * FROM users WHERE user_id=?", (uid,))
    return row


async def has_access(uid: int) -> bool:
    if uid in ADMIN_IDS:
        return True
    row = await q_one("SELECT sub_until FROM users WHERE user_id=?", (uid,))
    return bool(row and row["sub_until"] > time.time())


async def grant(uid: int, days: int) -> int:
    row = await get_user(uid)
    until = int(max(row["sub_until"], time.time()) + days * 86400)
    await q_run("UPDATE users SET sub_until=? WHERE user_id=?", (until, uid))
    return until


# ─────────────────── متغیرهای کاربر ({IP} و ...) ───────────────────
def valid_ip(v: str):
    try:
        return str(ipaddress.ip_address(v.strip()))
    except ValueError:
        return None


def valid_user(v: str):
    v = v.strip()
    return v if re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", v) else None


def valid_gh(v: str):
    v = v.strip().lstrip("@")
    return v if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", v) else None


def valid_repo(v: str):
    m = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?", v.strip().rstrip("/"))
    return f"https://github.com/{m.group(1)}/{m.group(2)}.git" if m else None


# کلید دیتابیس: (برچسب دکمه، تابع اعتبارسنجی، راهنما)
USER_FIELDS = {
    "server_ip": ("🌐 آی‌پی سرور", valid_ip, "آی‌پی سرورت رو بفرست. مثال: <code>203.0.113.10</code>"),
    "server_user": ("👤 یوزر سرور", valid_user, "یوزر سرور رو بفرست (معمولاً <code>root</code>)."),
    "github_user": ("🐙 یوزرنیم گیت‌هاب", valid_gh, "یوزرنیم گیت‌هابت رو بفرست."),
    "repo_url": ("📦 لینک ریپازیتوری", valid_repo,
                 "لینک ریپازیتوری رو بفرست. مثال: <code>https://github.com/ali/my-bot</code>"),
}


def build_vars(u) -> dict[str, str]:
    gh = (u["github_user"] if u else None) or "YOUR_GITHUB_USERNAME"
    repo = (u["repo_url"] if u else None) or f"https://github.com/{gh}/REPO_NAME.git"
    return {
        "IP": (u["server_ip"] if u else None) or "SERVER_IP",
        "USER": (u["server_user"] if u else None) or "root",
        "GITHUB_USER": gh,
        "REPO_URL": repo,
        "REPO_NAME": repo.rsplit("/", 1)[-1].removesuffix(".git"),
    }


VAR_RE = re.compile(r"\{(IP|USER|GITHUB_USER|REPO_URL|REPO_NAME)\}")


def render(text: str, vars_: dict[str, str]) -> str:
    return VAR_RE.sub(lambda m: html.escape(vars_[m.group(1)]), text)


def md_fallback(t: str) -> str:
    """اگر ادمین ``` یا ` تایپ کرده و تلگرام تبدیل نکرده بود، به تگ HTML تبدیل می‌شود."""
    t = re.sub(r"```(?:\w+\n)?(.*?)```", lambda m: f"<pre>{m.group(1).strip()}</pre>", t, flags=re.S)
    return re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)


# ───────────────────────── ابزارهای رابط ─────────────────────────
def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """پیام فعلی را ویرایش می‌کند؛ اگر نشد (مثلاً عکس بود) حذف و دوباره می‌فرستد."""
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" in str(e):
            return
        try:
            await cb.message.delete()
        except TelegramBadRequest:
            pass
        await cb.message.answer(text, reply_markup=kb)


async def main_menu(uid: int) -> InlineKeyboardMarkup:
    secs = await q_all("SELECT id,title FROM sections ORDER BY pos,id")
    rows = [[btn(s["title"], f"s:{s['id']}")] for s in secs]
    rows.append([btn("🪄 پرامپت‌ساز", "pb"), btn("⚙️ تنظیمات من", "me")])
    rows.append([btn("🤖 ساخت ربات", "bx:bots"), btn("📱 ساخت اپلیکیشن", "bx:app")])
    rows.append([btn("💎 اشتراک آموزش", "sub")])
    if uid in ADMIN_IDS:
        rows.append([btn("🛠 پنل مدیریت", "adm")])
    return markup(rows)


def chunks_escaped(raw: str, limit: int = 3600) -> list[str]:
    """متن خام را به تکه‌هایی می‌شکند که بعد از escape زیر محدودیت تلگرام بمانند."""
    lines: list[str] = []
    for line in raw.split("\n"):
        lines.extend(line[i:i + 800] for i in range(0, max(len(line), 1), 800))
    out, cur = [], ""
    for line in lines:
        if cur and len(html.escape(cur + "\n" + line)) > limit:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return [html.escape(c) for c in out]


# ───────────────────────── وضعیت‌ها (FSM) ─────────────────────────
class AddSection(StatesGroup):
    title = State()


class AddLesson(StatesGroup):
    title = State()
    free = State()


class AddSteps(StatesGroup):
    collect = State()
    cmd = State()


class EditPay(StatesGroup):
    text = State()


class SetVar(StatesGroup):
    value = State()


class Pay(StatesGroup):
    waiting = State()


class PB(StatesGroup):
    answer = State()


class AutoAnswer(BaseMiddleware):
    """به همه‌ی کلیک‌ها همان لحظه جواب می‌دهد تا دکمه معطل نماند."""

    async def __call__(self, handler, event, data):
        try:
            await event.answer()
        except TelegramBadRequest:
            pass
        return await handler(event, data)


common, admin, user = Router(), Router(), Router()
admin.message.filter(F.from_user.id.in_(ADMIN_IDS))
admin.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


# ═════════════════════════ عمومی ═════════════════════════
@common.message(Command("start", "menu"))
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await get_user(m.from_user.id, m.from_user.full_name)
    await m.answer(WELCOME, reply_markup=await main_menu(m.from_user.id))


@common.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("لغو شد.", reply_markup=await main_menu(m.from_user.id))


@common.callback_query(F.data == "home")
async def cb_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(cb, WELCOME, await main_menu(cb.from_user.id))


@common.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    return


# ═════════════════════════ کاربر: بخش‌ها و درس‌ها ═════════════════════════
@user.callback_query(F.data.startswith("s:"))
async def cb_section(cb: CallbackQuery):
    sid = int(cb.data.split(":")[1])
    sec = await q_one("SELECT * FROM sections WHERE id=?", (sid,))
    if not sec:
        return await cb.message.answer("بخش پیدا نشد")
    lessons = await q_all("SELECT * FROM lessons WHERE section_id=? ORDER BY pos,id", (sid,))
    access = await has_access(cb.from_user.id)
    rows = [[btn(("" if (l["is_free"] or access) else "🔒 ") + l["title"], f"l:{l['id']}")] for l in lessons]
    rows.append([btn("🔙 منو", "home")])
    body = "یک درس انتخاب کن 👇" if lessons else "هنوز درسی اینجا اضافه نشده."
    await show(cb, f"<b>{html.escape(sec['title'])}</b>\n\n{body}", markup(rows))


@user.callback_query(F.data.startswith("l:"))
async def cb_lesson(cb: CallbackQuery):
    lid = int(cb.data.split(":")[1])
    lesson = await q_one("SELECT * FROM lessons WHERE id=?", (lid,))
    if not lesson:
        return await cb.message.answer("درس پیدا نشد.")
    if not (lesson["is_free"] or await has_access(cb.from_user.id)):
        return await show_sub(cb)
    ok = await send_lesson(cb.bot, cb.message.chat.id, cb.from_user.id, cb.from_user.full_name, lid)
    if not ok:
        await cb.message.answer("این درس هنوز محتوایی ندارد.")


CODE_TAGS = re.compile(r"</?(?:pre|code)[^>]*>")


def strip_code(t: str) -> str:
    """توضیح قابل‌کپی نباشد: تگ‌های کد از متن توضیح حذف می‌شود."""
    return CODE_TAGS.sub("", t)


def subst(raw: str, vars_: dict[str, str]) -> str:
    return VAR_RE.sub(lambda m: vars_[m.group(1)], raw)


def copy_chunks(cmd: str, limit: int = 256) -> list[str]:
    """دکمه‌ی کپی تلگرام حداکثر ۲۵۶ حرف می‌گیرد؛ دستورها خط‌به‌خط در چند تکه جمع می‌شوند."""
    chunks, cur = [], ""
    for line in (ln.rstrip() for ln in cmd.splitlines() if ln.strip()):
        if len(line) > limit:
            continue  # خط خیلی بلند: فقط داخل کادر کد کپی می‌شود
        if cur and len(cur) + 1 + len(line) > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def copy_rows(cmd: str) -> list[list[InlineKeyboardButton]]:
    chunks = copy_chunks(cmd)
    if len(chunks) == 1:
        return [[InlineKeyboardButton(text="📋 کپی دستورها", copy_text=CopyTextButton(text=chunks[0]))]]
    return [[InlineKeyboardButton(text=f"📋 کپی {i}", copy_text=CopyTextButton(text=c))]
            for i, c in enumerate(chunks, 1)]


async def send_lesson(bot: Bot, chat_id: int, uid: int, name: str, lid: int) -> bool:
    """هر قدم یک پیام: توضیح ساده + (اگر دستور دارد) کادر دستور و دکمه‌ی «📋 کپی»."""
    lesson = await q_one("SELECT * FROM lessons WHERE id=?", (lid,))
    steps = await q_all("SELECT * FROM steps WHERE lesson_id=? ORDER BY pos,id", (lid,))
    if not lesson or not steps:
        return False
    u = await get_user(uid, name)
    v = build_vars(u)
    needs_ip = not u["server_ip"] and any("{IP}" in (st["text"] + (st["cmd"] or "")) for st in steps)
    title = f"<b>{html.escape(lesson['title'])}</b>"
    for i, st in enumerate(steps):
        last = i == len(steps) - 1
        text = strip_code(render(st["text"], v)).strip()
        cmd = subst(st["cmd"], v).strip() if st["cmd"] else ""
        if i == 0:
            text = f"{title}\n\n{text}" if text else title
        if cmd:
            text += f"\n\n<pre>{html.escape(cmd)}</pre>"
        rows = copy_rows(cmd) if cmd else []
        if last:
            if needs_ip:
                rows.append([btn("🌐 ثبت آی‌پی سرورم", "sv:server_ip")])
                text += "\n\n💡 آی‌پی سرورت رو ثبت کن تا دستورها با آی‌پی خودت ساخته بشن."
            rows.append([btn("🔙 برگشت", f"s:{lesson['section_id']}")])
        mk = markup(rows) if rows else None
        photo = st["photo"]
        if photo and len(text) <= 1024:
            await bot.send_photo(chat_id, photo, caption=text, reply_markup=mk, protect_content=PROTECT)
        elif photo:
            await bot.send_photo(chat_id, photo, protect_content=PROTECT)
            await bot.send_message(chat_id, text[:4096], reply_markup=mk, protect_content=PROTECT)
        else:
            await bot.send_message(chat_id, text[:4096], reply_markup=mk, protect_content=PROTECT)
    return True


# ═════════════════════════ کاربر: تنظیمات من ═════════════════════════
@user.callback_query(F.data == "me")
async def cb_me(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    u = await get_user(cb.from_user.id, cb.from_user.full_name)
    v = build_vars(u)
    lines = [f"{label}: <code>{html.escape(u[key])}</code>" if u[key] else f"{label}: —"
             for key, (label, _, _) in USER_FIELDS.items()]
    text = (
        "⚙️ <b>تنظیمات من</b>\n\n" + "\n".join(lines) +
        f"\n\nدستور اتصال تو الان این شکلیه:\n<pre>ssh {html.escape(v['USER'])}@{html.escape(v['IP'])}</pre>"
        "⚠️ رمز سرور یا کلید خصوصی رو هرگز برای ربات نفرست."
    )
    rows = [[btn(label, f"sv:{key}")] for key, (label, _, _) in USER_FIELDS.items()]
    rows.append([btn("🔙 منو", "home")])
    await show(cb, text, markup(rows))


@user.callback_query(F.data.startswith("sv:"))
async def cb_setvar(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[1]
    if key not in USER_FIELDS:
        return
    await state.set_state(SetVar.value)
    await state.update_data(key=key)
    await show(cb, USER_FIELDS[key][2] + "\n\nبرای لغو: /cancel")


@user.message(StateFilter(SetVar.value))
async def msg_setvar(m: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    label, validator, hint = USER_FIELDS[key]
    value = validator(m.text or "")
    if not value:
        return await m.answer("❌ فرمت درست نیست.\n" + hint)
    await q_run(f"UPDATE users SET {key}=? WHERE user_id=?", (value, m.from_user.id))
    await state.clear()
    await m.answer(f"✅ {label} ثبت شد: <code>{html.escape(value)}</code>",
                   reply_markup=markup([[btn("⚙️ تنظیمات من", "me"), btn("🏠 منو", "home")]]))


# ═════════════════════════ کاربر: اشتراک و پرداخت ═════════════════════════
async def show_sub(cb: CallbackQuery) -> None:
    text = await get_setting("pay_text", DEFAULT_PAY_TEXT)
    u = await get_user(cb.from_user.id)
    if u["sub_until"] > time.time():
        left = int((u["sub_until"] - time.time()) // 86400) + 1
        text += f"\n\n✅ اشتراک تو فعاله ({left} روز مونده)."
    await show(cb, text, markup([[btn("✅ پرداخت کردم، ارسال رسید", "paid")], [btn("🔙 منو", "home")]]))


@user.callback_query(F.data == "sub")
async def cb_sub(cb: CallbackQuery):
    await show_sub(cb)


@user.callback_query(F.data == "paid")
async def cb_paid(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Pay.waiting)
    await show(cb, "هش تراکنش یا عکس رسید رو همین‌جا بفرست تا ادمین بررسی کنه.\nبرای لغو: /cancel")


@user.message(StateFilter(Pay.waiting))
async def msg_paid(m: Message, state: FSMContext):
    await state.clear()
    u = m.from_user
    kb = markup([[btn("✅ ۳۰ روز", f"ap:{u.id}:30"), btn("✅ ۹۰ روز", f"ap:{u.id}:90")],
                 [btn("❌ رد", f"ap:{u.id}:0")]])
    for aid in ADMIN_IDS:
        try:
            await m.forward(aid)
            await m.bot.send_message(aid, f"💳 درخواست اشتراک از {html.escape(u.full_name)} (<code>{u.id}</code>)",
                                     reply_markup=kb)
        except TelegramBadRequest:
            logging.warning("ارسال به ادمین %s ناموفق بود", aid)
    await m.answer("✅ دریافت شد. بعد از بررسی، اشتراکت فعال می‌شه و خبرت می‌کنم.",
                   reply_markup=await main_menu(u.id))


# ═════════════════════════ کاربر: پرامپت‌ساز ═════════════════════════
PB_TEMPLATES = {
    "new": ("🆕 ساخت کد/پروژه جدید", [
        ("goal", "چی می‌خوای بسازی؟ کوتاه و دقیق بنویس.", 600),
        ("lang", "زبان و نسخه؟ مثلاً: Python 3.11", 100),
        ("env", "کجا اجرا می‌شه؟ مثلاً: اوبونتو ۲۲ روی سرور مجازی", 200),
        ("libs", "کتابخونه یا ابزار خاصی لازم داری؟ نمی‌دونی؟ بنویس: پیشنهاد بده", 300),
        ("io", "ورودی و خروجی برنامه چیه؟", 500),
    ]),
    "fix": ("🐞 رفع خطا", [
        ("code", "کدی که خطا می‌ده رو بفرست.", 2000),
        ("error", "متن کامل خطا رو بفرست.", 1000),
        ("env", "محیط اجرا و نسخه‌ها؟ مثلاً: اوبونتو ۲۲، Python 3.11", 200),
        ("did", "قبل از خطا دقیقاً چه کاری کردی؟", 400),
    ]),
}


def make_prompt(kind: str, a: dict[str, str]) -> str:
    rules = [
        "## قوانین پاسخ",
        "1. کد کامل و قابل اجرا بده، نه تکه‌تکه و نه با «...».",
        "2. اول ساختار فایل‌ها را بنویس، بعد کد هر فایل را جدا.",
        "3. دستورهای نصب و اجرا را مرحله‌به‌مرحله و قابل کپی در ترمینال بنویس.",
        "4. اگر اطلاعاتی کم بود، قبل از نوشتن کد حداکثر ۳ سؤال کوتاه بپرس.",
        "5. در پایان بگو چطور تست کنم و چه خطاهای رایجی ممکن است پیش بیاید.",
    ]
    if kind == "new":
        head = [f"تو یک برنامه‌نویس ارشد {a['lang']} هستی.", "", "## هدف", a["goal"], "", "## مشخصات فنی",
                f"- زبان و نسخه: {a['lang']}", f"- محیط اجرا: {a['env']}",
                f"- کتابخانه‌ها: {a['libs']}", f"- ورودی/خروجی: {a['io']}", ""]
    else:
        head = ["تو یک متخصص دیباگ هستی. علت خطا را پیدا کن و نسخه‌ی اصلاح‌شده را بده.", "",
                "## کد", a["code"], "", "## متن خطا", a["error"], "",
                "## محیط", a["env"], "", "## قبل از خطا چه کردم", a["did"], ""]
        rules[1] = "1. اول در دو خط علت دقیق خطا را بگو، بعد کد کامل اصلاح‌شده را بده."
    return "\n".join(head + rules)


@user.callback_query(F.data == "pb")
async def cb_pb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    rows = [[btn(t[0], f"pbt:{k}")] for k, t in PB_TEMPLATES.items()] + [[btn("🔙 منو", "home")]]
    await show(cb, "🪄 <b>پرامپت‌ساز</b>\n\nچند سؤال کوتاه جواب بده، من یک پرامپت کامل و دقیق برای هوش مصنوعی "
                   "(ChatGPT، Claude و ...) آماده می‌کنم. کدوم رو می‌خوای؟", markup(rows))


@user.callback_query(F.data.startswith("pbt:"))
async def cb_pbt(cb: CallbackQuery, state: FSMContext):
    kind = cb.data.split(":")[1]
    await state.set_state(PB.answer)
    await state.update_data(kind=kind, i=0, a={})
    await show(cb, f"سؤال ۱ از {len(PB_TEMPLATES[kind][1])}:\n\n{PB_TEMPLATES[kind][1][0][1]}\n\nبرای لغو: /cancel")


@user.message(StateFilter(PB.answer))
async def msg_pb(m: Message, state: FSMContext):
    data = await state.get_data()
    kind, i, answers = data["kind"], data["i"], data["a"]
    questions = PB_TEMPLATES[kind][1]
    key, _, limit = questions[i]
    text = (m.text or "").strip()
    if not text:
        return await m.answer("لطفاً متن بفرست.")
    if len(text) > limit:
        return await m.answer(f"❌ این جواب بلنده ({len(text)} حرف). حداکثر {limit} حرف، کوتاه‌ترش کن.")
    answers[key] = text
    if i + 1 < len(questions):
        await state.update_data(i=i + 1, a=answers)
        return await m.answer(f"سؤال {i + 2} از {len(questions)}:\n\n{questions[i + 1][1]}")
    await state.clear()
    for part in chunks_escaped(make_prompt(kind, answers)):
        await m.answer(f"<pre>{part}</pre>")
    await m.answer("✅ پرامپت آماده‌ست. روی کادر بزن تا کپی بشه و توی هوش مصنوعی بچسبون.\n"
                   "اگه جواب خطا داشت، متن خطا رو با «🐞 رفع خطا» بساز و بفرست.",
                   reply_markup=markup([[btn("🪄 یکی دیگه", "pb"), btn("🏠 منو", "home")]]))


# ═════════════════════════ ادمین ═════════════════════════
ADMIN_HELP = (
    "🛠 <b>پنل مدیریت</b>\n\n"
    "• «افزودن قدم»: اول متن توضیح (ساده، قابل‌کپی نیست)، بعد لیست دستورها (به‌صورت دکمه‌ی «📋 کپی»).\n"
    "• متغیرها (در توضیح یا دستورها): <code>{IP}</code> <code>{USER}</code> <code>{GITHUB_USER}</code> "
    "<code>{REPO_URL}</code> <code>{REPO_NAME}</code>\n"
    "• اشتراک آموزش دستی: <code>/grant آیدی_کاربر تعداد_روز</code>"
)


def admin_panel() -> InlineKeyboardMarkup:
    return markup([
        [btn("➕ بخش جدید", "a:sec"), btn("➕ درس جدید", "a:les")],
        [btn("📝 افزودن قدم به درس", "a:stp")],
        [btn("🗑 حذف", "a:del"), btn("💳 متن اشتراک آموزش", "a:pay")],
        [btn("🧩 قالب‌های ربات (پایتون)", "bxa:tpl"), btn("🤖 ربات‌های کاربران", "bxa:bots")],
        [btn("📦 سفارش‌های اپ", "bxa:orders"), btn("💳 اطلاعات واریز", "bxa:payinfo")],
        [btn("📊 آمار", "a:stat"), btn("🏠 منو", "home")],
    ])


async def pick_section(cb: CallbackQuery, prefix: str, text: str) -> None:
    secs = await q_all("SELECT id,title FROM sections ORDER BY pos,id")
    if not secs:
        return await cb.message.answer("اول یک بخش بساز")
    rows = [[btn(s["title"], f"{prefix}:{s['id']}")] for s in secs] + [[btn("🔙 پنل", "adm")]]
    await show(cb, text, markup(rows))


@admin.message(Command("admin"))
async def cmd_admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(ADMIN_HELP, reply_markup=admin_panel())


@admin.callback_query(F.data == "adm")
async def cb_adm(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(cb, ADMIN_HELP, admin_panel())


@admin.message(Command("grant"))
async def cmd_grant(m: Message, command: CommandObject):
    parts = (command.args or "").split()
    if len(parts) != 2 or not all(p.lstrip("-").isdigit() for p in parts):
        return await m.answer("فرمت: <code>/grant 123456789 30</code>")
    until = await grant(int(parts[0]), int(parts[1]))
    await m.answer(f"✅ اشتراک تا {time.strftime('%Y-%m-%d', time.localtime(until))} فعال شد.")


@admin.callback_query(F.data.startswith("ap:"))
async def cb_approve(cb: CallbackQuery):
    _, uid, days = cb.data.split(":")
    uid, days = int(uid), int(days)
    if days > 0:
        until = await grant(uid, days)
        note = f"🎉 اشتراکت فعال شد (تا {time.strftime('%Y-%m-%d', time.localtime(until))})."
        result = f"✅ {days} روز برای {uid} فعال شد."
    else:
        note, result = "❌ پرداخت تأیید نشد. اگه اشتباهی شده، دوباره رسید بفرست.", f"❌ رد شد: {uid}"
    try:
        await cb.bot.send_message(uid, note)
    except TelegramBadRequest:
        pass
    await cb.message.edit_text(result)


# ── افزودن بخش
@admin.callback_query(F.data == "a:sec")
async def cb_add_sec(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddSection.title)
    await show(cb, "اسم بخش رو بفرست (می‌تونی اولش ایموجی بذاری).\nلغو: /cancel")


@admin.message(StateFilter(AddSection.title))
async def msg_add_sec(m: Message, state: FSMContext):
    await q_run("INSERT INTO sections(title,pos) VALUES(?,?)", ((m.text or "").strip()[:60], await next_pos("sections")))
    await state.clear()
    await m.answer("✅ بخش ساخته شد.", reply_markup=admin_panel())


# ── افزودن درس
@admin.callback_query(F.data == "a:les")
async def cb_add_les(cb: CallbackQuery):
    await pick_section(cb, "al", "درس رو توی کدوم بخش بسازم؟")


@admin.callback_query(F.data.startswith("al:"))
async def cb_add_les_sec(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddLesson.title)
    await state.update_data(sid=int(cb.data.split(":")[1]))
    await show(cb, "اسم درس رو بفرست.\nلغو: /cancel")


@admin.message(StateFilter(AddLesson.title))
async def msg_add_les(m: Message, state: FSMContext):
    await state.update_data(title=(m.text or "").strip()[:80])
    await state.set_state(AddLesson.free)
    await m.answer("این درس رایگان باشه یا مخصوص مشترک‌ها؟",
                   reply_markup=markup([[btn("🆓 رایگان", "lf:1"), btn("🔒 اشتراکی", "lf:0")]]))


@admin.callback_query(StateFilter(AddLesson.free), F.data.startswith("lf:"))
async def cb_add_les_free(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    lid = await q_run("INSERT INTO lessons(section_id,title,is_free,pos) VALUES(?,?,?,?)",
                      (d["sid"], d["title"], int(cb.data.split(":")[1]),
                       await next_pos("lessons", "section_id=?", (d["sid"],))))
    await state.clear()
    await show(cb, "✅ درس ساخته شد. قدم‌هاش رو اضافه کنیم؟",
               markup([[btn("📝 افزودن قدم", f"ast:{lid}")], [btn("🔙 پنل", "adm")]]))


# ── افزودن قدم‌ها (هر پیام = یک قدم)
@admin.callback_query(F.data == "a:stp")
async def cb_add_stp(cb: CallbackQuery):
    await pick_section(cb, "ps", "قدم رو برای کدوم بخش اضافه کنم؟")


@admin.callback_query(F.data.startswith("ps:"))
async def cb_pick_lesson(cb: CallbackQuery):
    sid = int(cb.data.split(":")[1])
    lessons = await q_all("SELECT id,title FROM lessons WHERE section_id=? ORDER BY pos,id", (sid,))
    if not lessons:
        return await cb.message.answer("این بخش درسی ندارد")
    rows = [[btn(l["title"], f"ast:{l['id']}")] for l in lessons] + [[btn("🔙 پنل", "adm")]]
    await show(cb, "کدوم درس؟", markup(rows))


@admin.callback_query(F.data.startswith("ast:"))
async def cb_start_steps(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddSteps.collect)
    await state.update_data(lid=int(cb.data.split(":")[1]))
    await show(cb, "📝 قدم‌ها رو یکی‌یکی اضافه کن:\n\n"
                   "۱) اول <b>متن توضیح</b> رو بفرست (یا عکس با کپشن). توضیح معمولیه و کاربر نمی‌تونه کپیش کنه.\n"
                   "۲) بعد <b>لیست دستورها</b> رو بفرست (هر دستور یک خط). برای کاربر یک دکمه‌ی «📋 کپی» می‌شه. "
                   "دستور نداره؟ /skip\n\n"
                   "آی‌پی کاربر: <code>{IP}</code>\n"
                   "وقتی همه‌ی قدم‌ها تموم شد: /done (پیش‌نمایش رو می‌بینی)")


async def save_step(lid: int, pending: dict, cmd: str | None) -> int:
    pos = await next_pos("steps", "lesson_id=?", (lid,))
    await q_run("INSERT INTO steps(lesson_id,text,photo,cmd,pos) VALUES(?,?,?,?,?)",
                (lid, pending["text"], pending["photo"], cmd, pos))
    return pos


@admin.message(Command("done"))
async def cmd_done(m: Message, state: FSMContext):
    data = await state.get_data()
    lid = data.get("lid")
    if await state.get_state() == AddSteps.cmd.state and data.get("pending"):
        await save_step(lid, data["pending"], None)
    await state.clear()
    await m.answer("✅ ذخیره شد. کاربر دقیقاً این رو می‌بینه 👇")
    if lid:
        await send_lesson(m.bot, m.chat.id, m.from_user.id, m.from_user.full_name, lid)
    await m.answer("🛠 پنل مدیریت:", reply_markup=admin_panel())


@admin.message(Command("skip"), StateFilter(AddSteps.cmd))
async def cmd_skip(m: Message, state: FSMContext):
    data = await state.get_data()
    pos = await save_step(data["lid"], data["pending"], None)
    await state.set_state(AddSteps.collect)
    await m.answer(f"✅ قدم {pos} ذخیره شد (بدون دستور). قدم بعدی رو بفرست یا /done")


@admin.message(StateFilter(AddSteps.collect))
async def msg_step(m: Message, state: FSMContext):
    if m.text and m.text.startswith("/"):
        return await m.answer("دستور ناشناخته. برای پایان: /done")
    raw = md_fallback(m.html_text) if (m.text or m.caption) else ""
    photo = m.photo[-1].file_id if m.photo else None
    if not raw and not photo:
        return await m.answer("فقط متن یا عکس بفرست.")
    if len(raw) > 2500:
        return await m.answer(f"❌ این توضیح بلنده ({len(raw)} حرف). به دو قدم بشکن.")
    await state.update_data(pending={"text": raw, "photo": photo})
    await state.set_state(AddSteps.cmd)
    await m.answer("✅ توضیح گرفته شد. حالا <b>لیست دستورها</b> رو بفرست (هر دستور یک خط)، یا /skip")


@admin.message(StateFilter(AddSteps.cmd))
async def msg_cmd(m: Message, state: FSMContext):
    cmd = (m.text or "").strip()
    if not cmd:
        return await m.answer("فقط متن بفرست (لیست دستورها)، یا /skip")
    if len(cmd) > 1500:
        return await m.answer(f"❌ لیست دستورها بلنده ({len(cmd)} حرف). به دو قدم بشکن.")
    data = await state.get_data()
    pos = await save_step(data["lid"], data["pending"], cmd)
    await state.set_state(AddSteps.collect)
    n = len(cmd.splitlines())
    warn = "\n⚠️ بعضی خط‌ها بلندتر از ۲۵۶ حرفن و توی دکمه‌ی کپی جا نمی‌شن (فقط داخل کادر کد کپی می‌شن)." \
        if any(len(ln) > 256 for ln in cmd.splitlines()) else ""
    await m.answer(f"✅ قدم {pos} ذخیره شد ({n} خط دستور).{warn}\nقدم بعدی رو بفرست یا /done")


# ── حذف
@admin.callback_query(F.data == "a:del")
async def cb_del(cb: CallbackQuery):
    await pick_section(cb, "dsx", "کدوم بخش؟")


@admin.callback_query(F.data.startswith("dsx:"))
async def cb_del_sec(cb: CallbackQuery):
    sid = int(cb.data.split(":")[1])
    lessons = await q_all("SELECT id,title FROM lessons WHERE section_id=? ORDER BY pos,id", (sid,))
    rows = [[btn(l["title"], f"dlx:{l['id']}")] for l in lessons]
    rows += [[btn("🗑 حذف کل این بخش", f"cf:sec:{sid}")], [btn("🔙 پنل", "adm")]]
    await show(cb, "روی درس بزن تا گزینه‌های حذف رو ببینی:", markup(rows))


@admin.callback_query(F.data.startswith("dlx:"))
async def cb_del_lesson(cb: CallbackQuery):
    lid = cb.data.split(":")[1]
    await show(cb, "چی کار کنم؟", markup([
        [btn("🧹 پاک‌کردن قدم‌های درس", f"cf:stp:{lid}")],
        [btn("🗑 حذف کل درس", f"cf:les:{lid}")], [btn("🔙 پنل", "adm")]]))


@admin.callback_query(F.data.startswith("cf:"))
async def cb_confirm(cb: CallbackQuery):
    _, kind, oid = cb.data.split(":")
    await show(cb, "⚠️ مطمئنی؟ این کار برگشت نداره.",
               markup([[btn("✅ بله، حذف کن", f"dy:{kind}:{oid}")], [btn("❌ نه", "adm")]]))


@admin.callback_query(F.data.startswith("dy:"))
async def cb_delete(cb: CallbackQuery):
    _, kind, oid = cb.data.split(":")
    sql = {"sec": "DELETE FROM sections WHERE id=?", "les": "DELETE FROM lessons WHERE id=?",
           "stp": "DELETE FROM steps WHERE lesson_id=?"}[kind]
    await q_run(sql, (int(oid),))
    await show(cb, "✅ انجام شد.", admin_panel())


# ── متن پرداخت و آمار
@admin.callback_query(F.data == "a:pay")
async def cb_pay_text(cb: CallbackQuery, state: FSMContext):
    await state.set_state(EditPay.text)
    await show(cb, "متن جدید صفحه‌ی اشتراک رو بفرست (قیمت، آدرس کیف پول، شبکه، توضیح).\nلغو: /cancel")


@admin.message(StateFilter(EditPay.text))
async def msg_pay_text(m: Message, state: FSMContext):
    await set_setting("pay_text", md_fallback(m.html_text) if m.text else DEFAULT_PAY_TEXT)
    await state.clear()
    await m.answer("✅ ذخیره شد.", reply_markup=admin_panel())


@admin.callback_query(F.data == "a:stat")
async def cb_stat(cb: CallbackQuery):
    async def n(sql: str, args: tuple = ()):
        return (await q_one(sql, args))["c"]
    text = (f"📊 کاربران: {await n('SELECT COUNT(*) c FROM users')}\n"
            f"💎 مشترک فعال: {await n('SELECT COUNT(*) c FROM users WHERE sub_until>?', (int(time.time()),))}\n"
            f"📚 بخش: {await n('SELECT COUNT(*) c FROM sections')} | درس: {await n('SELECT COUNT(*) c FROM lessons')} "
            f"| قدم: {await n('SELECT COUNT(*) c FROM steps')}")
    await show(cb, text, admin_panel())


# پیام‌های بی‌ربط
@user.message()
async def fallback(m: Message):
    await m.answer("از منو استفاده کن 👇", reply_markup=await main_menu(m.from_user.id))


# ═════════════════════════ محتوای نمونه (فقط بار اول) ═════════════════════════
SEED = [
    ("📘 آموزش گیت‌هاب", [
        ("ساخت حساب و اولین ریپازیتوری", 1, [
            ("۱) مرورگر رو باز کن و برو به github.com. روی Sign up بزن و ثبت‌نام کن.", None),
            ("۲) بالای صفحه دکمه‌ی + رو بزن و New repository رو انتخاب کن. توی Repository name یک اسم "
             "انگلیسی بنویس (مثلاً اسم زیر) و بعد Create repository رو بزن.", "my-first-bot"),
        ]),
    ]),
    ("🖥 کلون روی سرور", [
        ("اتصال به سرور با SSH", 1, [
            ("ترمینال رو باز کن (ویندوز: PowerShell). این دستور با آی‌پی سرور خودت ساخته شده؛ "
             "دکمه‌ی کپی رو بزن و توی ترمینال بچسبون.", "ssh {USER}@{IP}"),
            ("بار اول می‌پرسه به این سرور اعتماد داری؟ این رو بنویس. بعد رمز سرور رو بزن؛ "
             "موقع تایپ چیزی نشون داده نمی‌شه، طبیعیه.", "yes"),
        ]),
        ("کلون کردن پروژه از گیت‌هاب", 0, [
            ("اول مطمئن شو گیت نصبه.", "apt update && apt install -y git"),
            ("حالا پروژه رو کلون کن و وارد پوشه‌اش شو.", "git clone {REPO_URL}\ncd {REPO_NAME}"),
        ]),
    ]),
    ("🤖 حرف زدن با هوش مصنوعی", [
        ("یک درخواست خوب چه شکلیه؟", 1, [
            ("هوش مصنوعی حدس نمی‌زنه، فقط چیزی رو که بهش می‌گی انجام می‌ده. هر درخواست کد باید این ۵ تا رو "
             "داشته باشه: هدف، زبان و نسخه، محل اجرا، ورودی/خروجی، قالب جواب.", None),
            ("برای ساخت خودکار همین پرامپت، از منوی اصلی «🪄 پرامپت‌ساز» رو بزن.", None),
        ]),
    ]),
]


async def seed_if_empty() -> None:
    if await q_one("SELECT id FROM sections LIMIT 1"):
        return
    for si, (stitle, lessons) in enumerate(SEED, 1):
        sid = await q_run("INSERT INTO sections(title,pos) VALUES(?,?)", (stitle, si))
        for li, (ltitle, free, steps) in enumerate(lessons, 1):
            lid = await q_run("INSERT INTO lessons(section_id,title,is_free,pos) VALUES(?,?,?,?)",
                              (sid, ltitle, free, li))
            for pi, (text, cmd) in enumerate(steps, 1):
                await q_run("INSERT INTO steps(lesson_id,text,cmd,pos) VALUES(?,?,?,?)", (lid, text, cmd, pi))


async def main(extra_routers=(), on_startup=None, on_shutdown=None) -> None:
    global DB
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN تنظیم نشده است.")
    if not ADMIN_IDS:
        logging.warning("ADMIN_IDS خالی است؛ پنل مدیریت کار نمی‌کند.")
    DB = await aiosqlite.connect(DB_PATH)
    DB.row_factory = aiosqlite.Row
    await DB.execute("PRAGMA foreign_keys=ON")
    await DB.execute("PRAGMA journal_mode=WAL")
    await DB.execute("PRAGMA synchronous=NORMAL")
    await DB.executescript(SCHEMA)
    cols = [r["name"] for r in await q_all("PRAGMA table_info(steps)")]
    if "cmd" not in cols:  # مهاجرت دیتابیس قدیمی
        await DB.execute("ALTER TABLE steps ADD COLUMN cmd TEXT")
    await DB.commit()
    await seed_if_empty()

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp = Dispatcher(storage=MemoryStorage())
    dp.callback_query.outer_middleware(AutoAnswer())
    dp.include_routers(common, admin, *extra_routers, user)
    if on_startup:
        await on_startup(bot)
    try:
        await dp.start_polling(bot)
    finally:
        if on_shutdown:
            await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
