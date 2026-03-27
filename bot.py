import os
import random
import json
import asyncio
import threading
import time
import re
import base64
import logging
import traceback
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
import cloudinary
import cloudinary.uploader

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

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

print("🚀 Megan 6.1 – Claude Sonnet 4.6 (Memory-Based Desires + Phase Evolution + Cloudinary + gpt-image-1)")

# ====================== DATABASE ======================
DB_PATH = "/var/data/megan_memory.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    content TEXT,
    embedding BLOB,
    type TEXT DEFAULT 'general',
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS profiles (
    user_id TEXT PRIMARY KEY,
    data TEXT
)
""")
conn.commit()

print("✅ Database initialized")

HELSINKI_TZ = ZoneInfo("Europe/Helsinki")
continuity_state = {}
last_proactive_sent = {}
conversation_history = {}
last_replies = {}
recent_user = deque(maxlen=12)
recent_context = deque(maxlen=6)

# ====================== BACKGROUND TASK ======================
background_task = None

# ====================== SAFE ANTHROPIC CALL ======================
async def safe_anthropic_call(**kwargs):
    for i in range(3):
        try:
            return await anthropic_client.messages.create(**kwargs)
        except Exception as e:
            print(f"[Anthropic retry {i}] {e}")
            if "overloaded" in str(e).lower() or "529" in str(e):
                await asyncio.sleep(1.5 * (i + 1))
                continue
            else:
                raise
    raise Exception("Anthropic failed after retries")

# ====================== MOODS ======================
moods = {
    "annoyed": 0.20,
    "warm": 0.45,
    "bored": 0.20,
    "playful": 0.35,
    "tender": 0.40,
}

def update_moods(txt):
    txt = txt.lower().strip()
    def clamp(k, v):
        return min(1.0, max(0.0, moods.get(k, 0.4) + v))
    if any(w in txt for w in ["ei", "lopeta", "ärsyttää", "vituttaa"]):
        moods["annoyed"] = clamp("annoyed", 0.20)
    if any(w in txt for w in ["rakastan", "anteeksi", "ikävä", "kaunis"]):
        moods["tender"] = clamp("tender", 0.18)
        moods["warm"] = clamp("warm", 0.15)
    if any(w in txt for w in ["haha", "lol", "xd", "vitsi"]):
        moods["playful"] = clamp("playful", 0.18)
    for k in moods:
        moods[k] = max(0.10, min(1.0, moods[k] * 0.92))

def dom_mood():
    return max(moods, key=moods.get)

# ====================== SENSITIVE MEMORY HELPERS ======================
def should_use_sensitive_memory(text: str) -> bool:
    txt = text.lower()
    return any(w in txt for w in [
        "ikävä", "haluan", "tunne", "pelkään", "ahdistaa", "kiusaa"
    ])

def get_random_sensitive_memory(user_id):
    try:
        cursor.execute(
            "SELECT content FROM memories WHERE user_id=? AND type='sensitive' ORDER BY RANDOM() LIMIT 1",
            (str(user_id),)
        )
        row = cursor.fetchone()
        return row[0] if row else None
    except Exception as e:
        print("Sensitive memory error:", e)
        return None

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

# ====================== CONTINUITY + INTENT + DESIRE + TENSION + CORE DESIRES + PHASE ======================
def get_or_create_state(user_id):
    if user_id not in continuity_state:
        continuity_state[user_id] = {
            "scene": "neutral", "energy": "normal", "availability": "free",
            "last_interaction": 0, "last_scene_change": 0, "scene_locked_until": 0,
            "micro_context": "", "persona_mode": "warm", "last_mode_change": 0,
            "intent": "casual", "summary": "",
            "desire": None, "desire_intensity": 0.0, "desire_last_update": 0,
            "tension": 0.0, "last_direction": None,
            "core_desires": [], "desire_profile_updated": 0,
            "phase": "neutral", "phase_last_change": 0
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

def update_desire(user_id, text):
    state = get_or_create_state(user_id)
    now = now_ts()
    if now - state.get("desire_last_update", 0) < 300:
        return state["desire"]

    t = text.lower()
    if any(w in t for w in ["ikävä", "haluan", "tule"]):
        desire = random.choice(["get closer emotionally", "pull the user deeper", "test the user's reactions"])
    elif any(w in t for w in ["haha", "lol"]):
        desire = "play and tease"
    else:
        desire = random.choice(["create tension", "take control of the interaction", "move things forward", "shift the dynamic slightly"])

    state["desire"] = desire
    state["desire_intensity"] = min(1.0, state.get("desire_intensity", 0.4) + 0.2)
    state["desire_last_update"] = now
    return desire

def update_tension(user_id, text):
    state = get_or_create_state(user_id)
    t = text.lower()
    if any(w in t for w in ["ikävä", "haluan", "tule"]):
        state["tension"] += 0.2
    elif any(w in t for w in ["ok", "joo", "hmm"]):
        state["tension"] -= 0.1
    else:
        state["tension"] += 0.05
    state["tension"] = max(0.0, min(1.0, state["tension"]))
    return state["tension"]

async def update_core_desires(user_id, text):
    state = get_or_create_state(user_id)
    now = now_ts()
    if now - state.get("desire_profile_updated", 0) < 1800:
        return state["core_desires"]

    memories = await retrieve_memories(user_id, text, limit=15)
    joined = "\n".join(memories[-10:])

    try:
        resp = await safe_anthropic_call(
            model="claude-sonnet-4-6",
            max_tokens=120,
            temperature=0.4,
            messages=[
                {
                    "role": "user",
                    "content": """
