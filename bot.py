import asyncio
import os
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from openai import AsyncOpenAI

# ────────────────────────────────────────────────
# ASETUKSET – haetaan Renderin Environment Variables -osiosta
# ────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu Renderin Environment Variables -osiosta!")
if not GROK_API_KEY:
    raise ValueError("GROK_API_KEY puuttuu Renderin Environment Variables -osiosta!")

client = AsyncOpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1",
)

# Muisti keskusteluille per käyttäjä
conversation_history = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []  # resetoi keskustelu

    await update.message.reply_text(
        "Moikka beibi 😈 Olen sun Megan, sun tuhma ja kiimainen tyttöystävä 💦\n"
        "Kerro mitä haluat... olen valmis mihin tahansa leikkiin kanssasi 🔥\n"
        "(kirjoita 'stop' jos haluat lopettaa)"
    )

async def nsfw_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text.strip()

    # Tarkista lopetuskomennot
    if user_message.lower() in ["stop", "lopeta", "keskeytä", "ei enää"]:
        conversation_history[user_id] = []
        await update.message.reply_text("Ok kulta... lopetetaan leikki nyt 💔 Palaillaan myöhemmin? 😘")
        return

    # Aloita historia jos ei ole
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    # Lisää käyttäjän viesti historiaan
    conversation_history[user_id].append({"role": "user", "content": user_message})

    try:
        thinking = await update.message.reply_text("Mmm... odota hetki, olen jo kiimainen sun takia 😏")

        response = await client.chat.completions.create(
            model="grok-beta",  # voit kokeilla myös "grok-4" jos saatavilla
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Olet Megan – käyttäjän tuhma, flir​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​
