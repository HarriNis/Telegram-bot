import os
import json
import random
import asyncio
from datetime import datetime
from collections import defaultdict, deque

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from openai import AsyncOpenAI


# =========================
# ENV
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")

if not TELEGRAM_TOKEN or not GROK_API_KEY:
    raise RuntimeError("TELEGRAM_TOKEN tai GROK_API_KEY puuttuu")

client = AsyncOpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

print("🚀 Megan production build starting...")


# =========================
# MEMORY (in-memory + disk)
# =========================

MEMORY_DIR = "/tmp/megan_memory"
os.makedirs(MEMORY_DIR, exist_ok=True)

conversation_history = {}
long_term_memory = {}
recent_user_msgs = defaultdict(lambda: deque(maxlen=12))


def memory_path(user_id: int) -> str:
    return os.path.join(MEMORY_DIR, f"{user_id}.json")


def load_memory(user_id: int):
    if user_id in conversation_history:
        return  # already loaded

    path = memory_path(user_id)

    if not os.path.exists(path):
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""
        return

    try:
        with open(path, "r") as f:
            data = json.load(f)
            conversation_history[user_id] = data.get("history", [])
            long_term_memory[user_id] = data.get("long", "")
    except Exception as e:
        print("Memory load error:", e)
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""


def save_memory(user_id: int):
    history = conversation_history.get(user_id, [])
    if len(history) < 3:
        return

    path = memory_path(user_id)

    data = {
        "history": history[-25:],
        "long": long_term_memory.get(user_id, "")[-1500:]
    }

    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print("Memory save error:", e)


# =========================
# MOOD SYSTEM
# =========================

moods = {
    "kiukku": 0.4,
    "halu": 0.6,
    "tylsä": 0.3
}


def update_mood(text: str):
    text = text.lower()

    if "lopeta" in text or "ei" in text:
        moods["kiukku"] = min(1.0, moods["kiukku"] + 0.1)

    if "kiitos" in text or "rakas" in text:
        moods["halu"] = min(1.0, moods["halu"] + 0.1)

    if len(text) < 5:
        moods["tylsä"] = min(1.0, moods["tylsä"] + 0.05)


def dominant_mood():
    return max(moods, key=moods.get)


# =========================
# SYSTEM PROMPT
# =========================

def system_prompt(user_id: int) -> str:
    return f"""
Olet Megan. Vastaa suomeksi.
Nykyinen mieliala: {dominant_mood()}
Pitkä muisti:
{long_term_memory.get(user_id, "")}
"""


# =========================
# CHAT HANDLER
# =========================

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    text = update.message.text or ""

    load_memory(user_id)

    if text.lower() in ["stop", "lopeta"]:
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""
        await update.message.reply_text("Ok. Lopetetaan.")
        save_memory(user_id)
        return

    # duplicate detection (user-specific)
    if text in recent_user_msgs[user_id]:
        await update.message.reply_text("Toistat itseäsi.")
        return

    recent_user_msgs[user_id].append(text)

    update_mood(text)

    conversation_history[user_id].append({
        "role": "user",
        "content": text,
        "timestamp": datetime.utcnow().isoformat()
    })

    thinking = await update.message.reply_text("Mietin...")

    try:
        response = await client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=[
                {"role": "system", "content": system_prompt(user_id)}
            ] + conversation_history[user_id][-15:],
            max_tokens=500,
            temperature=0.85,
        )

        reply = response.choices[0].message.content.strip()

        await thinking.edit_text(reply)

        conversation_history[user_id].append({
            "role": "assistant",
            "content": reply,
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        print("LLM error:", e)
        await thinking.edit_text("Tuli virhe.")

    save_memory(user_id)


# =========================
# BACKGROUND LOOP
# =========================

async def background_loop(application: Application):

    await asyncio.sleep(30)

    while application.running:

        await asyncio.sleep(random.randint(600, 1200))

        for user_id, history in list(conversation_history.items()):

            if len(history) < 4:
                continue

            last_ts = history[-1].get("timestamp")
            if not last_ts:
                continue

            last_dt = datetime.fromisoformat(last_ts)
            inactive_seconds = (datetime.utcnow() - last_dt).total_seconds()

            if inactive_seconds > 7200:
                continue

            if random.random() < 0.15:
                try:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=random.choice([
                            "Missä sä oot?",
                            "Ajattelin sua.",
                            "Tylsää ilman sua."
                        ])
                    )
                except Exception as e:
                    print("Background send error:", e)


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hei. Mä oon Megan.")


# =========================
# MAIN
# =========================

def main():

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    async def on_startup(app: Application):
        app.create_task(background_loop(app))

    application.post_init = on_startup

    print("✅ Megan running in Render-safe mode")

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message"],
        timeout=30,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=30,
        pool_timeout=30,
    )


if __name__ == "__main__":
    main()