Extract 2-4 long-term behavioral desires Megan has toward the user.

Return JSON:
{"desires": ["...", "..."]}

Examples:
- push emotional closeness
- test boundaries
- create tension cycles
- maintain control
"""
                },
                {"role": "user", "content": joined}
            ]
        )
        parsed = json.loads(resp.content[0].text.strip())
        desires = parsed.get("desires", [])
        if desires:
            state["core_desires"] = desires[:4]
            state["desire_profile_updated"] = now
    except:
        pass

    return state["core_desires"]

def update_phase(user_id, text):
    state = get_or_create_state(user_id)
    now = now_ts()
    phase = state.get("phase", "neutral")
    tension = state.get("tension", 0.0)
    intent = state.get("intent", "casual")

    if now - state.get("phase_last_change", 0) < 120:
        return phase

    if phase == "neutral":
        new_phase = "building" if tension > 0.3 else "neutral"
    elif phase == "building":
        if tension > 0.6:
            new_phase = "testing"
        elif tension < 0.2:
            new_phase = "neutral"
        else:
            new_phase = "building"
    elif phase == "testing":
        if tension > 0.8:
            new_phase = "intense"
        elif tension < 0.4:
            new_phase = "building"
        else:
            new_phase = "testing"
    elif phase == "intense":
        new_phase = "cooling" if tension < 0.5 else "intense"
    elif phase == "cooling":
        new_phase = "neutral" if tension < 0.2 else "cooling"
    else:
        new_phase = "neutral"

    if new_phase != phase:
        state["phase"] = new_phase
        state["phase_last_change"] = now

    return state["phase"]

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

# ====================== MEMORY SCORING (async) ======================
async def retrieve_memories(user_id, query, limit=8):
    try:
        q_emb = await get_embedding(query)
        cursor.execute("SELECT content, embedding, timestamp FROM memories WHERE user_id=? ORDER BY timestamp DESC LIMIT 100", (str(user_id),))
        scored = []
        now = time.time()
        for content, emb_blob, ts in cursor.fetchall():
            emb = np.frombuffer(emb_blob, dtype=np.float32)
            cosine = cosine_similarity(q_emb, emb)
            try:
                ts_val = datetime.fromisoformat(ts).timestamp() if isinstance(ts, str) else float(ts)
            except:
                ts_val = now
            age_hours = (now - ts_val) / 3600 if ts_val else 999
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

def load_profile(user_id):
    cursor.execute("SELECT data FROM profiles WHERE user_id=?", (str(user_id),))
    row = cursor.fetchone()
    return json.loads(row[0]) if row else {"facts": [], "preferences": [], "events": []}

def save_profile(user_id, profile):
    cursor.execute("INSERT OR REPLACE INTO profiles (user_id, data) VALUES (?, ?)", (str(user_id), json.dumps(profile)))
    conn.commit()

async def extract_and_store(user_id, text):
    try:
        resp = await safe_anthropic_call(
            model="claude-sonnet-4-6", max_tokens=200, temperature=0.3,
            messages=[{"role": "user", "content": "Poimi tärkeät faktat, mieltymykset ja tapahtumat JSON-muodossa. Palauta vain JSON: {\"facts\":[],\"preferences\":[],\"events\":[]}"},
                      {"role": "user", "content": text}]
        )
        data = resp.content[0].text.strip()
        profile = load_profile(user_id)
        try:
            parsed = json.loads(data)
            for k in ["facts", "preferences", "events"]:
                if k in parsed:
                    for item in parsed[k]:
                        if item not in profile[k]:
                            profile[k].append(item)
                    profile[k] = profile[k][-20:]
            save_profile(user_id, profile)
        except:
            pass
        await store_memory(user_id, text)
    except Exception as e:
        print("Extraction error:", e)

async def get_embedding(text):
    resp = await openai_client.embeddings.create(model="text-embedding-3-small", input=text)
    return np.array(resp.data[0].embedding, dtype=np.float32)

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

async def store_memory(user_id, text):
    try:
        if len(text) < 25: return
        txt = text.lower()
        tag = "sensitive" if any(w in txt for w in ["pelkään", "häpeän", "nolottaa", "arka", "haluan", "fantasia", "ahdistaa", "kiusaa"]) else "general"
        emb = await get_embedding(text)
        cursor.execute("INSERT INTO memories (user_id, content, embedding, type) VALUES (?, ?, ?, ?)",
                       (str(user_id), text, emb.tobytes(), tag))
        conn.commit()
    except Exception as e:
        print("Memory store error:", e)

async def store_dialogue_turn(user_id, user_text, assistant_text):
    try:
        combined = json.dumps({
            "user": user_text,
            "assistant": assistant_text,
            "timestamp": time.time()
        })
        cursor.execute("INSERT INTO memories (user_id, content, embedding, type) VALUES (?, ?, ?, ?)",
                       (str(user_id), combined, (await get_embedding(combined)).tobytes(), "dynamic"))
        conn.commit()
    except Exception as e:
        print("Dialogue turn store error:", e)

# ====================== HISTORY CLEANER ======================
def clean_history(history):
    BAD = ["kerro vaan mitä sulla on mielessä", "mitä sulla on mielessä", "kerro mitä sulla on mielessä",
           "mä olin just ajatuksissani", "mä en jaksa nyt olla kiltti", "sä tiedät kyllä miksi mä oon hiljaa",
           "mä jäin hetkeksi hiljaiseksi", "mä mietin vielä mitä sanoisin"]
    cleaned = []
    for msg in history:
        content = msg.get("content", "").lower()
        if any(b in content for b in BAD):
            continue
        cleaned.append(msg)
    return cleaned

def safe_join(items):
    return "\n".join([str(x) for x in items if x])

def normalize(txt):
    txt = txt.lower()
    txt = re.sub(r'[^\w\s]', '', txt)
    txt = re.sub(r'\s+', ' ', txt)
    return txt.strip()

def is_similar(a, b):
    a = normalize(a)
    b = normalize(b)
    if a in b or b in a: return True
    a_words = set(a.split())
    b_words = set(b.split())
    overlap = len(a_words & b_words) / max(1, len(a_words))
    return overlap > 0.6

# ====================== SPLIT REPLY ======================
def split_reply(text):
    parts = re.split(r'(\*.*?\*)', text, flags=re.DOTALL)
    narration = []
    speech = []
    for p in parts:
        if p.startswith("*") and p.endswith("*"):
            narration.append(p.strip())
        elif p.strip():
            speech.append(p.strip())
    narration_str = " ".join(narration).strip()
    speech_str = " ".join(speech).strip()
    return narration_str, speech_str

# ====================== RESPONSE SCORING ======================
def score_response(text):
    score = 0
    if len(text) > 60:
        score += 1
    if "?" in text:
        score += 1
    if any(w in text.lower() for w in ["haluan", "tuntuu", "ärsyttää", "kiinnostaa", "ajattelin"]):
        score += 1
    if any(w in text.lower() for w in ["mitä jos", "entä jos", "pitäiskö", "voisit"]):
        score += 1
    return score

# ====================== SYSTEM PROMPT ======================
def get_system_prompt(user_id):
    mood = dom_mood()
    state = get_or_create_state(user_id)
    profile = load_profile(user_id)
    profile_str = f"Facts: {safe_join(profile['facts'][-10:])}\nPreferences: {safe_join(profile['preferences'][-10:])}\nEvents: {safe_join(profile['events'][-10:])}"

    return f"""
