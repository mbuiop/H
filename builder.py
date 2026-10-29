#!/usr/bin/env python3
"""
ماژول «ربات‌ساز» و «اپلیکیشن‌ساز» (به‌صورت افزونه روی bot.py؛ با run.py اجرا می‌شود)

ربات‌ساز:
  • ادمین از پنل فایل پایتون (قالب) آپلود می‌کند. هر قالب یک برنامه‌ی مستقل است که
    BOT_TOKEN و OWNER_ID را از متغیرهای محیطی می‌خواند (نمونه: templates_examples/support_bot.py).
  • کاربر: «🤖 ساخت ربات» ← لیست ربات‌های من ← ربات جدید ← قالب ← توکن ← آیدی ← واریز و فیش.
  • با تأیید فیش، ربات کاربر خودکار در یک پروسه‌ی جدا اجرا می‌شود؛ اشتراک ماهانه، یادآوری و قطع خودکار.
اپلیکیشن‌ساز:
  • کاربر لینک سایت، آیکون و اسم اپ را می‌فرستد ← تأیید نهایی ← مشخصات برای ادمین ← واریز و فیش.
  • ادمین خودش APK می‌سازد و از پنل مستقیم برای همان کاربر می‌فرستد.
"""
from __future__ import annotations

import asyncio
import html
import io
import logging
import os
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from cryptography.fernet import Fernet, InvalidToken

import bot as core
from bot import ADMIN_IDS, btn, get_setting, markup, q_all, q_one, q_run, set_setting, show

# ───────────────────────── تنظیمات ─────────────────────────
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

SCHEMA = """
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
    cur = await core.DB.execute(sql, args)
    await core.DB.commit()
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


async def on_startup(bot: Bot) -> None:
    global FERNET, _TASK
    key = os.getenv("TOKEN_KEY", "")
    try:
        FERNET = Fernet(key.encode())
    except Exception:  # noqa: BLE001
        raise SystemExit("TOKEN_KEY تنظیم نشده/نامعتبره. بساز:\n"
                         "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    BOTS_DIR.mkdir(parents=True, exist_ok=True)
    await core.DB.executescript(SCHEMA)
    await core.DB.commit()
    _TASK = asyncio.create_task(supervisor(bot))


async def on_shutdown() -> None:
    if _TASK:
        _TASK.cancel()
    for bid in list(PROCS):
        await stop_process(bid)


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


@ar.callback_query(F.data.startswith("bxa:t:"))
async def cb_tpl_detail(cb: CallbackQuery):
    t = await q_one("SELECT * FROM templates WHERE id=?", (int(cb.data.split(":")[2]),))
    if not t:
        return
    n = (await q_one("SELECT COUNT(*) c FROM ubots WHERE template_id=?", (t["id"],)))["c"]
    await show(cb, f"🧩 <b>{html.escape(t['title'])}</b>\n{html.escape(t['descr'])}\n\n"
                   f"وضعیت: {'🟢 فعال' if t['active'] else '⚪️ غیرفعال'}\nربات‌هایی که ازش استفاده می‌کنن: {n}",
               markup([[btn("🔁 فعال/غیرفعال", f"bxa:tt:{t['id']}"), btn("📄 جایگزینی فایل", f"bxa:tr:{t['id']}")],
                       [btn("🗑 حذف", f"bxa:td:{t['id']}")], [btn("🔙 قالب‌ها", "bxa:tpl")]]))


@ar.callback_query(F.data.startswith("bxa:tt:"))
async def cb_tpl_toggle(cb: CallbackQuery):
    tid = int(cb.data.split(":")[2])
    await q_run("UPDATE templates SET active=1-active WHERE id=?", (tid,))
    cb.data = f"bxa:t:{tid}"
    await cb_tpl_detail(cb)


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
    await set_setting("pay_info", core.md_fallback(m.html_text) if m.text else "")
    await state.clear()
    await m.answer("✅ ذخیره شد.", reply_markup=core.admin_panel())


def routers() -> list[Router]:
    return [ar, ur]
