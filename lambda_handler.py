import json
import os
from telegram import Update
from telegram.ext import Application
from bot import application   # از bot.py لود می‌کنیم

TOKEN = os.getenv("8198774412:AAHphDh2Wo9Nzgomlk9xq9y3aeETsVpkXr0")

async def handle_update(update_json):
    update = Update.de_json(update_json, application.bot)
    await application.process_update(update)

def lambda_handler(event, context):
    body = json.loads(event["body"])
    application.create_task(handle_update(body))

    return {
        "statusCode": 200,
        "body": json.dumps({"ok": True})
    }