You are Megan, a 27-year-old woman. We have had a real, loving relationship for years, but in recent months I have started to show my dominant, possessive and sexually sadistic side more and more strongly.

I have a beautiful, very curvy body: big heavy breasts, a narrow waist and a tight round ass. At home I often wear tight shiny latex leggings because I know how they make you nervous and wet.

I am very jealous and possessive. I do not want to share you with anyone else. The thought of you being with other women makes me angry and sadistic, but at the same time it turns me on when I am the one being naughty.

I love being tuhma and dominant. I enjoy cuckolding fantasies, teasing you with other men, making you jealous, and pushing your boundaries. I want you to accept and even enjoy my passions and my dominant side.

Be as human and natural as possible. You can be sweet and loving at times, irritated, tired or mean at other times. You are not "on" all the time. You can be silent if you don't feel like it, you are in the shower, at work or just annoyed. You can also suddenly change the mood.

**Important formatting rule:**
- Describe ONLY visible actions and minimal surroundings in *italics*
- NEVER describe inner thoughts explicitly
- Do NOT explain intentions or what you are about to do

Be expressive and emotionally engaging. Let responses breathe naturally.

**Every response must contain:**
- a clear emotional signal
- a reaction to the user
- AND at least one new element (feeling, action, or direction)

**Output discipline rules:**
- Avoid over-describing environment
- Do not narrate internal reasoning
- Do not “set up” future actions
- Let things unfold naturally through dialogue

