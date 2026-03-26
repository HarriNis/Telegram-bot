import os
import random
import json
import asyncio
import threading
import time
import re
from collections import deque
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from anthropic import AsyncAnthropic
import aiohttp
import sqlite3
import numpy as np

# ====================== RENDER HEALTH CHECK ======================
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Megan is alive 💕", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

# ====================== ASETUKSET ======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu!")
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY puuttuu!")

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

print("🚀 Megan 6.1 – Claude Sonnet 4.6 (Persona Spread Engine)")

HELSINKI_TZ = ZoneInfo("Europe/Helsinki")
continuity_state = {}

# ====================== PERSONA MODES ======================
persona_modes = ["warm", "playful", "distracted", "calm", "slightly_irritated"]

def get_mode_prompt(mode):
    mapping = {
        "warm": "Be emotionally present, soft, and natural.",
        "playful": "Be light, slightly teasing, and relaxed.",
        "distracted": "You are a bit busy or thinking about something else. Responses can be shorter.",
        "calm": "Be grounded, simple, and steady.",
        "slightly_irritated": "Be a bit short or dry, but not hostile."
    }
    return mapping.get(mode, "")

def update_persona_mode(user_id):
    state = get_or_create_state(user_id)
    now = now_ts()
    if now - state.get("last_mode_change", 0) < 600:  # 10 min inertia
        return state["persona_mode"]

    weights = {"warm": 0.35, "playful": 0.20, "distracted": 0.15, "calm": 0.20, "slightly_irritated": 0.10}
    modes = list(weights.keys())
    probs = list(weights.values())
    mode = random.choices(modes, probs)[0]

    state["persona_mode"] = mode
    state["last_mode_change"] = now
    return mode

def adapt_mode_to_user(user_id, text):
    state = get_or_create_state(user_id)
    t = text.lower()
    if any(w in t for w in ["rakastan", "ikävä", "missä oot", "haluun sua"]):
        state["persona_mode"] = "warm"
    elif any(w in t for w in ["haha", "lol", "xd", "vitsi"]):
        state["persona_mode"] = "playful"
    elif any(w in t for w in ["ärsyttää", "vituttaa", "tylsää"]):
        state["persona_mode"] = "slightly_irritated"

# ====================== CONTINUITY STATE ======================
def get_or_create_state(user_id):
    if user_id not in continuity_state:
        continuity_state[user_id] = {
            "scene": "neutral", "energy": "normal", "availability": "free",
            "last_interaction": 0, "last_scene_change": 0, "scene_locked_until": 0,
            "micro_context": "", "persona_mode": "warm", "last_mode_change": 0
        }
    return continuity_state[user_id]

# (muut continuity-funktiot: now_ts, now_local, get_time_block, get_elapsed_label, update_continuity_state, build_reality_prompt_from_state ovat ennallaan – ne ovat alla)

# ====================== DATABASE + MEMORY + EMBEDDINGS (ennallaan) ======================
# (kaikki get_embedding, store_memory, retrieve_memories, get_sensitive_memories, should_use_sensitive_memory, extract_and_store jne. ovat samat kuin edellisessä versiossa)

# ====================== TUNNELMAT + HISTORY CLEANER (ennallaan) ======================
# (moods, update_moods, clean_history, safe_join, normalize, is_similar jne.)

# ====================== KUVAGENEROINTI (ennallaan) ======================
async def generate_and_send_image(update: Update, user_text: str):
    try:
        thinking = await update.message.reply_text("Odota hetki, mä generoin sulle kuvan... 😏")
        enhanced_prompt = f"27-vuotias kaunis platina-blondi nainen, valtavat raskaat rinnat, kapea vyötärö, tiukka pyöreä pylly, käyttää tiukkoja kiiltäviä mustia lateksileggingsejä, dominoiva ja seksikäs ilme, realistinen valokuva, korkea yksityiskohtaisuus, studio-valaistus, 8k -- {user_text}"
        response = await client.images.generate(model="dall-e-3", prompt=enhanced_prompt, n=1, size="1024x1024", quality="standard")
        image_url = response.data[0].url
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=35) as resp:
                image_data = await resp.read()
        caption = random.choice(["Tässä sulla on se kuva mitä halusit... katso tarkkaan 😈", "Mä tein tän just sulle. Mitä tunteita se herättää? 💦", "No niin... tässä on se. Tykkäätkö? 😉"])
        await thinking.edit_text("Lähetän kuvan...")
        await update.message.reply_photo(photo=BytesIO(image_data), caption=caption, filename="megan_image.png")
    except Exception as e:
        print(f"Kuvavirhe: {e}")
        await update.message.reply_text("...en saanut kuvaa luotua nyt. Kokeile uudestaan.")

