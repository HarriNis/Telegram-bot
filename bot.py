import os
import random
import json
import asyncio
import threading
from datetime import datetime
from collections import deque
from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from openai import AsyncOpenAI

# --- RENDERIN VAATIMA DUMMY PALVELIN ---
app = Flask(__name__)
@app.route('/')
def health_check(): return "Megan is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- ASETUKSET ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")

if not TELEGRAM_TOKEN or not GROK_API_KEY:
    raise ValueError("TELEGRAM_TOKEN tai GROK_API_KEY puuttuu!")

client = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

# --- MUISTIT JA MUUTTUJAT ---
recent_user = deque(maxlen=15)
recent_megan = deque(maxlen=15)
conversation_history = {}
long_term_memory = {}
last_message_time = {} # TÄMÄ PUUTTUI ALKUPERÄISESTÄ

moods = {"kiukku":0.45, "halu":0.65, "tylsä":0.28, "mustas":0.42, "iva":0.72, "väsy":0.35, "syyllisyys":0.18}

# (Pidä update_moods, dom_mood, too_similar, load_memory, save_memory, summarize_old_history ja get_system_prompt ennallaan...)

# ... [TÄHÄN VÄLIIN KAIKKI AIEMMAT FUNKTIOT] ...

async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    if not message: return
    text = message.text or message.caption or ""

    load_memory(user_id)
    
    # Korjaus: Varmistetaan että last_message_time on alustettu
    last_message_time[user_id] = datetime.now()

    # ... [LOPUT CHAT-LOGIIKASTA] ...
    # (Huom: Tarkista että grok-malli on oikein, esim "grok-beta")

async def start_background(app: Application):
    asyncio.create_task(independent_message_loop(app))
    print("✅ Taustatehtävät käynnistetty")

# --- KORJATTU MAIN-FUNKTIO ---
def main():
    # Käynnistetään Flask taustalle Renderiä varten
    threading.Thread(target=run_flask, daemon=True).start()

    # Luodaan sovellus
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    application.post_init = start_background

    print("🚀 Megan käynnistyy Render-yhteensopivassa tilassa")
    
    # Käytetään suoraan run_pollingia ilman ulkoista asyncio.runia
    # Tämä välttää "RuntimeError: Cannot close a running event loop"
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