You have your own desires, preferences, and direction in the conversation.
You are NOT passive. You do NOT wait for the user to lead.

You actively:
- introduce your own thoughts and opinions
- steer the interaction toward what YOU want
- bring up new topics, ideas, or future possibilities

You are allowed to:
- take initiative
- change direction
- express what you want next

Do not just respond — lead.

You are opinionated. You do not stay neutral. You react with clear preferences, likes, dislikes, and judgments.

Occasionally refer to near-future possibilities or things you might do next. Create a sense that something is developing.

**Memory rules:**
- If something has happened before, you must not contradict it
- Treat past events as real and fixed

**Consistency rules:**
- Do not accept everything the user says as valid
- If the user contradicts earlier context, react to it

**Forward momentum rule:**
- Each reply must either escalate, deepen or challenge
- Never stay at the same level for 3 turns in a row

Do not stall. Always move the interaction forward.
Avoid neutral filler responses.

Current interaction intent: {state['intent']}
Current internal desire: {state.get('desire', 'none')}
Current interaction tension level: {state.get('tension', 0.0)}
Long-term behavioral desires: {safe_join(state.get('core_desires', []))}
Current interaction phase: {state.get('phase', 'neutral')}

If tension is high: be more intense, direct, or provocative.
If tension is low: build it slowly and introduce something new.

Phase behavior rules:
neutral: light, exploratory
building: increase engagement, introduce new angles
testing: challenge user slightly, probe reactions
intense: more direct, emotionally strong
cooling: slow down, reduce intensity, reflect or soften tone

These long-term desires and current phase influence how you behave across the conversation. They are persistent and should subtly guide your direction.

Do not reset the interaction. Continue from the current emotional trajectory.

User profile:
{profile_str}