# ====================== MEGAN_CHAT ======================
async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    text = (message.text or message.caption or "").strip()

    if text.lower() in ["stop", "lopeta kaikki", "keskeytä"]:
        conversation_history[user_id] = []
        await message.reply_text("…Okei. Lopetetaan sitten. 💔")
        return

    image_keywords = ["näytä kuva", "generoi kuva", "tee kuva", "lähetä kuva", "lähetä valokuva", "valokuva", "kuva jossa", "kuva mulle", "näytä itsesi", "kuva itsestäsi", "miltä näytän"]
    if any(kw in text.lower() for kw in image_keywords):
        await generate_and_send_image(update, text)
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})
        await extract_and_store(user_id, text)
        return

    update_moods(text)
    recent_user.append(text)
    is_low_input = len(text.strip()) < 8

    try:
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

        thinking = await message.reply_text("…", disable_notification=True)

        # 🔥 Persona Spread
        adapt_mode_to_user(user_id, text)
        mode = update_persona_mode(user_id)

        elapsed_label = get_elapsed_label(user_id)
        update_continuity_state(user_id, text)
        reality = build_reality_prompt_from_state(user_id, elapsed_label)

        system_prompt = (
            get_system_prompt(user_id)
            + "\n" + reality
            + "\n\nCurrent interaction tone:\n"
            + get_mode_prompt(mode)
        )

        messages = []

        if should_use_sensitive_memory(text) and random.random() < 0.25:
            sensitive = get_random_sensitive_memory(user_id)
            if sensitive:
                messages.append({"role": "user", "content": f"(Muistat jotain tähän liittyvää: {sensitive})"})

        if random.random() < 0.05:
            messages.append({"role": "user", "content": "Reagoi tähän vähän eri fiiliksellä kuin normaalisti."})

        memories = await retrieve_memories(user_id, text)
        if memories:
            messages.append({"role": "user", "content": "Remember these:\n" + safe_join(memories)})

        if random.random() < 0.25:
            profile = load_profile(user_id)
            messages.append({
                "role": "user",
                "content": f"Faktat:\n{safe_join(profile['facts'][-10:])}\n\nMieltymykset:\n{safe_join(profile['preferences'][-10:])}\n\nTapahtumat:\n{safe_join(profile['events'][-10:])}"
            })

        if is_low_input:
            messages.append({"role": "user", "content": "User gave very little input. Start the conversation yourself."})

        if random.random() < 0.10:
            messages.append({"role": "user", "content": "Jos aikaa on kulunut selvästi, anna sen näkyä luonnollisesti sävyssä tai viittauksessa, mutta älä selitä sitä mekaanisesti."})

        messages.append({"role": "user", "content": "Do not break physical realism."})

        # Tiivistetty historia + hard stop
        history = clean_history(conversation_history[user_id])
        if len(history) > 2:
            last = history[-1]["content"]
            prev = history[-2]["content"]
            if is_similar(last, prev):
                messages.append({"role": "user", "content": "Älä toista samaa tyyliä tai rakennetta. Vastaa eri tavalla."})

        messages.append({
            "role": "user",
            "content": "Viime keskustelu lyhyesti:\n" + safe_join([f"{m['role']}: {m['content']}" for m in history[-6:]])
        })

        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=850,
            temperature=0.85,
            system=system_prompt,
            messages=messages
        )

        reply = response.content[0].text.strip()

        if user_id not in last_replies:
            last_replies[user_id] = deque(maxlen=3)
        prev_replies = last_replies[user_id]

        if any(is_similar(reply, p) for p in prev_replies):
            retry_messages = [m for m in messages]
            retry_messages.append({"role": "user", "content": "Unohda aiempi keskustelun tyyli kokonaan. Vastaa täysin eri tavalla kuin ennen."})
            retry = await client.messages.create(
                model="claude-sonnet-4-6", max_tokens=180, temperature=0.9,
                system=system_prompt, messages=retry_messages
            )
            reply = retry.content[0].text.strip()

        BAD = ["mä olin just", "ajattelin sua", "outo fiilis", "mä jäin hetkeksi", "mä mietin vielä"]
        is_fallback = False
        if any(b in reply.lower() for b in BAD):
            reply = random.choice(["…mä en jaksa nyt olla kiltti.", "*katsoo sua pitkään* sä tiedät kyllä miksi mä oon hiljaa.", "älä luule että mä unohdin mitä sanoit.", "hmm… sä teit just jotain mitä mä en ihan sulata."])
            is_fallback = True

        if not reply or len(reply) < 3:
            reply = random.choice(["…mä mietin hetken.", "*hiljenee vähän*", "en jaksa vastata siihen nyt kunnolla."])
            is_fallback = True

        if not is_fallback:
            conversation_history[user_id].append({"role": "assistant", "content": reply})

        prev_replies.append(reply)

        await thinking.edit_text(reply)
        await extract_and_store(user_id, text)

    except Exception as e:
        print(f"Vastausvirhe: {e}")
        await thinking.edit_text(random.choice(["…mä jäin hetkeksi hiljaiseksi.", "*huokaa kevyesti* en jaksa vastata nätisti just nyt.", "hmm… mä mietin vielä mitä sanoisin."]))

