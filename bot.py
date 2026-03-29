import os
import asyncio
import threading
import logging
import traceback
import aiohttp

from flask import Flask
from telegram import Update, InputFile
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu")

if not REPLICATE_API_TOKEN:
    raise ValueError("REPLICATE_API_TOKEN puuttuu")

app = Flask(__name__)

@app.route("/")
def health_check():
    return "Bot is alive", 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

def build_photo_prompt(user_text: str) -> str:
    return f"""
Create a photorealistic, high-quality image.

User request:
{user_text}

Requirements:
- photorealistic
- realistic lighting
- realistic skin texture
- detailed face
- cinematic but natural look
- no watermark
- no text
""".strip()

async def generate_image_replicate(prompt: str) -> bytes:
    prediction_url = "https://api.replicate.com/v1/predictions"

    headers = {
        "Authorization": f"Bearer {REPLICATE_API_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "version": "a6b5c5e4f0c5f7a2b8f3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4",
        "input": {
            "prompt": prompt,
            "width": 1024,
            "height": 1024,
            "num_inference_steps": 8,
            "output_format": "jpg",
            "output_quality": 95,
            "safety_tolerance": 3,
        },
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post(prediction_url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status != 201:
                raise RuntimeError(f"Prediction creation failed: {resp.status} | {body}")

            prediction = await resp.json()
            prediction_id = prediction["id"]
            logger.info("Prediction created: %s", prediction_id)

        poll_headers = {
            "Authorization": f"Bearer {REPLICATE_API_TOKEN}",
        }

        poll_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"

        for _ in range(180):
            await asyncio.sleep(1)

            async with session.get(poll_url, headers=poll_headers) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"Prediction polling failed: {resp.status} | {body}")

                result = await resp.json()
                status = result.get("status")
                logger.info("Prediction status: %s", status)

                if status == "succeeded":
                    output = result.get("output")
                    if not output:
                        raise RuntimeError("Prediction succeeded but output missing")

                    image_url = output[0] if isinstance(output, list) else output

                    async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=60)) as img_resp:
                        if img_resp.status != 200:
                            raise RuntimeError(f"Image download failed: {img_resp.status}")
                        return await img_resp.read()

                if status == "failed":
                    raise RuntimeError(f"Prediction failed: {result.get('error', 'unknown error')}")

                if status in ("canceled", "cancelled"):
                    raise RuntimeError("Prediction cancelled")

        raise TimeoutError("Image generation timed out")

def is_image_request(text: str) -> bool:
    t = text.lower()
    triggers = [
        "tee kuva",
        "lähetä kuva",
        "haluan kuvan",
        "näytä kuva",
        "luo kuva",
        "generate image",
        "create image",
        "make image",
        "photo of",
        "portrait of",
    ]
    return any(x in t for x in triggers)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Lähetä viesti kuten:\n"
        "tee kuva realistisesta muotokuvasta"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pyydä kuvaa tavallisella viestillä.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            return

        text = update.message.text.strip()

        if not is_image_request(text):
            await update.message.reply_text(
                "Pyydä kuvaa esim:\ntee kuva naisesta metsässä"
            )
            return

        await update.message.reply_text("Generoin kuvaa...")

        prompt = build_photo_prompt(text)
        image_bytes = await generate_image_replicate(prompt)

        await update.message.reply_photo(
            photo=InputFile(image_bytes, filename="generated.jpg"),
            caption="Tässä kuvasi."
        )

    except Exception as e:
        logger.error("Image generation failed: %s", e)
        traceback.print_exc()
        await update.message.reply_text(f"Kuvan generointi epäonnistui: {e}")

async def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    try:
        await asyncio.Event().wait()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
