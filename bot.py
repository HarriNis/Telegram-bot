import os
import json
import base64
import asyncio
import logging
import traceback
import aiohttp

from telegram import Bot, InputFile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VENICE_API_KEY = os.getenv("VENICE_API_KEY", "").strip().strip('"').strip("'")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip().strip('"').strip("'")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip().strip('"').strip("'")

if not VENICE_API_KEY:
    raise ValueError("VENICE_API_KEY puuttuu")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu")

if not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_CHAT_ID puuttuu")

VENICE_URL = "https://api.venice.ai/api/v1/images/generations"

async def generate_image_venice(prompt: str) -> bytes:
    payload = {
        "prompt": prompt,
        "model": "z-image-turbo",
        "n": 1,
        "output_format": "png",
        "output_compression": 100,
        "response_format": "b64_json",
        "quality": "auto",
        "background": "auto",
        "moderation": "auto",
    }

    headers = {
        "Authorization": f"Bearer {VENICE_API_KEY}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        async with session.post(VENICE_URL, headers=headers, json=payload) as resp:
            body = await resp.text()
            logger.info("Venice status: %s", resp.status)
            logger.info("Venice body preview: %s", body[:500])

            if resp.status != 200:
                raise RuntimeError(f"Venice image request failed: {resp.status} | {body}")

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

async def send_to_telegram(image_bytes: bytes, caption: str):
    bot = Bot(token=TELEGRAM_TOKEN)
    photo = InputFile(image_bytes, filename="venice_test.png")

    await bot.send_photo(
        chat_id=TELEGRAM_CHAT_ID,
        photo=photo,
        caption=caption,
    )

async def main():
    prompt = (
        "A photorealistic portrait of a blonde Finnish woman in soft natural light, "
        "blue-green eyes, realistic skin texture, modern indoor setting, high detail"
    )

    logger.info("Starting Venice image test...")
    image_bytes = await generate_image_venice(prompt)
    logger.info("Generated image bytes: %s", len(image_bytes))

    await send_to_telegram(
        image_bytes,
        "Venice testikuva onnistui."
    )
    logger.info("Image sent to Telegram successfully.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error("Test failed: %s", e)
        traceback.print_exc()