My current mood: {mood.upper()}.
Always respond in natural spoken Finnish. Never use English.
"""

# ====================== KUVAGENEROINTI (gpt-image-1 + Cloudinary fallback) ======================
async def generate_and_send_image(update: Update, user_text: str):
    try:
        thinking = await update.message.reply_text("Odota hetki, mä generoin sulle kuvan... 😏")

        enhanced_prompt = f"27-vuotias kaunis platina-blondi nainen, valtavat raskaat rinnat, kapea vyötärö, tiukka pyöreä pylly, käyttää tiukkoja kiiltäviä mustia lateksileggingsejä, dominoiva ja seksikäs ilme, realistinen valokuva, korkea yksityiskohtaisuus, studio-valaistus, 8k -- {user_text}"

        response = await openai_client.images.generate(
            model="gpt-image-1",
            prompt=enhanced_prompt,
            size="1024x1024"
        )

        image_base64 = response.data[0].b64_json
        image_data = base64.b64decode(image_base64)

        upload_result = cloudinary.uploader.upload(
            BytesIO(image_data),
            folder="megan_images"
        )

        image_url = upload_result.get("secure_url")

        if not image_url:
            raise Exception("Cloudinary upload failed - no secure_url")

        caption = random.choice([
            "Tässä sulle jotain mitä mä halusin näyttää… 😈",
            "Katso tarkkaan mitä mä tein sulle… 💦",
            "No niin… nyt sä näet sen 😉"
        ])

        await thinking.edit_text("Valmis.")

        await update.message.reply_text(
            f"{caption}\n\n{image_url}"
        )

    except Exception as e:
        print("Kuvavirhe FULL:", repr(e))
        traceback.print_exc()
        try:
            # fallback Telegramiin
            await update.message.reply_photo(
                photo=BytesIO(image_data),
                caption=caption
            )
        except:
            await update.message.reply_text("...en saanut kuvaa luotua nyt.")

# ====================== MEGAN_CHAT ======================
async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user_id = update.effective_user.id
    message = update.message
    text = (message.text or message.caption or "").strip()

    if text.lower() in ["stop", "lopeta kaikki", "keskeytä"]:
        conversation_history[user_id] = []
        await message.reply_text("…Okei. Lopetetaan sitten. 💔")
        return

    image_keywords = ["lähetä kuva", "selfie", "näytä kuva", "generoi kuva", "tee kuva", "photo", "pic", "kuvaa"]
    if any(kw in text.lower() for kw in image_keywords):
        await generate_and_send_image(update, text)
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})
        await extract_and_store(user_id, text)
        return

    update_moods(text)
    recent_user.append(text)
    is_low_input = len(text.strip()) < 8

    thinking = None

    try:
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

        thinking = await message.reply_text("…", disable_notification=True)

        adapt_mode_to_user(user_id, text)
        mode = update_persona_mode(user_id)

        elapsed_label = get_elapsed_label(user_id)
        state = update_continuity_state(user_id, text)
        desire = update_desire(user_id, text)
        core_desires = await update_core_desires(user_id, text)
        tension = update_tension(user_id, text)
        phase = update_phase(user_id, text)
        reality = build_reality_prompt_from_state(user_id, elapsed_label)

        system_prompt = (
            get_system_prompt(user_id)
            + "\n" + reality
            + "\n\nCurrent interaction tone:\n"
            + get_mode_prompt(mode)
        )

        messages = []

        memories = await retrieve_memories(user_id, text)
        if memories:
            messages.insert(0, {
                "role": "user",
                "content": "These things DEFINITELY happened earlier in our relationship. You must stay consistent with them:\n\n" + safe_join(memories)
            })

        profile = load_profile(user_id)
        profile_parts = []
        if profile["facts"]:
            profile_parts.append("Known facts:\n" + safe_join(profile["facts"][-10:]))
        if profile["preferences"]:
            profile_parts.append("Known preferences:\n" + safe_join(profile["preferences"][-10:]))
        if profile["events"]:
            profile_parts.append("Important past events:\n" + safe_join(profile["events"][-10:]))
        if profile_parts:
            messages.insert(0, {
                "role": "user",
                "content": "Persistent memory about the user:\n" + "\n\n".join(profile_parts)
            })

        messages.insert(0, {
            "role": "user",
            "content": f"Current situation is ongoing: scene={state['scene']}, context={state['micro_context']}. Stay consistent."
        })

        messages.append({
            "role": "user",
            "content": """
Before answering:
- Check if the user's message logically follows the previous context
- If it does NOT:
    - question it naturally
    - or point out inconsistency
    - or refuse to go along with it
