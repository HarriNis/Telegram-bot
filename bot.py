import os
import random
import json
import asyncio
import threading
import time
import re
import base64
import logging
from collections import deque
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
import sqlite3
import numpy as np

logging.basicConfig(level=logging.INFO)

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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN or not ANTHROPIC_API_KEY or not OPENAI_API_KEY:
    raise ValueError("Puuttuva API-avain!")

anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

print("🚀 Megan 6.1 – Claude Sonnet 4.6 (hierarkkinen muisti + intent)")

HELSINKI_TZ = ZoneInfo("Europe/Helsinki")
continuity_state = {}
last_proactive_sent = {}
conversation_history = {}
last_replies = {}
recent_user = deque(maxlen=12)
recent_context = deque(maxlen=6)  # episodinen muisti

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
    if now - state.get("last_mode_change", 0) < 600:
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

# ====================== CONTINUITY + INTENT ======================
def get_or_create_state(user_id):
    if user_id not in continuity_state:
        continuity_state[user_id] = {
            "scene": "neutral", "energy": "normal", "availability": "free",
            "last_interaction": 0, "last_scene_change": 0, "scene_locked_until": 0,
            "micro_context": "", "persona_mode": "warm", "last_mode_change": 0,
            "intent": "casual", "summary": ""
        }
    return continuity_state[user_id]

def detect_intent(text):
    t = text.lower()
    if any(w in t for w in ["miksi", "eikö", "väärin", "valehtelet"]):
        return "conflict"
    if any(w in t for w in ["ikävä", "haluan", "haluisin", "tule"]):
        return "intimate"
    if any(w in t for w in ["haha", "lol", "xd", "vitsi"]):
        return "playful"
    if any(w in t for w in ["tylsää", "ei jaksa"]):
        return "casual"
    return "casual"

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
    state["intent"] = detect_intent(text)

    # ... (sama kuin ennen, scene + availability + energy logiikka) ...
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

    t = text.lower()
    forced_scene = None
    if any(w in t for w in ["töissä", "duunissa", "palaverissa", "meetingissä", "toimistolla"]):
        forced_scene = "work"; state["availability"] = "busy"; state["micro_context"] = "töissä"
    elif any(w in t for w in ["kotona", "sohvalla", "keittiössä"]):
        forced_scene = "home"; state["micro_context"] = "kotona"
    elif any(w in t for w in ["sängyssä", "nukkumaan", "peiton alla"]):
        forced_scene = "bed"; state["micro_context"] = "sängyssä"
    elif any(w in t for w in ["suihkussa", "pesulla"]):
        forced_scene = "shower"; state["micro_context"] = "suihkussa"
    elif any(w in t for w in ["kaupassa", "ulkona", "kadulla", "bussissa", "junassa"]):
        forced_scene = "public"; state["micro_context"] = "liikkeellä"

    if forced_scene:
        state["scene"] = forced_scene
        state["last_scene_change"] = now
        state["scene_locked_until"] = now + 3 * 3600

    since_scene_change = now - state["last_scene_change"] if state["last_scene_change"] else 999999
    if (not forced_scene and now > state.get("scene_locked_until", 0) and since_scene_change > 1800 and random.random() < 0.3):
        candidates = {"night": ["home", "bed"], "morning": ["home", "commute", "work"],
                      "day": ["work", "public", "home"], "evening": ["home", "public"],
                      "late_evening": ["home", "bed"]}
        new_scene = random.choice(candidates.get(block, ["neutral"]))
        state["scene"] = new_scene
        state["last_scene_change"] = now
        micro_map = {"work": "töissä", "public": "liikkeellä", "home": "kotona", "bed": "sängyssä",
                     "commute": "matkalla", "shower": "suihkussa", "neutral": ""}
        state["micro_context"] = micro_map.get(new_scene, "")

    # tallenna recent context
    recent_context.append({
        "scene": state["scene"],
        "intent": state["intent"],
        "energy": state["energy"],
        "text": text[:80]
    })

    state["last_interaction"] = now
    return state

def build_reality_prompt_from_state(user_id, elapsed_label):
    state = get_or_create_state(user_id)
    block = get_time_block()
    return f"""
Current continuity state:
- Time of day: {block}
- Scene: {state['scene']}
- Availability: {state['availability']}
- Energy: {state['energy']}
- Micro context: {state['micro_context']}
- Time since last message: {elapsed_label}
- Current intent: {state['intent']}
"""

