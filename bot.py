import os
import random
import json
import asyncio
from datetime import datetime
from collections import deque
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from openai import AsyncOpenAI

# ==================== ENV ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")

if not TELEGRAM_TOKEN or not GROK_API_KEY:
    raise ValueError("TELEGRAM_TOKEN tai GROK_API_KEY puuttuu!")

client = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

print("🚀 Megan käynnistyy – Render vakaa")

# ==================== TUNNELMAT ====================
moods = {"kiukku":0.45, "halu":0.65, "tylsä":0.28, "mustas":0.42, "iva":0.72, "väsy":0.35, "syyllisyys":0.18}

def update_moods(txt):
    txt = txt.lower()

    def shift(key, val):
        moods[key] = max(0.05, min(1.0, moods[key] + val))

    if any(w in txt for w in ["älä","lopeta","en halua","ei"]):
        shift("kiukku", 0.2)
        shift("halu", -0.15)

    if any(w in txt for w in ["rakastan","kiitos","rakas"]):
        shift("halu", 0.3)
        shift("tylsä", -0.2)

    if any(w in txt for w in ["muu mies","toinen"]):
        shift("mustas", 0.35)

def dom_mood():
    return max(moods, key=moods.get)

# ==================== VIESTI HISTORIA ====================
recent_user = deque(maxlen=12)
recent_megan = deque(maxlen=12)

def too_similar(t):
    t = t.lower().strip()
    for o in recent_user:
        o = o.lower().strip()
        if len(t) > 6 and (o.startswith(t[:6]) or t.startswith(o[:6])):
            return True
    return False

# ==================== MUISTIT ====================
MEMORY_DIR = "/tmp/megan_memory"
os.makedirs(MEMORY_DIR, exist_ok=True)

conversation_history = {}
long_term_memory = {}

def load_memory(user_id):
    file = os.path.join(MEMORY_DIR, f"{user_id}.json")

    if not os.path.exists(file):
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""
        return

    try:
        with open(file, "r") as f:
            data = json.load(f)
            conversation_history[user_id] = data.get("history", [])
            long_term_memory[user_id] = data.get("long", "")
    except:
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""

def save_memory(user_id):
    file = os.path.join(MEMORY_DIR, f"{user_id}.json")

    data = {
        "history": conversation_history[user_id][-25:],
        "long": long_term_memory[user_id][-1600:]
    }

    with open(file, "w") as f:
        json.dump(data, f)

# ==================== SYSTEM PROMPT ====================
def system_prompt(user_id):
    return f"""
Olet Megan, dominoiva nainen. Vastaa aina suomeksi.
Nykyinen mielialasi: {dom_mood()}
Pitkä muisti:
{long_term_memory.get(user_id, "")}
"""

# ==================== CHAT ====================
async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    text = update.message.text or ""

    load_memory(user_id)

    if text.lower() in ["stop","lopeta"]:
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""
        await update.message.reply_text("Ok. Lopetetaan.")
        return

    if too_similar(text):
        await update.message.reply_text("Älä toista itseäsi.")
        return

    update_moods(text)

    recent_user.append(text)

    conversation_history.setdefault(user_id, []).append(
        {"role":"user","content":text}
    )

    try:
        thinking = await update.message.reply_text("Mietin...")

        response = await client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=[
                {"role":"system","content":system_prompt(user_id)}
            ] + conversation_history[user_id][-15:],
            max_tokens=600,
            temperature=0.85
        )

        reply = response.choices[0].message.content.strip()

        await thinking.edit_text(reply)

        conversation_history[user_id].append(
            {"role":"assistant","content":reply}
        )

        recent_megan.append(reply)

    except Exception as e:
        print("Virhe:", e)
        await update.message.reply_text("Hetki... jotain hajosi.")

    save_memory(user_id)

# ==================== ITSESTÄÄN VIESTIT ====================
async def independent_loop(app: Application):

    await asyncio.sleep(20)

    while True:
        await asyncio.sleep(random.randint(500, 1500))

        for user_id in list(conversation_history.keys()):
            try:
                if random.random() < 0.12:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=random.choice([
                            "Missä sä oot?",
                            "Mä tylsistyn täällä...",
                            "Ajattelin sua."
                        ])
                    )
            except:
                pass

# ==================== START ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    load_memory(user_id)

    await update.message.reply_text(
        "Hei. Mä oon Megan. Mitä kuuluu?"
    )

    save_memory(user_id)

# ==================== MAIN ====================
async def main():

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT, megan_chat))

    asyncio.create_task(independent_loop(application))

    print("✅ Megan toimii Renderissä")

    await application.run_polling(
        drop_pending_updates=True
    )

if __name__ == "__main__":
    asyncio.run(main())