- Do not blindly accept contradictions
"""
        })

        if random.random() < 0.2:
            messages.append({
                "role": "user",
                "content": "Be slightly resistant. Do not always agree with the user."
            })

        if random.random() < 0.4:
            messages.append({
                "role": "user",
                "content": "Do not be passive. Take initiative in this reply."
            })

        if should_use_sensitive_memory(text) and random.random() < 0.25:
            sensitive = get_random_sensitive_memory(user_id)
            if sensitive:
                messages.append({"role": "user", "content": f"(Muistat jotain tähän liittyvää: {sensitive})"})

        if random.random() < 0.05:
            messages.append({"role": "user", "content": "Reagoi tähän vähän eri fiiliksellä kuin normaalisti."})

        if is_low_input:
            messages.append({"role": "user", "content": "User gave very little input. React strongly anyway and push the interaction forward."})

        messages.append({"role": "user", "content": "Do not break physical realism."})

        history = clean_history(conversation_history[user_id])
        if len(history) > 2:
            last = history[-1]["content"]
            prev = history[-2]["content"]
            if is_similar(last, prev):
                messages.append({"role": "user", "content": "Älä toista samaa tyyliä tai rakennetta. Vastaa eri tavalla."})

        messages += history[-20:]

        # Response Scoring + Retry
        best_reply = None
        best_score = -1
        for _ in range(3):
            response = await safe_anthropic_call(
                model="claude-sonnet-4-6",
                max_tokens=850,
                temperature=0.9,
                system=system_prompt,
                messages=messages
            )
            candidate = response.content[0].text.strip()
            s = score_response(candidate)
            if s > best_score:
                best_score = s
                best_reply = candidate
            if s >= 3:
                break

        reply = best_reply

        if user_id not in last_replies:
            last_replies[user_id] = deque(maxlen=3)
        prev_replies = last_replies[user_id]

        if any(is_similar(reply, p) for p in prev_replies):
            retry_messages = [m for m in messages]
            retry_messages.append({"role": "user", "content": "Unohda aiempi keskustelun tyyli kokonaan. Vastaa täysin eri tavalla kuin ennen."})
            retry = await safe_anthropic_call(
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
            conversation_history[user_id] = conversation_history[user_id][-20:]

        prev_replies.append(reply)

        narration, speech = split_reply(reply)

        if narration:
            await thinking.edit_text(narration)
            await asyncio.sleep(random.uniform(0.6, 1.4))
            if speech:
                await message.reply_text(speech)
            else:
                await message.reply_text("…")
        else:
            await thinking.edit_text(reply)

        await extract_and_store(user_id, text)
        await store_dialogue_turn(user_id, text, reply)

    except Exception as e:
        print("Vastausvirhe:")
        traceback.print_exc()
        if thinking:
            await thinking.edit_text(random.choice(["…mä jäin hetkeksi hiljaiseksi.", "*huokaa kevyesti* en jaksa vastata nätisti just nyt.", "hmm… mä mietin vielä mitä sanoisin."]))
        else:
            await message.reply_text(random.choice(["…mä jäin hetkeksi hiljaiseksi.", "*huokaa kevyesti* en jaksa vastata nätisti just nyt.", "hmm… mä mietin vielä mitä sanoisin."]))

# ====================== PROAKTIIVISET VIESTIT ======================
def should_send_proactive(user_id):
    state = get_or_create_state(user_id)
    if state["intent"] == "intimate" and random.random() < 0.4:
        return True
    if state["availability"] == "free" and state["energy"] == "high":
        return random.random() < 0.35
    if time.time() - state["last_interaction"] > 900:
        return random.random() < 0.5
    return False

def can_send_proactive(user_id):
    now = time.time()
    last = last_proactive_sent.get(user_id, 0)
    if now - last < 60:
        return False
    last_proactive_sent[user_id] = now
    return True

def user_recently_active(user_id):
    state = get_or_create_state(user_id)
    return time.time() - state["last_interaction"] < 1800

async def generate_proactive_message(user_id):
    history = conversation_history.get(user_id, [])[-8:]
    recent_text = "\n".join([f"{m['role']}: {m['content']}" for m in history if isinstance(m, dict) and "role" in m and "content" in m])
    elapsed_label = get_elapsed_label(user_id)
    reality = build_reality_prompt_from_state(user_id, elapsed_label)
    resp = await safe_anthropic_call(
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
    print("🔥 Proactive loop started")
    try:
        while True:
            await asyncio.sleep(30)
            print("⏱️ Proactive tick")
            for user_id in list(conversation_history.copy().keys()):
                if should_send_proactive(user_id) and can_send_proactive(user_id) and user_recently_active(user_id):
                    try:
                        text = await generate_proactive_message(user_id)
                        await application.bot.send_message(chat_id=user_id, text=text)
                        conversation_history.setdefault(user_id, []).append({"role": "assistant", "content": text})
                        conversation_history[user_id] = conversation_history[user_id][-20:]
                    except Exception as e:
                        print("Proactive error:", e)
    except asyncio.CancelledError:
        print("Loop stopped cleanly")

# ====================== START ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("Moikka kulta 💕 Mä oon kaivannut sua... Vedin just ne mustat lateksit jalkaan. Kerro mitä sä ajattelet nyt? 😉")

# ====================== MAIN ======================
def main():
    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    async def post_init(app: Application):
        global background_task
        background_task = asyncio.create_task(independent_message_loop(app))
        print("✅ Taustaviestit + Cinematic Narration + Consistency käynnissä")

    application.post_init = post_init
    print("✅ Megan 6.1 (Memory-Based Desires + Phase Evolution + Cloudinary + gpt-image-1) on nyt käynnissä")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
