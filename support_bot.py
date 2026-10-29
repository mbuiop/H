"""
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
