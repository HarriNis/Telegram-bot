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

# =========================
# LOGGING
# =========================
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =========================
# ENV
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu ympäristömuuttujista")

if not REPLICATE_API_TOKEN:
    raise ValueError("REPLICATE_API_TOKEN puuttuu ympäristömuuttujista")

# =========================
# FLASK HEALTH CHECK
# =========================
app = Flask(__name__)

@app.route("/")
def health_check():
    return "Telegram photo bot is alive", 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

# =========================
# IMAGE PROMPT
# =========================
def build_photo_prompt(user_text: str) -> str:
    """
    Luo valokuvamaisen promptin käyttäjän pyynnön pohjalta.
    """
    user_text = user_text.strip()

    return f"""
Create a photorealistic, high-quality portrait photograph.

User request:
{user_text}

Requirements:
- photorealistic
- natural human proportions
- realistic skin texture
- cinematic but believable lighting
- detailed eyes and face
- professional photography look
- high detail
- no text, no watermark
- natural composition
""".strip()

# =========================
# REPLICATE IMAGE GENERATION
# =========================
async def generate_image_replicate(prompt: str) -> bytes:
    """
    Luo kuvan Replicate API:n kautta ja palauttaa kuvan byteseinä.
    """
    prediction_url = "https://api.replicate.com/v1/predictions"

    headers = {
        "Authorization": f"Token {REPLICATE_API_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        # Esimerkkiversio käyttäjän alkuperäisestä pohjasta
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

    timeout = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # 1. Luo prediction
        async with session.post(prediction_url, headers=headers, json=payload) as resp:
            if resp.status != 201:
                error_text = await resp.text()
                raise RuntimeError(f"Prediction creation failed: {resp.status} | {error_text}")

            prediction = await resp.json()
            prediction_id = prediction["id"]
            logger.info("Replicate prediction created: %s", prediction_id)

        # 2. Pollaa tulosta
        poll_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"

        for _ in range(180):  # max ~180s
            await asyncio.sleep(1)

            async with session.get(poll_url, headers={"Authorization": f"Token {REPLICATE_API_TOKEN}"}) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"Prediction polling failed: {resp.status} | {error_text}")

                result = await resp.json()
                status = result.get("status")
                logger.info("Replicate status: %s", status)

                if status == "succeeded":
                    output = result.get("output")
                    if not output:
                        raise RuntimeError("Prediction succeeded but output missing")

                    image_url = output[0] if isinstance(output, list) else output
                    logger.info("Image URL received: %s", image_url)

                    # 3. Lataa valmis kuva
                    async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=60)) as img_resp:
                        if img_resp.status != 200:
                            raise RuntimeError(f"Image download failed: {img_resp.status}")
                        return await img_resp.read()

                if status == "failed":
                    raise RuntimeError(f"Prediction failed: {result.get('error', 'unknown error')}")

                if status in ("canceled", "cancelled"):
                    raise RuntimeError("Prediction was cancelled")

        raise TimeoutError("Image generation timed out")

# =========================
# COMMANDS
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hei. Lähetä viesti, jossa pyydät kuvaa.\n"
        "Esim:\n"
        "- tee kuva vaaleasta naisesta metsässä\n"
        "- lähetä kuva cyberpunk-muotokuvasta\n"
        "- haluan kuvan realistisesta mallista"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Komennot:\n"
        "/start - Aloitus\n"
        "/help - Ohje\n\n"
        "Pyydä kuvaa tavallisella viestillä."
    )

# =========================
# MESSAGE HANDLER
# =========================
def is_image_request(text: str) -> bool:
    text = text.lower()
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
    return any(trigger in text for trigger in triggers)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            return

        text = update.message.text.strip()
        logger.info("User message: %s", text)

        if not is_image_request(text):
            await update.message.reply_text(
                "Pyydä kuvaa esimerkiksi näin:\n"
                "`tee kuva realistisesta muotokuvasta`\n"
                "`lähetä kuva naisesta kaupungissa sateessa`",
                parse_mode="Markdown"
            )
            return

        await update.message.reply_text("Generoin kuvaa...")

        prompt = build_photo_prompt(text)
        image_bytes = await generate_image_replicate(prompt)

        photo = InputFile(image_bytes, filename="generated_photo.jpg")

        await update.message.reply_photo(
            photo=photo,
            caption="Tässä kuvasi."
        )

    except Exception as e:
        logger.error("handle_message error: %s", e)
        traceback.print_exc()
        await update.message.reply_text(f"Kuvan generointi epäonnistui: {e}")

# =========================
# MAIN
# =========================
async def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask health check started on port %s", PORT)

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting Telegram bot...")

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
