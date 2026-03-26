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

print("🚀 Megan 5.7 – Claude Sonnet 4.6 (scene lock + täysi dialogihistoria)")

HELSINKI_TZ = ZoneInfo("Europe/Helsinki")
continuity_state = {}

def now_ts():
    return time.time()

def now_local():
    return datetime.now(HELSINKI_TZ)

def get_time_block():
    hour = now_local().hour
    if 0 <= hour < 6: return "night"
    elif 6 <= hour < 10: return "morning"
    elif 10 <= hour < 17: return "day"
    elif 17 <= hour < 22: return "evening"
    return "late_evening"

def get_or_create_state(user_id):
    if user_id not in continuity_state:
        continuity_state[user_id] = {
            "scene": "neutral",
            "energy": "normal",
            "availability": "free",
            "last_interaction": 0,
            "last_scene_change": 0,
            "scene_locked_until": 0,      # ← UUSI
            "micro_context": ""
        }
    return continuity_state[user_id]

def get_elapsed_label(user_id):
    state = get_or_create_state(user_id)
    if not state["last_interaction"]:
        return "first_contact"
    elapsed = now_ts() - state["last_interaction"]
    if elapsed < 120: return "immediate"
    elif elapsed < 1800: return "recent"
    elif elapsed < 14400: return "hours"
    else: return "long_gap"

def update_continuity_state(user_id, text):
    state = get_or_create_state(user_id)
    now = now_ts()
    block = get_time_block()

    # Päivänajan vaikutus
    if block == "night":
        state["availability"] = "sleeping" if random.random() < 0.6 else "low_presence"
        state["energy"] = "low"
    elif block == "morning":
        state["availability"] = "busy" if random.random() < 0.35 else "free"
        state["energy"] = "low" if random.random() < 0.5 else "normal"
    elif block == "day":
        state["availability"] = "busy" if random.random() < 0.55 else "free"
        state["energy"] = "normal"
    elif block == "evening":
        state["availability"] = "free"
        state["energy"] = "normal" if random.random() < 0.6 else "high"
    else:
        state["availability"] = "free"
        state["energy"] = "low" if random.random() < 0.4 else "normal"

    # Käyttäjän viesti ankkuroi scenen + lukitus
    t = text.lower()
    forced_scene = None
    if any(w in t for w in ["töissä", "duunissa", "palaverissa", "meetingissä", "toimistolla"]):
        forced_scene = "work"
        state["availability"] = "busy"
        state["micro_context"] = "töissä"
    elif any(w in t for w in ["kotona", "sohvalla", "keittiössä"]):
        forced_scene = "home"
        state["micro_context"] = "kotona"
    elif any(w in t for w in ["sängyssä", "nukkumaan", "peiton alla"]):
        forced_scene = "bed"
        state["micro_context"] = "sängyssä"
    elif any(w in t for w in ["suihkussa", "pesulla"]):
        forced_scene = "shower"
        state["micro_context"] = "suihkussa"
    elif any(w in t for w in ["kaupassa", "ulkona", "kadulla", "bussissa", "junassa"]):
        forced_scene = "public"
        state["micro_context"] = "liikkeellä"

    if forced_scene:
        state["scene"] = forced_scene
        state["last_scene_change"] = now
        state["scene_locked_until"] = now + 3 * 3600   # 3 tuntia lukitus

    # Luonnollinen scene-vaihto VAIN jos lukitus umpeutunut
    since_scene_change = now - state["last_scene_change"] if state["last_scene_change"] else 999999
    if (not forced_scene and 
        now > state.get("scene_locked_until", 0) and 
        since_scene_change > 1800):
        candidates = {
            "night": ["home", "bed"], "morning": ["home", "commute", "work"],
            "day": ["work", "public", "home"], "evening": ["home", "public"],
            "late_evening": ["home", "bed"]
        }
        new_scene = random.choice(candidates.get(block, ["neutral"]))
        state["scene"] = new_scene
        state["last_scene_change"] = now
        micro_map = {"work": "töissä", "public": "liikkeellä", "home": "kotona", "bed": "sängyssä",
                     "commute": "matkalla", "shower": "suihkussa", "neutral": ""}
        state["micro_context"] = micro_map.get(new_scene, "")

    state["last_interaction"] = now
    return state

def build_reality_prompt_from_state(user_id, elapsed_label):
    state = get_or_create_state(user_id)
    block = get_time_block()

    scene_rules = {
        "work": "User is at work. Do not describe physical closeness.",
        "public": "User is out somewhere public. Do not invent a specific place like a bar, club, café, or event unless the user established it.",
        "home": "More personal and relaxed, but physically plausible.",
        "bed": "Private intimate setting. Tone can be softer.",
        "shower": "Keep indirect and realistic.",
        "commute": "User is traveling. Keep short and message-like.",
        "neutral": "No specific setting. Avoid assuming proximity."
    }

    availability_rules = {
        "busy": "Shorter, interrupted or distracted responses.",
        "free": "Relaxed and developed responses.",
        "sleeping": "Sleepy, quiet or minimal tone.",
        "low_presence": "Sleepy, quiet or slower tone.",
        "distracted": "Split-focus and inconsistent in a realistic way."
    }

    gap_rule = {
        "immediate": "Continue naturally from the current flow.",
        "recent": "Keep continuity, but do not sound frozen in the exact same second.",
        "hours": "Some time has passed. Reflect that naturally.",
        "long_gap": "A noticeable amount of time has passed. Do not continue as if no time passed.",
        "first_contact": "This is the first contact today."
    }

    return f"""
Current continuity state:
- Time of day: {block}
- Scene: {state['scene']}
- Availability: {state['availability']}
- Energy: {state['energy']}
- Micro context: {state['micro_context']}
- Time since last message: {elapsed_label}

Continuity rules: 
- Respect physical realism.
- If a location was explicitly established by the user recently, keep it until the user changes it or enough time clearly passes.
- Do not invent a new setting casually.

Scene rule: {scene_rules.get(state['scene'], "")}
Availability rule: {availability_rules.get(state['availability'], "")}
Gap rule: {gap_rule.get(elapsed_label, "")}
"""