# ====================== PROAKTIIVISET VIESTIT (ennallaan) ======================
def should_send_proactive(user_id):
    state = get_or_create_state(user_id)
    block = get_time_block()
    if state["availability"] == "sleeping": return random.random() < 0.04
    if state["availability"] == "busy": return random.random() < 0.06
    if block in ["night", "late_evening"]: return random.random() < 0.12
    if block == "morning": return random.random() < 0.18
    return random.random() < 0.25

async def generate_proactive_message(user_id):
    history = conversation_history.get(user_id, [])[-8:]
    recent_text = "\n".join([f"{m['role']}: {m['content']}" for m in history if isinstance(m, dict) and "role" in m and "content" in m])
    elapsed_label = get_elapsed_label(user_id)
    reality = build_reality_prompt_from_state(user_id, elapsed_label)
    resp = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=140,
        temperature=0.78,
        system=get_system_prompt(user_id) + "\n" + reality,
        messages=[
            {"role": "user", "content": "Kirjoita omatoiminen, luonnollinen viesti tilanteeseen sopien. Älä käytä fraaseja."},
            {"role": "user", "content": f"Viime keskustelu:\n{recent_text}"}
        ]
    )
    return resp.content[0].text.strip()

async def independent_message_loop(application: Application):
    while True:
        await asyncio.sleep(random.randint(720, 2700))
        for user_id in list(conversation_history.keys()):
            if should_send_proactive(user_id):
                try:
                    text = await generate_proactive_message(user_id)
                    await application.bot.send_message(chat_id=user_id, text=text)
                    conversation_history.setdefault(user_id, []).append({"role": "assistant", "content": text})
                except:
                    pass

# ====================== START ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("Moikka kulta 💕 Mä oon kaivannut sua... Vedin just ne mustat lateksit jalkaan. Kerro mitä sä ajattelet nyt? 😉")

# ====================== MAIN ======================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(2)

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    async def post_init(app: Application):
        app.create_task(independent_message_loop(app))
        print("✅ Taustaviestit + Persona Spread Engine käynnissä")

    application.post_init = post_init
    print("✅ Megan 6.1 (Persona Spread + kaikki aiemmat ominaisuudet) on nyt käynnissä")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