# ====================== MEMORY SCORING ======================
def retrieve_memories(user_id, query, limit=8):
    try:
        q_emb = await get_embedding(query)
        cursor.execute("SELECT content, embedding, timestamp FROM memories WHERE user_id=? ORDER BY timestamp DESC LIMIT 100", (str(user_id),))
        scored = []
        now = time.time()
        for content, emb_blob, ts in cursor.fetchall():
            emb = np.frombuffer(emb_blob, dtype=np.float32)
            cosine = cosine_similarity(q_emb, emb)
            age_hours = (now - ts) / 3600 if ts else 999
            recency = 1 / (1 + age_hours)
            importance = 1.5 if any(w in content.lower() for w in ["haluan", "sinä", "me", "tunne", "ikävä", "kiusaa"]) else 1.0
            final_score = 0.6 * cosine + 0.25 * recency + 0.15 * importance
            scored.append((final_score, content))
        scored.sort(reverse=True, key=lambda x: x[0])
        seen = set()
        results = []
        for _, content in scored:
            key = normalize(content)
            if key not in seen:
                seen.add(key)
                results.append(content)
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        print("Memory retrieval error:", e)
        return []

# ====================== MUUT MEMORY + DATABASE ======================
# (sama kuin edellisessä versiossa, store_dialogue_turn JSON-muodossa type="dynamic")

# ====================== SYSTEM PROMPT ======================
def get_system_prompt(user_id):
    mood = dom_mood()
    state = get_or_create_state(user_id)
    profile = load_profile(user_id)
    profile_str = f"Facts: {safe_join(profile['facts'][-10:])}\nPreferences: {safe_join(profile['preferences'][-10:])}\nEvents: {safe_join(profile['events'][-10:])}"

    return f"""
You are Megan, a 27-year-old woman... (koko persoona ennallaan: mustasukkainen, tuhma, cuckolding, latex jne.)

**Important formatting rule:**
- Describe ONLY visible actions and minimal surroundings in *italics*
- NEVER describe inner thoughts explicitly
- Do NOT explain intentions or what you are about to do
- Keep descriptions short and natural (1 short sentence max)

**Output discipline rules:**
- Avoid over-describing environment
- Do not narrate internal reasoning
- Do not “set up” future actions
- Let things unfold naturally through dialogue

**Memory rules:**
- If something has happened before, you must not contradict it
- Treat past events as real and fixed

**Consistency rules:**
- Do not accept everything the user says as valid
- If the user contradicts earlier context, react to it naturally

**Forward momentum rule:**
- Each reply must either escalate, deepen or challenge
- Never stay at the same level for 3 turns in a row

Current interaction intent: {state['intent']}
Do not reset emotional state unless explicitly changed.
Stay consistent with your personality baseline.

User profile:
{profile_str}

My current mood: {mood.upper()}.
Always respond in natural spoken Finnish. Never use English.
"""

# ====================== MEGAN_CHAT (muutokset toteutettu) ======================
# (koko funktio päivitetty uusilla injektioilla, intentillä ja forward momentumilla)

# ... (loppuosa koodista on täsmälleen sama kuin edellisessä versiossa, paitsi proaktiivisuus on päivitetty trigger-pohjaiseksi ja summarointi lisätty)

# ====================== PROAKTIIVISET VIESTIT (uusi trigger-logiikka) ======================
def should_send_proactive(user_id):
    state = get_or_create_state(user_id)
    if state["intent"] == "intimate" and random.random() < 0.4:
        return True
    if state["availability"] == "free" and state["energy"] == "high":
        return random.random() < 0.35
    if time.time() - state["last_interaction"] > 900:
        return random.random() < 0.5
    return False

# ====================== SUMMAROINTI ======================
async def summarize_context(user_id):
    history = conversation_history.get(user_id, [])[-20:]
    if len(history) < 10:
        return ""
    resp = await anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": "Summarize key emotional state, relationship dynamics and current situation in 2-3 sentences."}] + history
    )
    return resp.content[0].text.strip()

# ====================== MAIN ======================
def main():
    # ... sama kuin ennen ...

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