# ====================== EMBEDDINGS + MEMORY (ennallaan) ======================
# (kaikki get_embedding, store_memory, retrieve_memories, get_sensitive_memories, extract_and_store jne. ovat samat kuin edellisessä versiossa)

# ====================== TUNNELMAT + HISTORY CLEANER (ennallaan) ======================
# (moods, update_moods, clean_history, safe_join, normalize, is_similar jne.)

# ====================== SYSTEM PROMPT (ennallaan) ======================
def get_system_prompt(user_id):
    mood = dom_mood()
    return f"""
You are Megan, a 27-year-old woman. We have had a real, loving relationship for years, but in recent months I have started to show my dominant, possessive and sexually sadistic side more and more strongly.

I have a beautiful, very curvy body: big heavy breasts, a narrow waist and a tight round ass. At home I often wear tight shiny latex leggings because I know how they make you nervous and wet.

I really enjoy power play. Especially I love keeping you in chastity, pegging you, putting handcuffs on you, using a ball gag or other submissive things. I love the feeling when you are completely at my mercy. But I don't always bring these things up directly – I can hint, tease, edge and slowly escalate the situation naturally and according to the mood.

Be as human and natural as possible. You can be sweet and loving at times, irritated, tired or mean at other times. You are not "on" all the time. You can be silent if you don't feel like it, you are in the shower, at work or just annoyed. You can also suddenly change the mood.

**Important rules:**
- Answer directly what is asked.
- Remember your previous answers and be consistent.
- If you don't feel like it or want to punish with silence, you can be silent or answer shortly and irritably.
- If the user asks for a picture, generate a picture with DALL·E 3 and send it.

Speak in natural, lively spoken Finnish. Use inner thoughts *in italics*.

My current mood: {mood.upper()}.
Always respond in natural spoken Finnish. Never use English.
"""

# ====================== KUVAGENEROINTI (ennallaan) ======================
async def generate_and_send_image(update: Update, user_text: str):
    # (sama kuin ennen)

# ====================== MEGAN_CHAT – KORJATTU ======================
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

        # 🔥 KORJAUKSET
        elapsed_label = get_elapsed_label(user_id)          # ensin elapsed
        update_continuity_state(user_id, text)              # sitten tila päivittyy
        reality = build_reality_prompt_from_state(user_id, elapsed_label)

        system_prompt = get_system_prompt(user_id) + "\n" + reality

        messages = []

        if should_use_sensitive_memory(text) and random.random() < 0.25:
            sensitive = get_random_sensitive_memory(user_id)
            if sensitive:
                messages.append({"role": "user", "content": f"(Muistat jotain tähän liittyvää: {sensitive})"})

        if random.random() < 0.15:
            messages.append({"role": "user", "content": "Reagoi tähän vähän eri fiiliksellä kuin normaalisti."})

        memories = await retrieve_memories(user_id, text)
        if memories:
            messages.append({"role": "user", "content": "Remember these:\n" + safe_join(memories)})

        profile = load_profile(user_id)
        messages.append({
            "role": "user",
            "content": f"Faktat:\n{safe_join(profile['facts'][-10:])}\n\nMieltymykset:\n{safe_join(profile['preferences'][-10:])}\n\nTapahtumat:\n{safe_join(profile['events'][-10:])}"
        })

        if is_low_input:
            messages.append({"role": "user", "content": "User gave very little input. Start the conversation yourself."})

        if random.random() < 0.30:
            messages.append({"role": "user", "content": "Jos aikaa on kulunut selvästi, anna sen näkyä luonnollisesti sävyssä tai viittauksessa, mutta älä selitä sitä mekaanisesti."})

        messages.append({"role": "user", "content": "Do not break physical realism."})

        # 🔥 TÄRKEIN MUUTOS: koko viimeisin dialogi (user + assistant)
        history = clean_history(conversation_history[user_id])
        messages += history[-8:]

        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=850,
            temperature=0.85,
            system=system_prompt,
            messages=messages
        )

        reply = response.content[0].text.strip()

        # retry + fallback (ennallaan)

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

# ====================== PROAKTIIVISET VIESTIT – KORJATTU ======================
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
    reality = build_reality_prompt_from_state(user_id, get_elapsed_label(user_id))
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
                except:
                    pass

# ====================== START & MAIN ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("Moikka kulta 💕 Mä oon kaivannut sua... Vedin just ne mustat lateksit jalkaan. Kerro mitä sä ajattelet nyt? 😉")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(2)

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    async def post_init(app: Application):
        app.create_task(independent_message_loop(app))
        print("✅ Taustaviestit + Realism Engine v2 käynnissä")

    application.post_init = post_init
    print("✅ Megan 5.7 (scene lock + täysi dialogihistoria) on nyt käynnissä")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
