#!/usr/bin/env python3
"""نقطه‌ی ورود: ربات آموزشی + ربات‌ساز + اپلیکیشن‌ساز.   اجرا:  python run.py"""
import asyncio

import bot
import builder

if __name__ == "__main__":
    asyncio.run(bot.main(extra_routers=builder.routers(),
                         on_startup=builder.on_startup,
                         on_shutdown=builder.on_shutdown))
