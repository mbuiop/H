# -*- coding: utf-8 -*-
# نصب:  pip install "python-telegram-bot==20.7"
# اجرا: python bot.py
import os
import sqlite3
import asyncio
import builder
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)

# ====== تنظیمات ======
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")          # از @BotFather (با export تنظیم کن)
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))     # آیدی عددی تلگرام خودت
TEMPLATE_ZIP = "template.zip"                       # زیپ پروژه اپلیکیشن آماده
CARD_NUMBER = "5892101187322777"
PRICE = 2_000_000                           # قیمت اشتراک (تومان)
REF_PERCENT = 10                            # درصد پورسانت رفرال
MIN_WITHDRAW = 2_000_000                    # حداقل برداشت (تومان)
# ======================

db = sqlite3.connect("orders.db", check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,
    status TEXT, link TEXT, icon_id TEXT, app_name TEXT, receipt_msg INTEGER)""")
db.execute("""CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY, username TEXT, ref_by INTEGER,
    balance INTEGER DEFAULT 0, warnings INTEGER DEFAULT 0)""")
db.execute("""CREATE TABLE IF NOT EXISTS withdraws(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER,
    card TEXT, status TEXT)""")
for _col in ("receipt_msg INTEGER", "apk_id TEXT", "aab_id TEXT"):  # اگر دیتابیس قدیمی داری
    try:
        db.execute("ALTER TABLE orders ADD COLUMN " + _col)
    except sqlite3.OperationalError:
        pass
db.commit()
# وضعیت سفارش: await_receipt, pending_pay, await_link, await_icon, await_name, building, done, rejected


def fmt(n):
    return f"{n:,}"


def register(user, ref=None):
    ex = db.execute("SELECT 1 FROM users WHERE user_id=?", (user.id,)).fetchone()
    if not ex:
        rb = None
        if ref and ref != user.id and db.execute("SELECT 1 FROM users WHERE user_id=?", (ref,)).fetchone():
            rb = ref
        db.execute("INSERT INTO users(user_id,username,ref_by) VALUES(?,?,?)",
                   (user.id, user.username or "-", rb))
    else:
        db.execute("UPDATE users SET username=? WHERE user_id=?", (user.username or "-", user.id))
    db.commit()


def balance(uid):
    r = db.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    return r[0] if r else 0


def add_balance(uid, amount):
    db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, uid)); db.commit()


def active_order(uid):
    return db.execute("SELECT id,status FROM orders WHERE user_id=? AND status NOT IN ('done','rejected') "
                      "ORDER BY id DESC LIMIT 1", (uid,)).fetchone()


def set_status(oid, st):
    db.execute("UPDATE orders SET status=? WHERE id=?", (st, oid)); db.commit()


MENU = M([[B("📱 ساخت اپلیکیشن", callback_data="new")],
          [B("💰 کیف پول و دعوت دوستان", callback_data="wallet")]])

PANEL = M([[B("✅ تایید اشتراک", callback_data="ap:subs")],
           [B("🛠 تایید و ساخت اپلیکیشن", callback_data="ap:build")],
           [B("👥 آمار کاربران با آیدی", callback_data="ap:stats")],
           [B("📢 ارسال پیام همگانی", callback_data="ap:bc")],
           [B("⚠️ ارسال اخطار به کاربر", callback_data="ap:warn")],
           [B("💸 درخواست‌های برداشت", callback_data="ap:wd")],
           [B("📦 آپلود قالب اپلیکیشن", callback_data="ap:tpl")]])


# ---------------- کاربر ----------------
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    ref = None
    if c.args and c.args[0].startswith("ref_") and c.args[0][4:].isdigit():
        ref = int(c.args[0][4:])
    register(u.effective_user, ref)
    await u.message.reply_text("سلام 👋\nبه ربات ساخت اپلیکیشن خوش آمدید.\nبرای شروع یکی از گزینه‌ها را بزنید.",
                               reply_markup=MENU)


async def show_wallet(c, chat_id, uid):
    bal = balance(uid)
    cnt = db.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (uid,)).fetchone()[0]
    link = f"https://t.me/{c.bot.username}?start=ref_{uid}"
    text = (f"💰 موجودی شما: {fmt(bal)} تومان\n"
            f"👥 تعداد دعوت‌شدگان: {cnt}\n\n"
            f"🔗 لینک دعوت اختصاصی شما:\n{link}\n\n"
            f"هر کسی با لینک شما وارد شود و اشتراک بخرد، {REF_PERCENT}٪ مبلغ ({fmt(PRICE * REF_PERCENT // 100)} تومان) "
            f"به موجودی شما اضافه می‌شود.\n\n"
            f"وقتی موجودی شما به {fmt(MIN_WITHDRAW)} تومان رسید می‌توانید برداشت کنید یا با آن اپلیکیشن بسازید.")
    kb = []
    if bal >= MIN_WITHDRAW:
        kb.append([B("💸 برداشت", callback_data="wd")])
    if bal >= PRICE:
        kb.append([B("📱 ساخت اپلیکیشن با موجودی", callback_data="usebal")])
    await c.bot.send_message(chat_id, text, reply_markup=M(kb) if kb else None)


async def send_order_to_admin(c, oid):
    uid, un, link, icon, name = db.execute(
        "SELECT user_id,username,link,icon_id,app_name FROM orders WHERE id=?", (oid,)).fetchone()
    try:
        await c.bot.send_photo(ADMIN_ID, icon, caption=f"آیکون سفارش #{oid}")
    except Exception:
        await c.bot.send_document(ADMIN_ID, icon, caption=f"آیکون سفارش #{oid}")
    await c.bot.send_message(
        ADMIN_ID,
        f"🆕 سفارش #{oid}\nکاربر: {uid} (@{un})\nنام اپ: {name}\nلینک: {link}",
        reply_markup=M([[B("🤖 ساخت خودکار (GitHub)", callback_data=f"auto:{oid}")],
                        [B("📤 ارسال دستی اپلیکیشن", callback_data=f"send:{oid}")]]))


LINK_PROMPT = ("🔗 حالا لینک سایتی که می‌خواهید به اپلیکیشن تبدیل شود را ارسال کنید.\n\n"
               "⚠️ دقت کنید لینک را کاملاً درست بفرستید؛ بعد از ساخت اپلیکیشن به هیچ عنوان "
               "امکان تغییر لینک وجود ندارد.")


# ---------------- پنل ادمین ----------------
async def panel(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != ADMIN_ID:
        return
    c.application.bot_data["astate"] = None
    await u.message.reply_text("🎛 پنل مدیریت", reply_markup=PANEL)


async def cancel(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id == ADMIN_ID:
        c.application.bot_data["astate"] = None
        await u.message.reply_text("لغو شد.", reply_markup=PANEL)
    else:
        c.user_data.clear()
        await u.message.reply_text("لغو شد.", reply_markup=MENU)


async def admin_panel_action(c, q, arg):
    bd = c.application.bot_data
    bd["astate"] = None

    if arg == "subs":
        rows = db.execute("SELECT id,user_id,username FROM orders WHERE status='pending_pay'").fetchall()
        if not rows:
            await q.message.reply_text("فیش در انتظار تایید نداریم.")
            return
        kb = [[B(f"#{r[0]} | {r[1]} @{r[2]}", callback_data=f"rcpt:{r[0]}")] for r in rows]
        await q.message.reply_text(f"🧾 فیش‌های در انتظار تایید ({len(rows)})", reply_markup=M(kb))

    elif arg == "build":
        rows = db.execute("SELECT id,app_name FROM orders WHERE status='building'").fetchall()
        if not rows:
            await q.message.reply_text("سفارش در حال ساخت نداریم.")
            return
        kb = [[B(f"#{r[0]} | {r[1]}", callback_data=f"show:{r[0]}")] for r in rows]
        await q.message.reply_text(f"🛠 سفارش‌های در حال ساخت ({len(rows)})", reply_markup=M(kb))

    elif arg == "stats":
        total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        done = db.execute("SELECT COUNT(*) FROM orders WHERE status='done'").fetchone()[0]
        await q.message.reply_text(f"👥 کل کاربران: {total}\n📱 اپ‌های تحویل‌شده: {done}")
        rows = db.execute(
            "SELECT u.user_id,u.username,u.balance,u.warnings,"
            "(SELECT COUNT(*) FROM users r WHERE r.ref_by=u.user_id),"
            "(SELECT COUNT(*) FROM orders o WHERE o.user_id=u.user_id AND o.status IN ('building','done')) "
            "FROM users u ORDER BY u.rowid").fetchall()
        lines = [f"🆔 {r[0]} | @{r[1]} | موجودی {fmt(r[2])} | دعوت {r[4]} | اپ {r[5]} | اخطار {r[3]}" for r in rows]
        for i in range(0, len(lines), 30):
            await q.message.reply_text("\n".join(lines[i:i + 30]))

    elif arg == "bc":
        bd["astate"] = {"t": "bc"}
        await q.message.reply_text("📢 پیام همگانی را بفرستید (متن، عکس یا هر چیز دیگر).\nبرای لغو: /cancel")

    elif arg == "warn":
        bd["astate"] = {"t": "warn_id"}
        await q.message.reply_text("⚠️ آیدی عددی کاربر متخلف را بفرستید.\nبرای لغو: /cancel")

    elif arg == "tpl":
        bd["astate"] = {"t": "tpl"}
        await q.message.reply_text("📦 فایل zip پروژه اندروید را بفرستید.\nاگر بیشتر از ۲۰ مگابایت است، دستی با نام template.zip کنار bot.py بگذارید.\nبرای لغو: /cancel")

    elif arg == "wd":
        rows = db.execute("SELECT id,user_id,amount,card FROM withdraws WHERE status='pending'").fetchall()
        if not rows:
            await q.message.reply_text("درخواست برداشتی نداریم.")
            return
        for r in rows:
            await q.message.reply_text(
                f"💸 برداشت #{r[0]}\nکاربر: {r[1]}\nمبلغ: {fmt(r[2])} تومان\nکارت: {r[3]}",
                reply_markup=M([[B("✅ پرداخت شد", callback_data=f"wd_ok:{r[0]}"),
                                 B("❌ رد", callback_data=f"wd_no:{r[0]}")]]))


# ---------------- ساخت خودکار ----------------
async def run_auto_build(c, oid):
    bd = c.application.bot_data
    bd.setdefault("building", set()).add(oid)
    loop = asyncio.get_running_loop()

    def progress(text):
        asyncio.run_coroutine_threadsafe(c.bot.send_message(ADMIN_ID, text[:3800]), loop)

    try:
        await c.bot.send_message(ADMIN_ID, f"🤖 ساخت خودکار سفارش #{oid} شروع شد...")
        link, icon_id, name = db.execute("SELECT link,icon_id,app_name FROM orders WHERE id=?", (oid,)).fetchone()
        os.makedirs("work", exist_ok=True)
        icon_path = f"work/icon_{oid}.img"
        f = await c.bot.get_file(icon_id)
        await f.download_to_drive(icon_path)
        apk_path, aab_path, repo_url = await asyncio.to_thread(
            builder.build_app, oid, TEMPLATE_ZIP, link, name, icon_path, progress)
        with open(apk_path, "rb") as fh:
            msg_ = await c.bot.send_document(
                ADMIN_ID, fh, filename=f"app_{oid}.apk",
                caption=f"✅ اپ سفارش #{oid} ساخته شد.\n{repo_url}\nبعد از تست، تایید کن تا برای کاربر برود.",
                reply_markup=M([[B("✅ تایید و ارسال به کاربر", callback_data=f"apk_ok:{oid}")]]))
        aab_fid = None
        if aab_path:
            with open(aab_path, "rb") as fh:
                m2 = await c.bot.send_document(ADMIN_ID, fh, filename=f"app_{oid}.aab",
                                               caption="📦 فایل AAB مخصوص انتشار در گوگل پلی")
            aab_fid = m2.document.file_id
        db.execute("UPDATE orders SET apk_id=?, aab_id=? WHERE id=?", (msg_.document.file_id, aab_fid, oid))
        db.commit()
    except Exception as e:
        await c.bot.send_message(ADMIN_ID, f"❌ ساخت خودکار سفارش #{oid} ناموفق بود:\n{str(e)[:3000]}")
    finally:
        bd["building"].discard(oid)


# ---------------- کالبک‌ها ----------------
async def cb(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    uid = q.from_user.id
    d = q.data

    # ---- کاربر ----
    if d == "new":
        register(q.from_user)
        if active_order(uid):
            await q.message.reply_text("شما یک سفارش در حال انجام دارید.")
            return
        db.execute("INSERT INTO orders(user_id,username,status) VALUES(?,?,?)",
                   (uid, q.from_user.username or "-", "await_receipt")); db.commit()
        await q.message.reply_text(
            f"💳 شماره کارت:\n{CARD_NUMBER}\n\n💰 مبلغ: {fmt(PRICE)} تومان\n\n"
            "لطفاً مبلغ را واریز کنید و تصویر فیش واریزی را همینجا ارسال کنید.")
        return

    if d == "wallet":
        register(q.from_user)
        await show_wallet(c, q.message.chat_id, uid)
        return

    if d == "wd":
        if balance(uid) < MIN_WITHDRAW:
            await q.message.reply_text(f"حداقل موجودی برای برداشت {fmt(MIN_WITHDRAW)} تومان است.")
            return
        c.user_data["await_card"] = True
        await q.message.reply_text("💳 شماره کارت ۱۶ رقمی خود را برای واریز ارسال کنید.\nبرای لغو: /cancel")
        return

    if d == "usebal":
        if active_order(uid):
            await q.message.reply_text("شما یک سفارش در حال انجام دارید.")
            return
        if balance(uid) < PRICE:
            await q.message.reply_text("موجودی شما کافی نیست.")
            return
        add_balance(uid, -PRICE)
        db.execute("INSERT INTO orders(user_id,username,status) VALUES(?,?,?)",
                   (uid, q.from_user.username or "-", "await_link")); db.commit()
        await q.message.reply_text("✅ اشتراک شما با موجودی فعال شد.\n\n" + LINK_PROMPT)
        await c.bot.send_message(ADMIN_ID, f"ℹ️ کاربر {uid} (@{q.from_user.username}) با موجودی کیف پول اشتراک خرید.")
        return

    # ---- ادمین ----
    if uid != ADMIN_ID:
        return
    act, arg = d.split(":", 1)

    if act == "ap":
        await admin_panel_action(c, q, arg)
        return

    # ---- برداشت ----
    if act in ("wd_ok", "wd_no"):
        wid = int(arg)
        r = db.execute("SELECT user_id,amount,status FROM withdraws WHERE id=?", (wid,)).fetchone()
        if not r or r[2] != "pending":
            await q.message.reply_text("این درخواست قبلاً بررسی شده.")
            return
        if act == "wd_ok":
            db.execute("UPDATE withdraws SET status='paid' WHERE id=?", (wid,)); db.commit()
            await q.message.reply_text(f"✅ برداشت #{wid} ثبت شد.")
            await c.bot.send_message(r[0], f"✅ برداشت {fmt(r[1])} تومان شما واریز شد.")
        else:
            db.execute("UPDATE withdraws SET status='rejected' WHERE id=?", (wid,)); db.commit()
            add_balance(r[0], r[1])
            await q.message.reply_text(f"❌ برداشت #{wid} رد شد و مبلغ به موجودی کاربر برگشت.")
            await c.bot.send_message(r[0], f"❌ درخواست برداشت شما رد شد و {fmt(r[1])} تومان به موجودی شما برگشت.")
        return

    oid = int(arg)
    row = db.execute("SELECT user_id,status,app_name,link,receipt_msg FROM orders WHERE id=?", (oid,)).fetchone()
    if not row:
        return
    user_id, status = row[0], row[1]

    if act == "rcpt":   # نمایش فیش از پنل
        if row[4]:
            await c.bot.copy_message(
                ADMIN_ID, user_id, row[4], caption=f"🧾 فیش سفارش #{oid}\nکاربر: {user_id}",
                reply_markup=M([[B("✅ تایید", callback_data=f"pay_ok:{oid}"),
                                 B("❌ رد", callback_data=f"pay_no:{oid}")]]))
    elif act == "pay_ok":
        if status != "pending_pay":
            await q.message.reply_text("این سفارش قبلاً بررسی شده.")
            return
        set_status(oid, "await_link")
        await q.message.reply_text(f"✅ پرداخت سفارش #{oid} تایید شد.")
        await c.bot.send_message(user_id, "✅ پرداخت شما تایید و اشتراک شما فعال شد.\n\n" + LINK_PROMPT)
        # پورسانت رفرال
        ref = db.execute("SELECT ref_by FROM users WHERE user_id=?", (user_id,)).fetchone()
        if ref and ref[0]:
            bonus = PRICE * REF_PERCENT // 100
            add_balance(ref[0], bonus)
            try:
                await c.bot.send_message(
                    ref[0], f"🎉 یکی از دعوت‌شدگان شما اشتراک خرید!\n"
                            f"💰 {fmt(bonus)} تومان به موجودی شما اضافه شد.")
            except Exception:
                pass
    elif act == "pay_no":
        if status != "pending_pay":
            await q.message.reply_text("این سفارش قبلاً بررسی شده.")
            return
        set_status(oid, "rejected")
        await q.message.reply_text(f"❌ سفارش #{oid} رد شد.")
        await c.bot.send_message(user_id, "❌ فیش شما تایید نشد. در صورت اشتباه، دوباره از منو اقدام کنید.",
                                 reply_markup=MENU)
    elif act == "show":
        await send_order_to_admin(c, oid)
    elif act == "auto":
        bd = c.application.bot_data
        if status != "building":
            await q.message.reply_text("این سفارش در وضعیت ساخت نیست.")
        elif not os.path.exists(TEMPLATE_ZIP):
            await q.message.reply_text("ابتدا از پنل «آپلود قالب اپلیکیشن» پروژه را بفرست.")
        elif oid in bd.setdefault("building", set()):
            await q.message.reply_text("این سفارش در حال ساخت است.")
        else:
            t = asyncio.create_task(run_auto_build(c, oid))
            bd.setdefault("tasks", set()).add(t)
            t.add_done_callback(bd["tasks"].discard)
    elif act == "apk_ok":
        r = db.execute("SELECT apk_id,aab_id FROM orders WHERE id=?", (oid,)).fetchone()
        if status == "done" or not r or not r[0]:
            await q.message.reply_text("این سفارش قبلاً ارسال شده یا فایلی ندارد.")
            return
        await c.bot.send_message(user_id, "🎉 اپلیکیشن شما تایید و آماده شد! فایل در پیام بعد ارسال می‌شود.")
        await c.bot.send_document(user_id, r[0], caption="📱 اپلیکیشن شما (APK برای نصب)")
        if r[1]:
            await c.bot.send_document(user_id, r[1], caption="📦 فایل AAB برای انتشار در گوگل پلی")
        set_status(oid, "done")
        await q.message.reply_text(f"✅ اپ سفارش #{oid} برای کاربر ارسال شد و اعلان رفت.")
    elif act == "send":
        c.application.bot_data["astate"] = {"t": "send", "oid": oid}
        await q.message.reply_text(f"فایل اپلیکیشن سفارش #{oid} را (به صورت فایل/Document) ارسال کنید.")


# ---------------- پیام‌ها ----------------
async def admin_message(u: Update, c: ContextTypes.DEFAULT_TYPE):
    m = u.message
    bd = c.application.bot_data
    st = bd.get("astate")
    if not st:
        return

    if st["t"] == "send":
        if not m.document:
            await m.reply_text("لطفاً اپ را به صورت فایل (Document) بفرستید.")
            return
        oid = st["oid"]
        user_id = db.execute("SELECT user_id FROM orders WHERE id=?", (oid,)).fetchone()[0]
        await c.bot.send_message(user_id, "🎉 اپلیکیشن شما تایید و آماده شد! فایل در پیام بعد ارسال می‌شود.")
        await c.bot.send_document(user_id, m.document.file_id, caption="📱 اپلیکیشن شما")
        set_status(oid, "done")
        bd["astate"] = None
        await m.reply_text(f"✅ اپ سفارش #{oid} برای کاربر ارسال شد و اعلان رفت.", reply_markup=PANEL)

    elif st["t"] == "tpl":
        if not (m.document and (m.document.file_name or "").lower().endswith(".zip")):
            await m.reply_text("لطفاً فایل zip پروژه را بفرستید.")
            return
        f = await c.bot.get_file(m.document.file_id)
        await f.download_to_drive(TEMPLATE_ZIP)
        bd["astate"] = None
        await m.reply_text("✅ قالب ذخیره شد.", reply_markup=PANEL)

    elif st["t"] == "bc":
        bd["astate"] = None
        ids = [r[0] for r in db.execute("SELECT user_id FROM users")]
        await m.reply_text(f"⏳ در حال ارسال برای {len(ids)} کاربر...")
        ok = 0
        for i in ids:
            try:
                await c.bot.copy_message(i, m.chat_id, m.message_id)
                ok += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        await m.reply_text(f"📢 ارسال شد: {ok} از {len(ids)}", reply_markup=PANEL)

    elif st["t"] == "warn_id":
        t = (m.text or "").strip()
        if not t.isdigit() or not db.execute("SELECT 1 FROM users WHERE user_id=?", (int(t),)).fetchone():
            await m.reply_text("کاربری با این آیدی پیدا نشد. دوباره بفرستید یا /cancel بزنید.")
            return
        bd["astate"] = {"t": "warn_text", "uid": int(t)}
        await m.reply_text("متن اخطار را بنویسید:")

    elif st["t"] == "warn_text":
        uid = st["uid"]
        bd["astate"] = None
        db.execute("UPDATE users SET warnings=warnings+1 WHERE user_id=?", (uid,)); db.commit()
        try:
            await c.bot.send_message(uid, f"⚠️ اخطار از طرف مدیریت:\n\n{m.text}")
            await m.reply_text("✅ اخطار ارسال شد.", reply_markup=PANEL)
        except Exception:
            await m.reply_text("❌ ارسال نشد (کاربر ربات را بلاک کرده).", reply_markup=PANEL)


async def msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    m = u.message
    uid = m.from_user.id

    if uid == ADMIN_ID:
        await admin_message(u, c)
        return

    register(m.from_user)

    # ---- دریافت شماره کارت برای برداشت ----
    if c.user_data.get("await_card"):
        card = "".join(ch for ch in (m.text or "") if ch.isdigit())
        if len(card) != 16:
            await m.reply_text("شماره کارت باید ۱۶ رقم باشد. دوباره ارسال کنید یا /cancel بزنید.")
            return
        bal = balance(uid)
        c.user_data.pop("await_card")
        if bal < MIN_WITHDRAW:
            await m.reply_text("موجودی کافی نیست.")
            return
        add_balance(uid, -bal)
        db.execute("INSERT INTO withdraws(user_id,amount,card,status) VALUES(?,?,?,'pending')", (uid, bal, card))
        db.commit()
        wid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        await m.reply_text("✅ درخواست برداشت شما ثبت شد و پس از بررسی واریز می‌شود.")
        await c.bot.send_message(
            ADMIN_ID,
            f"💸 برداشت جدید #{wid}\nکاربر: {uid} (@{m.from_user.username})\nمبلغ: {fmt(bal)} تومان\nکارت: {card}",
            reply_markup=M([[B("✅ پرداخت شد", callback_data=f"wd_ok:{wid}"),
                             B("❌ رد", callback_data=f"wd_no:{wid}")]]))
        return

    o = active_order(uid)
    if not o:
        await m.reply_text("برای شروع یکی از گزینه‌ها را بزنید.", reply_markup=MENU)
        return
    oid, st = o

    if st == "await_receipt":
        if not (m.photo or m.document):
            await m.reply_text("لطفاً تصویر فیش واریزی را ارسال کنید.")
            return
        db.execute("UPDATE orders SET status='pending_pay', receipt_msg=? WHERE id=?", (m.message_id, oid))
        db.commit()
        await c.bot.copy_message(
            ADMIN_ID, m.chat_id, m.message_id,
            caption=f"🧾 فیش سفارش #{oid}\nکاربر: {uid} (@{m.from_user.username})",
            reply_markup=M([[B("✅ تایید", callback_data=f"pay_ok:{oid}"),
                             B("❌ رد", callback_data=f"pay_no:{oid}")]]))
        await m.reply_text("✅ فیش شما دریافت شد و در حال بررسی است. لطفاً منتظر بمانید.")

    elif st == "pending_pay":
        await m.reply_text("فیش شما در حال بررسی است. لطفاً منتظر بمانید.")

    elif st == "await_link":
        t = (m.text or "").strip()
        if not t.startswith(("http://", "https://")):
            await m.reply_text("لینک معتبر نیست. لینک کامل را با http:// یا https:// ارسال کنید.")
            return
        db.execute("UPDATE orders SET link=?, status='await_icon' WHERE id=?", (t, oid)); db.commit()
        await m.reply_text("✅ لینک ثبت شد.\n\n🖼 حالا آیکون اپلیکیشن را ارسال کنید.\n"
                           "می‌توانید آن را با ChatGPT یا هر ابزار دیگری بسازید و اینجا بفرستید.")

    elif st == "await_icon":
        if m.photo:
            fid = m.photo[-1].file_id
        elif m.document:
            fid = m.document.file_id
        else:
            await m.reply_text("لطفاً آیکون را به صورت تصویر ارسال کنید.")
            return
        db.execute("UPDATE orders SET icon_id=?, status='await_name' WHERE id=?", (fid, oid)); db.commit()
        await m.reply_text("✅ آیکون ثبت شد.\n\n✏️ حالا نام اپلیکیشن را وارد کنید.")

    elif st == "await_name":
        name = (m.text or "").strip()
        if not name:
            await m.reply_text("لطفاً نام اپلیکیشن را به صورت متن ارسال کنید.")
            return
        db.execute("UPDATE orders SET app_name=?, status='building' WHERE id=?", (name, oid)); db.commit()
        await m.reply_text("⏳ اطلاعات شما ثبت شد.\nفرایند ساخت اپلیکیشن در حال انجام است. "
                           "پس از آماده شدن برای شما ارسال می‌شود.")
        await send_order_to_admin(c, oid)

    elif st == "building":
        await m.reply_text("⏳ فرایند ساخت اپلیکیشن در حال انجام است.")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, msg))
    app.run_polling()


if __name__ == "__main__":
    main()
