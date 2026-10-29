#!/usr/bin/env python3
"""
ربات آموزشی + ربات‌ساز + اپلیکیشن‌ساز — همه‌چیز در یک فایل

راه‌اندازی:
  1) pip install -r requirements.txt
  2) python bot.py      (بار اول فایل .env می‌سازه؛ BOT_TOKEN و ADMIN_IDS رو توش پر کن)
  3) دوباره: python bot.py

نکته: توکن رو هرگز داخل کد ننویس؛ فقط داخل فایل .env (که خودکار داخل .gitignore می‌ره).
"""
from __future__ import annotations

import asyncio
import html
import io
import ipaddress
import logging
import os
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path

import aiosqlite
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message)
from cryptography.fernet import Fernet, InvalidToken

# ───────────────────────── تنظیمات (.env) ─────────────────────────
ENV_FILE = Path(".env")


def load_env() -> None:
    """مقدارها را از فایل .env می‌خواند (فرمت: KEY=VALUE). متغیرهای محیطی اولویت دارند."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def protect_secrets() -> None:
    """جلوگیری از آپلود تصادفی توکن و دیتابیس روی گیت‌هاب."""
    want = [".env", "bot.db*", "data/", "__pycache__/"]
    gi = Path(".gitignore")
    have = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    missing = [w for w in want if w not in have]
    if missing:
        with gi.open("a", encoding="utf-8") as f:
            f.write(("\n" if have else "") + "\n".join(missing) + "\n")


def ensure_config() -> None:
    load_env()
    protect_secrets()
    if not ENV_FILE.exists():
        ENV_FILE.write_text("# توکن ربات از @BotFather\nBOT_TOKEN=\n# آیدی عددی ادمین (از @userinfobot)؛ "
                            "چند تا با کاما\nADMIN_IDS=\n", encoding="utf-8")
    if not os.getenv("BOT_TOKEN") or not os.getenv("ADMIN_IDS"):
        raise SystemExit("\n❗ فایل .env رو باز کن و BOT_TOKEN و ADMIN_IDS رو پر کن (بدون فاصله و گیومه)،\n"
                         "   بعد دوباره اجرا کن:  python bot.py\n")
    if not os.getenv("TOKEN_KEY"):  # کلید رمزنگاری توکن ربات‌های کاربران؛ خودکار ساخته می‌شه
        key = Fernet.generate_key().decode()
        with ENV_FILE.open("a", encoding="utf-8") as f:
            f.write(f"\n# کلید رمزنگاری توکن‌ها. گم نشه! یک نسخه پشتیبان بگیر\nTOKEN_KEY={key}\n")
        os.environ["TOKEN_KEY"] = key
        print("🔑 TOKEN_KEY ساخته و داخل .env ذخیره شد. یک نسخه پشتیبان ازش بگیر.")


ensure_config()
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {int(x) for x in re.split(r"[,\s]+", os.environ["ADMIN_IDS"]) if x.strip().isdigit()}
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


# ═════════════════════ ربات‌ساز و اپلیکیشن‌ساز: تنظیمات ═════════════════════
DATA_ROOT = Path(os.getenv("DATA_ROOT", "data"))
TPL_DIR = DATA_ROOT / "templates"
BOTS_DIR = DATA_ROOT / "bots"
PRICE_BOT = int(os.getenv("PRICE_BOT", "1000000"))  # تومان، ماهانه
PRICE_APP = int(os.getenv("PRICE_APP", "1500000"))  # تومان، یک‌بار
SUB_DAYS = 30
MAX_BOTS_PER_USER = 5
MEM_MB = int(os.getenv("BOT_MEM_MB", "1024"))  # سقف حافظه‌ی هر ربات کاربر (فقط لینوکس)
TOKEN_RE = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,50}")
URL_RE = re.compile(r"https?://[^\s]{4,200}")

FERNET: Fernet | None = None
PROCS: dict[int, asyncio.subprocess.Process] = {}
STARTS: dict[int, list[float]] = {}  # زمان استارت‌ها برای تشخیص crash-loop
_TASK: asyncio.Task | None = None

SCHEMA2 = """
CREATE TABLE IF NOT EXISTS templates(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, descr TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS ubots(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, template_id INTEGER NOT NULL,
  tg_id INTEGER NOT NULL UNIQUE, username TEXT NOT NULL DEFAULT '', token_enc TEXT NOT NULL,
  owner_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'awaiting_payment',
  expires_at INTEGER NOT NULL DEFAULT 0, last_remind TEXT, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS app_orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, user_label TEXT NOT NULL DEFAULT '',
  site_url TEXT NOT NULL, app_name TEXT NOT NULL, icon_file TEXT NOT NULL, icon_kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'awaiting_payment', paid INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, label TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL, ref_id INTEGER NOT NULL, amount INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', created INTEGER NOT NULL);
"""

STATUS = {"awaiting_payment": "⏳ منتظر پرداخت", "active": "🟢 فعال", "expired": "🔴 منقضی",
          "suspended": "⛔ تعلیق", "error": "⚠️ خطا"}
ORDER_STATUS = {"awaiting_payment": "⏳ منتظر پرداخت", "in_progress": "🛠 در حال ساخت", "delivered": "✅ تحویل شد"}


# ───────────────────────── ابزارها ─────────────────────────
def money(n: int) -> str:
    return f"{n:,}"


def days_left(expires_at: int) -> int:
    return max(0, -(-(expires_at - int(time.time())) // 86400))


def label_of(u) -> str:
    un = f" @{u.username}" if u.username else ""
    return f"{html.escape(u.full_name)}{un} [{u.id}]"


def fmt_date(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


async def run_rc(sql: str, args: tuple = ()) -> int:
    """اجرا و برگرداندن تعداد ردیف‌های تغییرکرده (برای جلوگیری از تأیید دوباره‌ی یک فیش)."""
    cur = await DB.execute(sql, args)
    await DB.commit()
    return cur.rowcount


async def notify(bot: Bot, uid: int, text: str) -> None:
    try:
        await bot.send_message(uid, text)
    except (TelegramForbiddenError, TelegramBadRequest):
        logging.warning("پیام به %s ارسال نشد", uid)


async def pay_text(amount: int, title: str, after: str) -> str:
    info = await get_setting("pay_info", "⚠️ ادمین هنوز اطلاعات واریز رو تنظیم نکرده.")
    return (f"{title}\n\nمبلغ: <b>{money(amount)} تومان</b>\n\n{info}\n\n"
            f"بعد از واریز، <b>فیش (عکس یا هش تراکنش) رو همین‌جا بفرست</b>. {after}")


class NewBot(StatesGroup):
    token = State()
    owner = State()


class AppOrder(StatesGroup):
    url = State()
    icon = State()
    name = State()
    confirm = State()


class Receipt(StatesGroup):
    wait = State()


class TplUpload(StatesGroup):
    title = State()
    descr = State()
    file = State()


class Deliver(StatesGroup):
    file = State()


class PayInfo(StatesGroup):
    text = State()


ur, ar = Router(), Router()
ar.message.filter(F.from_user.id.in_(ADMIN_IDS))
ar.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


# ═════════════════════ مدیریت پروسه‌ی ربات‌های کاربران ═════════════════════
def _limit() -> None:  # داخل پروسه‌ی فرزند اجرا می‌شود
    try:
        import resource
        lim = MEM_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
    except Exception:  # noqa: BLE001
        pass


async def start_process(bid: int) -> bool:
    p = PROCS.get(bid)
    if p and p.returncode is None:
        return True
    b = await q_one("SELECT * FROM ubots WHERE id=?", (bid,))
    tpl = TPL_DIR / f"{b['template_id']}.py" if b else None
    if not b or not tpl or not tpl.exists():
        logging.error("ربات %s: قالب پیدا نشد", bid)
        return False
    try:
        token = FERNET.decrypt(b["token_enc"].encode()).decode()
    except InvalidToken:
        logging.error("ربات %s: توکن رمزگشایی نشد (TOKEN_KEY عوض شده؟)", bid)
        return False
    d = (BOTS_DIR / str(bid)).resolve()
    d.mkdir(parents=True, exist_ok=True)
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TEMP", "TMP") if k in os.environ}
    env.update(BOT_TOKEN=token, OWNER_ID=str(b["owner_id"]), DATA_DIR=str(d), PYTHONUNBUFFERED="1")
    kwargs = {"preexec_fn": _limit, "start_new_session": True} if os.name == "posix" else {}
    log = open(d / "bot.log", "ab")
    try:
        PROCS[bid] = await asyncio.create_subprocess_exec(
            sys.executable, str(tpl.resolve()), cwd=str(d), env=env,
            stdout=log, stderr=asyncio.subprocess.STDOUT, **kwargs)
    finally:
        log.close()
    STARTS.setdefault(bid, []).append(time.time())
    logging.info("ربات %s (@%s) اجرا شد", bid, b["username"])
    return True


async def stop_process(bid: int) -> None:
    p = PROCS.pop(bid, None)
    if p and p.returncode is None:
        p.terminate()
        try:
            await asyncio.wait_for(p.wait(), 5)
        except asyncio.TimeoutError:
            p.kill()
            await p.wait()


async def activate_bot(bot: Bot, bid: int, days: int) -> None:
    b = await q_one("SELECT * FROM ubots WHERE id=?", (bid,))
    if not b:
        return
    exp = max(b["expires_at"], int(time.time())) + days * 86400
    status = "suspended" if b["status"] == "suspended" else "active"
    await q_run("UPDATE ubots SET expires_at=?, status=?, last_remind=NULL WHERE id=?", (exp, status, bid))
    if status == "active":
        await start_process(bid)
    await notify(bot, b["user_id"], f"✅ اشتراک ربات @{b['username']} تأیید شد.\n"
                                    f"فعال تا: {fmt_date(exp)} ({days_left(exp)} روز)")


async def tick(bot: Bot) -> None:
    now, today = int(time.time()), date.today().isoformat()
    for b in await q_all("SELECT * FROM ubots WHERE status='active'"):
        bid = b["id"]
        if b["expires_at"] <= now:
            await stop_process(bid)
            await q_run("UPDATE ubots SET status='expired' WHERE id=?", (bid,))
            await notify(bot, b["user_id"], f"🔴 اشتراک ربات @{b['username']} تموم شد و ربات از کار افتاد.\n"
                                            "از «🤖 ساخت ربات» اشتراکت رو تمدید کن.")
            continue
        p = PROCS.get(bid)
        if p is None or p.returncode is not None:
            recent = [t for t in STARTS.get(bid, []) if now - t < 600]
            STARTS[bid] = recent
            if len(recent) >= 5:  # حلقه‌ی کرش
                await stop_process(bid)
                await q_run("UPDATE ubots SET status='error' WHERE id=?", (bid,))
                for aid in ADMIN_IDS:
                    await notify(bot, aid, f"⚠️ ربات @{b['username']} (#{bid}) مدام کرش می‌کنه و متوقف شد.")
                continue
            await start_process(bid)
        left = days_left(b["expires_at"])
        if left <= 3 and b["last_remind"] != today:
            await q_run("UPDATE ubots SET last_remind=? WHERE id=?", (today, bid))
            await notify(bot, b["user_id"],
                         f"⏰ {left} روز تا پایان اشتراک ربات @{b['username']} مونده.\n"
                         "اشتراک خودت رو فعال کن (🤖 ساخت ربات ← ربات‌های من ← تمدید)، "
                         "در غیر این صورت ربات از کار می‌افته.")


async def supervisor(bot: Bot) -> None:
    while True:
        try:
            await tick(bot)
        except Exception:  # noqa: BLE001
            logging.exception("supervisor")
        await asyncio.sleep(30)


# ═════════════════════ پرداخت و فیش (مشترک) ═════════════════════
async def ask_receipt(bot: Bot, chat_id: int, state: FSMContext, kind: str, ref: int, text: str) -> None:
    await state.set_state(Receipt.wait)
    await state.update_data(kind=kind, ref=ref)
    await bot.send_message(chat_id, text, reply_markup=markup(
        [[btn("🔙 بعداً", "bx:bots" if kind == "bot" else "home")]]))


async def payment_desc(kind: str, ref: int) -> str:
    if kind == "bot":
        b = await q_one("SELECT u.username, t.title FROM ubots u LEFT JOIN templates t ON t.id=u.template_id "
                        "WHERE u.id=?", (ref,))
        return f"🤖 اشتراک ماهانه ربات @{b['username']} (قالب: {html.escape(b['title'] or '-')})"
    o = await q_one("SELECT app_name, site_url FROM app_orders WHERE id=?", (ref,))
    return f"📱 سفارش اپ «{html.escape(o['app_name'])}» — {html.escape(o['site_url'])}"


@ur.message(StateFilter(Receipt.wait))
async def msg_receipt(m: Message, state: FSMContext):
    if m.text and m.text.startswith("/"):
        return await m.answer("فیش رو بفرست (عکس یا هش تراکنش). برای لغو: /cancel")
    if not (m.photo or m.document or m.text):
        return await m.answer("عکس فیش یا هش تراکنش رو بفرست.")
    d = await state.get_data()
    kind, ref = d["kind"], d["ref"]
    await state.clear()
    amount = PRICE_BOT if kind == "bot" else PRICE_APP
    pend = await q_one("SELECT id FROM payments WHERE kind=? AND ref_id=? AND status='pending'", (kind, ref))
    pid = pend["id"] if pend else await q_run(
        "INSERT INTO payments(user_id,label,kind,ref_id,amount,created) VALUES(?,?,?,?,?,?)",
        (m.from_user.id, label_of(m.from_user), kind, ref, amount, int(time.time())))
    desc = await payment_desc(kind, ref)
    kb = markup([[btn("✅ تأیید", f"bxa:p:{pid}:1"), btn("❌ رد", f"bxa:p:{pid}:0")]])
    for aid in ADMIN_IDS:
        try:
            await m.forward(aid)
            await m.bot.send_message(aid, f"💳 فیش #{pid}\nکاربر: {label_of(m.from_user)}\n{desc}\n"
                                          f"مبلغ: {money(amount)} تومان", reply_markup=kb)
        except (TelegramForbiddenError, TelegramBadRequest):
            logging.warning("ارسال فیش به ادمین %s ناموفق بود", aid)
    after = "بعد از تأیید، ربات خودکار فعال می‌شه." if kind == "bot" else \
        "بعد از تأیید، ساخت اپ شروع می‌شه و فایلش برات ارسال می‌شه."
    await m.answer(f"✅ فیش دریافت شد و برای بررسی رفت. {after}")


@ar.callback_query(F.data.startswith("bxa:p:"))
async def cb_pay_decision(cb: CallbackQuery):
    _, _, pid, ok = cb.data.split(":")
    new = "approved" if ok == "1" else "rejected"
    if await run_rc("UPDATE payments SET status=? WHERE id=? AND status='pending'", (new, int(pid))) == 0:
        return await cb.message.edit_text("این فیش قبلاً بررسی شده.")
    p = await q_one("SELECT * FROM payments WHERE id=?", (int(pid),))
    if new == "rejected":
        await notify(cb.bot, p["user_id"], "❌ فیش تأیید نشد. اگه اشتباهی شده، دوباره فیش درست رو بفرست.")
        return await cb.message.edit_text(f"❌ فیش #{pid} رد شد.")
    if p["kind"] == "bot":
        await activate_bot(cb.bot, p["ref_id"], SUB_DAYS)
    else:
        await q_run("UPDATE app_orders SET paid=1, status='in_progress' WHERE id=? AND status='awaiting_payment'",
                    (p["ref_id"],))
        await notify(cb.bot, p["user_id"], "✅ پرداخت تأیید شد. ساخت اپلیکیشن شروع شد و تا ۲۴ ساعت آینده "
                                           "فایلش همین‌جا برات ارسال می‌شه.")
    await cb.message.edit_text(f"✅ فیش #{pid} تأیید شد.")


# ═════════════════════ کاربر: ربات‌های من ═════════════════════
@ur.callback_query(F.data == "bx:bots")
async def cb_bots(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    bots = await q_all("SELECT * FROM ubots WHERE user_id=? ORDER BY id", (cb.from_user.id,))
    rows = [[btn(f"{STATUS[b['status']].split()[0]} @{b['username']}", f"bx:b:{b['id']}")] for b in bots]
    rows += [[btn("➕ ربات جدید", "bx:new")], [btn("🔙 منو", "home")]]
    body = "یکی رو انتخاب کن 👇" if bots else "هنوز رباتی نساختی. «➕ ربات جدید» رو بزن."
    await show(cb, f"🤖 <b>ربات‌های من</b>\n\n{body}", markup(rows))


async def owned_bot(cb: CallbackQuery, bid: int):
    b = await q_one("SELECT u.*, t.title AS tpl FROM ubots u LEFT JOIN templates t ON t.id=u.template_id "
                    "WHERE u.id=?", (bid,))
    return b if b and b["user_id"] == cb.from_user.id else None


@ur.callback_query(F.data.startswith("bx:b:"))
async def cb_bot_detail(cb: CallbackQuery):
    b = await owned_bot(cb, int(cb.data.split(":")[2]))
    if not b:
        return
    line = STATUS[b["status"]]
    if b["status"] == "active":
        line += f" — {days_left(b['expires_at'])} روز مونده (تا {fmt_date(b['expires_at'])})"
    text = f"🤖 <b>@{b['username']}</b>\nقالب: {html.escape(b['tpl'] or '-')}\nوضعیت: {line}"
    if b["status"] != "active":
        text += "\n\n⛔ شما اشتراک فعال ندارید."
    await show(cb, text, markup([
        [btn("💳 فعال‌سازی / تمدید اشتراک", f"bx:pay:{b['id']}")],
        [btn("🗑 حذف ربات", f"bx:del:{b['id']}")], [btn("🔙 ربات‌های من", "bx:bots")]]))


@ur.callback_query(F.data.startswith("bx:pay:"))
async def cb_bot_pay(cb: CallbackQuery, state: FSMContext):
    b = await owned_bot(cb, int(cb.data.split(":")[2]))
    if not b:
        return
    head = "⛔ <b>شما اشتراک فعال ندارید.</b>" if b["status"] != "active" else "🔄 <b>تمدید اشتراک</b>"
    text = await pay_text(PRICE_BOT, f"{head}\nربات @{b['username']} — اشتراک ماهانه",
                          "بعد از تأیید، ربات شما خودکار فعال می‌شود.")
    await ask_receipt(cb.bot, cb.message.chat.id, state, "bot", b["id"], text)


@ur.callback_query(F.data.startswith("bx:del:"))
async def cb_bot_del(cb: CallbackQuery):
    b = await owned_bot(cb, int(cb.data.split(":")[2]))
    if b:
        await show(cb, f"⚠️ ربات @{b['username']} حذف بشه؟ برگشت نداره و اشتراک باقی‌مونده هم از بین می‌ره.",
                   markup([[btn("✅ بله، حذف کن", f"bx:dely:{b['id']}")], [btn("❌ نه", f"bx:b:{b['id']}")]]))


@ur.callback_query(F.data.startswith("bx:dely:"))
async def cb_bot_del_yes(cb: CallbackQuery):
    b = await owned_bot(cb, int(cb.data.split(":")[2]))
    if not b:
        return
    await stop_process(b["id"])
    await q_run("DELETE FROM ubots WHERE id=?", (b["id"],))
    shutil.rmtree(BOTS_DIR / str(b["id"]), ignore_errors=True)
    await show(cb, "🗑 ربات حذف شد. برای امنیت، توکنش رو توی @BotFather با /revoke عوض کن.",
               markup([[btn("🔙 ربات‌های من", "bx:bots")]]))


# ═════════════════════ کاربر: ساخت ربات جدید ═════════════════════
@ur.callback_query(F.data == "bx:new")
async def cb_new(cb: CallbackQuery):
    cnt = (await q_one("SELECT COUNT(*) c FROM ubots WHERE user_id=?", (cb.from_user.id,)))["c"]
    if cnt >= MAX_BOTS_PER_USER:
        return await show(cb, f"حداکثر {MAX_BOTS_PER_USER} ربات می‌تونی داشته باشی.",
                          markup([[btn("🔙 ربات‌های من", "bx:bots")]]))
    tpls = await q_all("SELECT * FROM templates WHERE active=1 ORDER BY id")
    if not tpls:
        return await show(cb, "فعلاً قالبی برای ساخت ربات موجود نیست.", markup([[btn("🔙 بازگشت", "bx:bots")]]))
    text = "🧩 <b>یک قالب انتخاب کن:</b>\n\n" + "\n".join(
        f"• <b>{html.escape(t['title'])}</b> — {html.escape(t['descr'])}" for t in tpls)
    rows = [[btn(t["title"], f"bx:t:{t['id']}")] for t in tpls] + [[btn("🔙 بازگشت", "bx:bots")]]
    await show(cb, text, markup(rows))


@ur.callback_query(F.data.startswith("bx:t:"))
async def cb_tpl(cb: CallbackQuery, state: FSMContext):
    await state.set_state(NewBot.token)
    await state.update_data(tid=int(cb.data.split(":")[2]))
    await show(cb, "۱) توی @BotFather یک ربات بساز (/newbot) و <b>توکنش</b> رو همین‌جا بفرست.\n\n"
                   "🔐 توکن رو فقط به همین ربات بده؛ بعد از دریافت، پیامت رو پاک می‌کنم و توکن رمزشده ذخیره می‌شه.\n"
                   "لغو: /cancel")


@ur.message(StateFilter(NewBot.token))
async def msg_token(m: Message, state: FSMContext):
    token = (m.text or "").strip()
    try:
        await m.delete()
    except TelegramBadRequest:
        pass
    if not TOKEN_RE.fullmatch(token):
        return await m.answer("❌ این شبیه توکن نیست. از @BotFather کپی کن و دوباره بفرست.\nلغو: /cancel")
    try:
        tmp = Bot(token)
        try:
            me = await tmp.get_me()
        finally:
            await tmp.session.close()
    except Exception:  # noqa: BLE001
        return await m.answer("❌ این توکن معتبر نیست یا باطل شده.")
    if await q_one("SELECT id FROM ubots WHERE tg_id=?", (me.id,)):
        return await m.answer("❌ این ربات قبلاً ثبت شده.")
    await state.update_data(token=token, tg_id=me.id, username=me.username or "")
    await state.set_state(NewBot.owner)
    await m.answer(f"✅ ربات @{me.username} تأیید شد.\n\n"
                   "۲) <b>آیدی عددی</b> ادمین این ربات رو بفرست (کسی که پیام‌ها و مدیریت ربات به اون می‌رسه).\n"
                   "اگه خودتی، دکمه‌ی زیر رو بزن.",
                   reply_markup=markup([[btn("👤 همین حساب خودم", "bx:me")]]))


async def finish_new_bot(bot: Bot, chat_id: int, user_id: int, owner_id: int, state: FSMContext) -> None:
    d = await state.get_data()
    await state.clear()
    bid = await q_run(
        "INSERT INTO ubots(user_id,template_id,tg_id,username,token_enc,owner_id,created) VALUES(?,?,?,?,?,?,?)",
        (user_id, d["tid"], d["tg_id"], d["username"], FERNET.encrypt(d["token"].encode()).decode(),
         owner_id, int(time.time())))
    text = await pay_text(PRICE_BOT, f"⛔ <b>شما اشتراک فعال ندارید.</b>\nربات @{d['username']} — اشتراک ماهانه",
                          "بعد از تأیید، ربات شما خودکار فعال می‌شود.")
    await ask_receipt(bot, chat_id, state, "bot", bid, text)


@ur.message(StateFilter(NewBot.owner))
async def msg_owner(m: Message, state: FSMContext):
    t = (m.text or "").strip()
    if not (t.isdigit() and 5 <= len(t) <= 15):
        return await m.answer("❌ آیدی عددی بفرست (فقط عدد). یا دکمه‌ی «همین حساب خودم». لغو: /cancel")
    await finish_new_bot(m.bot, m.chat.id, m.from_user.id, int(t), state)


@ur.callback_query(StateFilter(NewBot.owner), F.data == "bx:me")
async def cb_owner_me(cb: CallbackQuery, state: FSMContext):
    await finish_new_bot(cb.bot, cb.message.chat.id, cb.from_user.id, cb.from_user.id, state)


# ═════════════════════ کاربر: ساخت اپلیکیشن ═════════════════════
@ur.callback_query(F.data == "bx:app")
async def cb_app(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AppOrder.url)
    await show(cb, f"📱 <b>تبدیل سایت به اپلیکیشن اندروید</b>\nقیمت: {money(PRICE_APP)} تومان\n\n"
                   "۱) لینک سایتی که می‌خوای به اپلیکیشن تبدیل بشه رو بفرست (با https://)\n"
                   "لغو: /cancel", markup([[btn("📋 سفارش‌های من", "bx:orders"), btn("🔙 منو", "home")]]))


@ur.message(StateFilter(AppOrder.url))
async def msg_app_url(m: Message, state: FSMContext):
    t = (m.text or "").strip()
    if not URL_RE.fullmatch(t):
        return await m.answer("❌ لینک معتبر نیست. مثال: https://example.com\nلغو: /cancel")
    await state.update_data(url=t)
    await state.set_state(AppOrder.icon)
    await m.answer("۲) <b>آیکون</b> اپلیکیشن رو بفرست.\n"
                   "📎 برای کیفیت بهتر به‌صورت «فایل (File)» بفرست؛ ترجیحاً PNG مربع ۵۱۲×۵۱۲.")


@ur.message(StateFilter(AppOrder.icon))
async def msg_app_icon(m: Message, state: FSMContext):
    if m.photo:
        fid, kind = m.photo[-1].file_id, "photo"
    elif m.document and (m.document.mime_type or "").startswith("image/") and (m.document.file_size or 0) <= 5_000_000:
        fid, kind = m.document.file_id, "doc"
    else:
        return await m.answer("❌ یک تصویر بفرست (حداکثر ۵ مگابایت).")
    await state.update_data(icon=fid, kind=kind)
    await state.set_state(AppOrder.name)
    await m.answer("۳) <b>اسم اپلیکیشن</b> رو بفرست (حداکثر ۳۰ حرف).")


@ur.message(StateFilter(AppOrder.name))
async def msg_app_name(m: Message, state: FSMContext):
    name = (m.text or "").strip()
    if not (2 <= len(name) <= 30) or "\n" in name:
        return await m.answer("❌ اسم باید بین ۲ تا ۳۰ حرف و تک‌خطی باشه.")
    await state.update_data(name=name)
    await state.set_state(AppOrder.confirm)
    d = await state.get_data()
    cap = (f"🔎 <b>مشخصات اپلیکیشن</b>\n\nنام: <b>{html.escape(name)}</b>\nلینک: {html.escape(d['url'])}\n\n"
           "⚠️ مطمئنی آیکون و نام اپلیکیشن درسته؟\n"
           "<b>اگر تأیید کنی، امکان ویرایش بعداً وجود نداره.</b> در انتخاب اسم و آیکون دقت کن.")
    kb = markup([[btn("✅ تأیید می‌کنم", "bx:ok")], [btn("🔄 از اول", "bx:app"), btn("❌ لغو", "home")]])
    if d["kind"] == "doc":
        await m.answer_document(d["icon"], caption=cap, reply_markup=kb)
    else:
        await m.answer_photo(d["icon"], caption=cap, reply_markup=kb)


async def send_order_card(bot: Bot, chat_id: int, o) -> None:
    cap = (f"📱 <b>سفارش اپ #{o['id']}</b>\nکاربر: {o['user_label']}\n"
           f"نام اپ: {html.escape(o['app_name'])}\nلینک: {html.escape(o['site_url'])}\n"
           f"پرداخت: {'✅ تأیید شده' if o['paid'] else '⏳ هنوز تأیید نشده'}\n"
           f"وضعیت: {ORDER_STATUS[o['status']]}")
    kb = markup([[btn("📤 ارسال APK به کاربر", f"bxa:deliver:{o['id']}")]])
    if o["icon_kind"] == "doc":
        await bot.send_document(chat_id, o["icon_file"], caption=cap, reply_markup=kb)
    else:
        await bot.send_photo(chat_id, o["icon_file"], caption=cap, reply_markup=kb)


@ur.callback_query(StateFilter(AppOrder.confirm), F.data == "bx:ok")
async def cb_app_ok(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    oid = await q_run(
        "INSERT INTO app_orders(user_id,user_label,site_url,app_name,icon_file,icon_kind,created) "
        "VALUES(?,?,?,?,?,?,?)",
        (cb.from_user.id, label_of(cb.from_user), d["url"], d["name"], d["icon"], d["kind"], int(time.time())))
    o = await q_one("SELECT * FROM app_orders WHERE id=?", (oid,))
    for aid in ADMIN_IDS:
        try:
            await send_order_card(cb.bot, aid, o)
        except (TelegramForbiddenError, TelegramBadRequest):
            logging.warning("ارسال سفارش به ادمین %s ناموفق بود", aid)
    text = await pay_text(PRICE_APP, f"✅ <b>سفارش #{oid} ثبت شد.</b>\n⏱ فرایند ساخت اپلیکیشن ۲۴ ساعت طول می‌کشه.\n\n"
                                     "💳 برای شروع، هزینه رو واریز و اشتراک رو فعال کن:",
                          "بعد از تأیید، فایل اپلیکیشن به‌صورت خودکار برات ارسال می‌شه.")
    await ask_receipt(cb.bot, cb.message.chat.id, state, "app", oid, text)


@ur.callback_query(F.data == "bx:orders")
async def cb_my_orders(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    os_ = await q_all("SELECT * FROM app_orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (cb.from_user.id,))
    rows = [[btn(f"#{o['id']} {o['app_name']} — {ORDER_STATUS[o['status']]}", f"bx:ao:{o['id']}")] for o in os_]
    rows.append([btn("🔙 منو", "home")])
    await show(cb, "📋 <b>سفارش‌های اپلیکیشن من</b>" + ("" if os_ else "\n\nسفارشی نداری."), markup(rows))


@ur.callback_query(F.data.startswith("bx:ao:"))
async def cb_my_order(cb: CallbackQuery, state: FSMContext):
    o = await q_one("SELECT * FROM app_orders WHERE id=?", (int(cb.data.split(":")[2]),))
    if not o or o["user_id"] != cb.from_user.id:
        return
    if o["status"] == "awaiting_payment":
        text = await pay_text(PRICE_APP, f"⏳ <b>سفارش #{o['id']} منتظر پرداخته.</b>",
                              "بعد از تأیید، فایل اپلیکیشن برات ارسال می‌شه.")
        return await ask_receipt(cb.bot, cb.message.chat.id, state, "app", o["id"], text)
    await show(cb, f"سفارش #{o['id']} «{html.escape(o['app_name'])}»\nوضعیت: {ORDER_STATUS[o['status']]}",
               markup([[btn("🔙 سفارش‌ها", "bx:orders")]]))


# ═════════════════════ ادمین: قالب‌ها (آپلود فایل پایتون) ═════════════════════
@ar.callback_query(F.data == "bxa:tpl")
async def cb_tpl_list(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    tpls = await q_all("SELECT * FROM templates ORDER BY id")
    rows = [[btn(("🟢 " if t["active"] else "⚪️ ") + t["title"], f"bxa:t:{t['id']}")] for t in tpls]
    rows += [[btn("➕ آپلود فایل پایتون", "bxa:tnew")], [btn("🔙 پنل", "adm")]]
    await show(cb, "🧩 <b>قالب‌های ربات</b>\n\nهر قالب یک فایل .py است که BOT_TOKEN و OWNER_ID را از env می‌خواند.",
               markup(rows))


@ar.callback_query(F.data == "bxa:tnew")
async def cb_tpl_new(cb: CallbackQuery, state: FSMContext):
    await state.set_state(TplUpload.title)
    await state.update_data(replace=None)
    await show(cb, "اسم قالب رو بفرست (کاربر می‌بینه). مثال: «ربات پشتیبانی»\nلغو: /cancel")


@ar.message(StateFilter(TplUpload.title))
async def msg_tpl_title(m: Message, state: FSMContext):
    await state.update_data(title=(m.text or "").strip()[:40])
    await state.set_state(TplUpload.descr)
    await m.answer("یک توضیح کوتاه برای کاربر بنویس (مثلاً: «پیام مشتری‌ها به تو می‌رسه و جواب می‌دی»).")


@ar.message(StateFilter(TplUpload.descr))
async def msg_tpl_descr(m: Message, state: FSMContext):
    await state.update_data(descr=(m.text or "").strip()[:120])
    await state.set_state(TplUpload.file)
    await m.answer("حالا <b>فایل .py</b> رو بفرست.\nفایل باید توکن رو از <code>BOT_TOKEN</code> و آیدی مالک رو از "
                   "<code>OWNER_ID</code> بخونه (نمونه: support_bot.py).")


@ar.message(StateFilter(TplUpload.file), F.document)
async def msg_tpl_file(m: Message, state: FSMContext):
    doc = m.document
    if not (doc.file_name or "").lower().endswith(".py"):
        return await m.answer("❌ فقط فایل .py قبول می‌شه.")
    if (doc.file_size or 0) > 300_000:
        return await m.answer("❌ فایل بزرگ‌تر از ۳۰۰ کیلوبایته.")
    buf = io.BytesIO()
    await m.bot.download(doc, destination=buf)
    try:
        src = buf.getvalue().decode("utf-8")
        compile(src, doc.file_name, "exec")  # فقط بررسی سینتکس؛ اجرا نمی‌شود
    except UnicodeDecodeError:
        return await m.answer("❌ فایل باید UTF-8 باشه.")
    except SyntaxError as e:
        return await m.answer(f"❌ خطای سینتکس، خط {e.lineno}: {html.escape(str(e.msg))}")
    d = await state.get_data()
    await state.clear()
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    if d.get("replace"):
        tid = d["replace"]
        (TPL_DIR / f"{tid}.py").write_text(src, encoding="utf-8")
        for b in await q_all("SELECT id FROM ubots WHERE template_id=?", (tid,)):
            await stop_process(b["id"])  # supervisor با کد جدید دوباره بالا می‌آورد
        msg = f"✅ فایل قالب #{tid} جایگزین شد و ربات‌های مربوط با کد جدید ری‌استارت می‌شن."
    else:
        tid = await q_run("INSERT INTO templates(title,descr) VALUES(?,?)", (d["title"], d["descr"]))
        (TPL_DIR / f"{tid}.py").write_text(src, encoding="utf-8")
        msg = f"✅ قالب «{html.escape(d['title'])}» ذخیره شد و برای کاربرها فعاله."
    if "BOT_TOKEN" not in src:
        msg += "\n⚠️ توی فایل <code>BOT_TOKEN</code> دیده نشد؛ مطمئن شو توکن رو از env می‌خونه."
    await m.answer(msg, reply_markup=markup([[btn("🧩 قالب‌ها", "bxa:tpl")]]))


@ar.message(StateFilter(TplUpload.file))
async def msg_tpl_nofile(m: Message):
    await m.answer("فایل .py رو به‌صورت سند (Document) بفرست. لغو: /cancel")


async def render_tpl(cb: CallbackQuery, tid: int) -> None:
    t = await q_one("SELECT * FROM templates WHERE id=?", (tid,))
    if not t:
        return
    n = (await q_one("SELECT COUNT(*) c FROM ubots WHERE template_id=?", (tid,)))["c"]
    await show(cb, f"🧩 <b>{html.escape(t['title'])}</b>\n{html.escape(t['descr'])}\n\n"
                   f"وضعیت: {'🟢 فعال' if t['active'] else '⚪️ غیرفعال'}\nربات‌هایی که ازش استفاده می‌کنن: {n}",
               markup([[btn("🔁 فعال/غیرفعال", f"bxa:tt:{tid}"), btn("📄 جایگزینی فایل", f"bxa:tr:{tid}")],
                       [btn("🗑 حذف", f"bxa:td:{tid}")], [btn("🔙 قالب‌ها", "bxa:tpl")]]))


@ar.callback_query(F.data.startswith("bxa:t:"))
async def cb_tpl_detail(cb: CallbackQuery):
    await render_tpl(cb, int(cb.data.split(":")[2]))


@ar.callback_query(F.data.startswith("bxa:tt:"))
async def cb_tpl_toggle(cb: CallbackQuery):
    tid = int(cb.data.split(":")[2])
    await q_run("UPDATE templates SET active=1-active WHERE id=?", (tid,))
    await render_tpl(cb, tid)


@ar.callback_query(F.data.startswith("bxa:tr:"))
async def cb_tpl_replace(cb: CallbackQuery, state: FSMContext):
    await state.set_state(TplUpload.file)
    await state.update_data(replace=int(cb.data.split(":")[2]))
    await show(cb, "فایل .py جدید رو بفرست (جایگزین فایل قبلی می‌شه).\nلغو: /cancel")


@ar.callback_query(F.data.startswith("bxa:td:"))
async def cb_tpl_delete(cb: CallbackQuery):
    tid = int(cb.data.split(":")[2])
    if (await q_one("SELECT COUNT(*) c FROM ubots WHERE template_id=?", (tid,)))["c"]:
        return await cb.message.answer("❌ ربات‌هایی از این قالب استفاده می‌کنن. به‌جای حذف، غیرفعالش کن.")
    await q_run("DELETE FROM templates WHERE id=?", (tid,))
    (TPL_DIR / f"{tid}.py").unlink(missing_ok=True)
    await show(cb, "🗑 حذف شد.", markup([[btn("🧩 قالب‌ها", "bxa:tpl")]]))


# ═════════════════════ ادمین: ربات‌های کاربران ═════════════════════
@ar.callback_query(F.data == "bxa:bots")
async def cb_admin_bots(cb: CallbackQuery):
    bots = await q_all("SELECT * FROM ubots ORDER BY id DESC LIMIT 30")
    rows = [[btn(f"{STATUS[b['status']].split()[0]} @{b['username']} — کاربر {b['user_id']}", f"bxa:b:{b['id']}")]
            for b in bots]
    rows.append([btn("🔙 پنل", "adm")])
    await show(cb, "🤖 <b>ربات‌های کاربران</b>" + ("" if bots else "\n\nهنوز رباتی ثبت نشده."), markup(rows))


async def render_admin_bot(cb: CallbackQuery, bid: int) -> None:
    b = await q_one("SELECT u.*, t.title AS tpl FROM ubots u LEFT JOIN templates t ON t.id=u.template_id "
                    "WHERE u.id=?", (bid,))
    if not b:
        return
    p = PROCS.get(bid)
    running = "▶️ در حال اجرا" if p and p.returncode is None else "⏹ اجرا نمی‌شه"
    exp = f"{fmt_date(b['expires_at'])} ({days_left(b['expires_at'])} روز)" if b["expires_at"] else "—"
    await show(cb, f"🤖 <b>@{b['username']}</b> (#{bid})\nکاربر: <code>{b['user_id']}</code> | مالک ربات: "
                   f"<code>{b['owner_id']}</code>\nقالب: {html.escape(b['tpl'] or '-')}\n"
                   f"وضعیت: {STATUS[b['status']]} | {running}\nانقضا: {exp}",
               markup([[btn("⛔ تعلیق / رفع تعلیق", f"bxa:bs:{bid}"), btn("➕ ۳۰ روز", f"bxa:bp:{bid}")],
                       [btn("📜 لاگ", f"bxa:bl:{bid}"), btn("🗑 حذف", f"bxa:bd:{bid}")],
                       [btn("🔙 لیست", "bxa:bots")]]))


@ar.callback_query(F.data.startswith("bxa:b:"))
async def cb_admin_bot(cb: CallbackQuery):
    await render_admin_bot(cb, int(cb.data.split(":")[2]))


@ar.callback_query(F.data.startswith("bxa:bs:"))
async def cb_admin_suspend(cb: CallbackQuery):
    bid = int(cb.data.split(":")[2])
    b = await q_one("SELECT * FROM ubots WHERE id=?", (bid,))
    if not b:
        return
    if b["status"] == "suspended":
        status = "active" if b["expires_at"] > time.time() else "expired"
        await q_run("UPDATE ubots SET status=? WHERE id=?", (status, bid))
        if status == "active":
            await start_process(bid)
    else:
        await q_run("UPDATE ubots SET status='suspended' WHERE id=?", (bid,))
        await stop_process(bid)
    await render_admin_bot(cb, bid)


@ar.callback_query(F.data.startswith("bxa:bp:"))
async def cb_admin_plus(cb: CallbackQuery):
    bid = int(cb.data.split(":")[2])
    await activate_bot(cb.bot, bid, SUB_DAYS)
    await render_admin_bot(cb, bid)


@ar.callback_query(F.data.startswith("bxa:bl:"))
async def cb_admin_log(cb: CallbackQuery):
    log = BOTS_DIR / cb.data.split(":")[2] / "bot.log"
    text = log.read_text(encoding="utf-8", errors="replace")[-3000:] if log.exists() else "لاگی نیست."
    text = TOKEN_RE.sub("<token>", text)  # توکن هرگز نمایش داده نشود
    await cb.message.answer(f"<pre>{html.escape(text or 'خالی')}</pre>")


@ar.callback_query(F.data.startswith("bxa:bd:"))
async def cb_admin_del(cb: CallbackQuery):
    bid = cb.data.split(":")[2]
    await show(cb, "⚠️ این ربات حذف بشه؟", markup([[btn("✅ بله", f"bxa:bdy:{bid}")], [btn("❌ نه", f"bxa:b:{bid}")]]))


@ar.callback_query(F.data.startswith("bxa:bdy:"))
async def cb_admin_del_yes(cb: CallbackQuery):
    bid = int(cb.data.split(":")[2])
    await stop_process(bid)
    await q_run("DELETE FROM ubots WHERE id=?", (bid,))
    shutil.rmtree(BOTS_DIR / str(bid), ignore_errors=True)
    await show(cb, "🗑 حذف شد.", markup([[btn("🔙 لیست", "bxa:bots")]]))


# ═════════════════════ ادمین: سفارش اپ، APK، اطلاعات واریز ═════════════════════
@ar.callback_query(F.data == "bxa:orders")
async def cb_admin_orders(cb: CallbackQuery):
    os_ = await q_all("SELECT * FROM app_orders ORDER BY id DESC LIMIT 20")
    rows = [[btn(f"#{o['id']} {o['app_name']} — {ORDER_STATUS[o['status']]}", f"bxa:o:{o['id']}")] for o in os_]
    rows.append([btn("🔙 پنل", "adm")])
    await show(cb, "📦 <b>سفارش‌های اپ</b>" + ("" if os_ else "\n\nسفارشی نیست."), markup(rows))


@ar.callback_query(F.data.startswith("bxa:o:"))
async def cb_admin_order(cb: CallbackQuery):
    o = await q_one("SELECT * FROM app_orders WHERE id=?", (int(cb.data.split(":")[2]),))
    if o:
        await send_order_card(cb.bot, cb.message.chat.id, o)


@ar.callback_query(F.data.startswith("bxa:deliver:"))
async def cb_deliver(cb: CallbackQuery, state: FSMContext):
    oid = int(cb.data.split(":")[2])
    o = await q_one("SELECT * FROM app_orders WHERE id=?", (oid,))
    if not o:
        return
    await state.set_state(Deliver.file)
    await state.update_data(oid=oid)
    warn = "" if o["paid"] else "\n⚠️ پرداخت این سفارش هنوز تأیید نشده!"
    await cb.message.answer(f"فایل APK سفارش #{oid} رو بفرست؛ مستقیم برای کاربر ارسال می‌شه.{warn}\nلغو: /cancel")


@ar.message(StateFilter(Deliver.file), F.document)
async def msg_deliver(m: Message, state: FSMContext):
    oid = (await state.get_data())["oid"]
    o = await q_one("SELECT * FROM app_orders WHERE id=?", (oid,))
    try:
        await m.bot.send_document(o["user_id"], m.document.file_id,
                                  caption=f"🎉 اپلیکیشن «{html.escape(o['app_name'])}» آماده شد!\n"
                                          "فایل رو نصب کن (اگه اندروید هشدار داد، نصب از منبع ناشناس رو مجاز کن).")
    except (TelegramForbiddenError, TelegramBadRequest):
        return await m.answer("❌ ارسال نشد (کاربر ربات رو بلاک کرده؟). دوباره فایل بفرست یا /cancel")
    await q_run("UPDATE app_orders SET status='delivered' WHERE id=?", (oid,))
    await state.clear()
    await m.answer(f"✅ APK سفارش #{oid} برای کاربر ارسال شد.")


@ar.message(StateFilter(Deliver.file))
async def msg_deliver_nofile(m: Message):
    await m.answer("فایل APK رو به‌صورت سند (Document) بفرست. لغو: /cancel")


@ar.callback_query(F.data == "bxa:payinfo")
async def cb_payinfo(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PayInfo.text)
    cur = await get_setting("pay_info", "— (تنظیم نشده)")
    await show(cb, f"اطلاعات فعلی:\n\n{cur}\n\nمتن جدید رو بفرست (شماره کارت/آدرس کیف پول، نام صاحب حساب...). "
                   "مبلغ خودکار بالای این متن نوشته می‌شه.\nلغو: /cancel")


@ar.message(StateFilter(PayInfo.text))
async def msg_payinfo(m: Message, state: FSMContext):
    await set_setting("pay_info", md_fallback(m.html_text) if m.text else "")
    await state.clear()
    await m.answer("✅ ذخیره شد.", reply_markup=admin_panel())


# ═════════════════════ قالب نمونه (ربات پشتیبانی) ═════════════════════
SAMPLE_TEMPLATE = r'''"""
قالب نمونه: ربات پشتیبانی.
پیام مشتری‌ها برای مالک ربات (OWNER_ID) می‌رسه؛ مالک روی پیام Reply می‌زنه و جوابش برای مشتری می‌ره.
قرارداد قالب‌ها: توکن از BOT_TOKEN و آیدی مالک از OWNER_ID (متغیرهای محیطی) خونده می‌شه.
"""
import asyncio
import os
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

TOKEN = os.environ["BOT_TOKEN"]
OWNER = int(os.environ["OWNER_ID"])
ID_RE = re.compile(r"\[(\d+)\]")
dp = Dispatcher()


@dp.message(CommandStart())
async def start(m: Message):
    if m.from_user.id == OWNER:
        await m.answer("پنل پشتیبانی فعاله ✅\nروی پیام هر مشتری Reply بزن تا جوابت برای خودش بره.")
    else:
        await m.answer("سلام 👋 پیامت رو بنویس، به‌زودی جواب می‌دیم.")


@dp.message(F.from_user.id == OWNER, F.reply_to_message)
async def owner_reply(m: Message):
    src = m.reply_to_message
    found = ID_RE.search(src.text or src.caption or "")
    if not found:
        return await m.answer("روی پیام یک مشتری Reply بزن.")
    await m.copy_to(int(found.group(1)))
    await m.answer("✅ ارسال شد.")


@dp.message(F.from_user.id != OWNER, F.text)
async def from_user_text(m: Message):
    await m.bot.send_message(OWNER, f"📩 [{m.from_user.id}] {m.from_user.full_name}\n\n{m.text}")
    await m.answer("✅ پیامت ثبت شد.")


@dp.message(F.from_user.id != OWNER, F.photo | F.document)
async def from_user_media(m: Message):
    await m.copy_to(OWNER, caption=f"📩 [{m.from_user.id}] {m.from_user.full_name}\n\n{m.caption or ''}")
    await m.answer("✅ پیامت ثبت شد.")


async def main():
    await dp.start_polling(Bot(TOKEN))


if __name__ == "__main__":
    asyncio.run(main())
'''


async def seed_template() -> None:
    """بار اول یک قالب نمونه می‌سازد تا ربات‌ساز همان لحظه قابل‌امتحان باشد."""
    if await q_one("SELECT id FROM templates LIMIT 1"):
        return
    tid = await q_run("INSERT INTO templates(title,descr) VALUES(?,?)",
                      ("🎧 ربات پشتیبانی", "پیام مشتری‌ها به تو می‌رسه و از همون‌جا جواب می‌دی"))
    (TPL_DIR / f"{tid}.py").write_text(SAMPLE_TEMPLATE, encoding="utf-8")


async def main() -> None:
    global DB, FERNET, _TASK
    logging.basicConfig(level=logging.INFO)
    try:
        FERNET = Fernet(os.environ["TOKEN_KEY"].encode())
    except Exception:  # noqa: BLE001
        raise SystemExit("TOKEN_KEY داخل .env نامعتبره. خطش رو پاک کن تا دوباره ساخته بشه (ربات‌های قبلی باز نمی‌شن).")
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    BOTS_DIR.mkdir(parents=True, exist_ok=True)
    DB = await aiosqlite.connect(DB_PATH)
    DB.row_factory = aiosqlite.Row
    await DB.execute("PRAGMA foreign_keys=ON")
    await DB.execute("PRAGMA journal_mode=WAL")
    await DB.execute("PRAGMA synchronous=NORMAL")
    await DB.executescript(SCHEMA)
    await DB.executescript(SCHEMA2)
    cols = [r["name"] for r in await q_all("PRAGMA table_info(steps)")]
    if "cmd" not in cols:  # مهاجرت دیتابیس قدیمی
        await DB.execute("ALTER TABLE steps ADD COLUMN cmd TEXT")
    await DB.commit()
    await seed_if_empty()
    await seed_template()

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp = Dispatcher(storage=MemoryStorage())
    dp.callback_query.outer_middleware(AutoAnswer())
    dp.include_routers(common, admin, ar, ur, user)  # user (با fallback) باید آخر باشد
    _TASK = asyncio.create_task(supervisor(bot))
    try:
        await dp.start_polling(bot)
    finally:
        _TASK.cancel()
        for bid in list(PROCS):
            await stop_process(bid)
        await DB.close()


if __name__ == "__main__":
    asyncio.run(main())
