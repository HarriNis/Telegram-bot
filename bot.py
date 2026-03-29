import os
import json
import base64
import asyncio
import logging
import traceback
import aiohttp

from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip().strip('"').strip("'")
VENICE_API_KEY = os.getenv("VENICE_API_KEY", "").strip().strip('"').strip("'")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu")

if not VENICE_API_KEY:
    raise ValueError("VENICE_API_KEY puuttuu")

VENICE_URL = "https://api.venice.ai/api/v1/image/generations"


def is_image_request(text: str) -> bool:
    t = text.lower()
    triggers = [
        "tee kuva",
        "lähetä kuva",
        "haluan kuvan",
        "näytä kuva",
        "luo kuva",
        "ota kuva",
        "create image",
        "generate image",
    ]
    return any(x in t for x in triggers)


def build_prompt(user_text: str) -> str:
    return f"""
Create a photorealistic image based on this request:

{user_text}

Requirements:
- photorealistic
- realistic skin texture
- realistic lighting
- natural composition
- detailed face
- no text
- no watermark
""".strip()


async def generate_image_venice(prompt: str) -> bytes:
    payload = {
        "model": "fluently-xl",
        "prompt": prompt,
        "size": "1024x1024",
        "response_format": "b64_json"
    }

    headers = {
        "Authorization": f"Bearer {VENICE_API_KEY}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        async with session.post(VENICE_URL, headers=headers, json=payload) as resp:
            body = await resp.text()
            logger.info("VENICE STATUS: %s", resp.status)
            logger.info("VENICE BODY PREVIEW: %s", body[:500])

            if resp.status != 200:
                raise RuntimeError(f"Venice request failed: {resp.status} | {body}")

            data = json.loads(body)

    items = data.get("data", [])
    if not items:
        raise RuntimeError("Venice response missing data[]")

    b64_json = items[0].get("b64_json")
    if not b64_json:
        raise RuntimeError("Venice response missing data[0].b64_json")

    try:
        return base64.b64decode(b64_json)
    except Exception as e:
        raise RuntimeError(f"Base64 decode failed: {e}") from e


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hei. Lähetä mikä tahansa viesti niin näytän chat ID:n.\n\n"
        "Pyydä kuvaa esimerkiksi:\n"
        "tee kuva realistisesta muotokuvasta"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            return

        text = update.message.text.strip()
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        print("CHAT ID:", chat_id)
        print("USER ID:", user_id)

        if not is_image_request(text):
            await update.message.reply_text(
                f"Chat ID on: {chat_id}\n\n"
                f"Lähetä kuvapyyntö esimerkiksi:\n"
                f"tee kuva naisesta iltavalossa"
            )
            return

        await update.message.reply_text(
            f"Chat ID on: {chat_id}\n\nGeneroin Venice-testikuvaa..."
        )

        prompt = build_prompt(text)
        image_bytes = await generate_image_venice(prompt)

        await update.message.reply_photo(
            photo=InputFile(image_bytes, filename="venice_test.png"),
            caption=f"Venice-testikuva onnistui.\nChat ID: {chat_id}"
        )

    except Exception as e:
        logger.error("HANDLE ERROR: %s", e)
        traceback.print_exc()
        await update.message.reply_text(f"Virhe: {e}")


async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting...")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
