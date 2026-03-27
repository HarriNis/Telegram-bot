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
XAI_API_KEY = os.getenv("XAI_API_KEY")
VENICE_API_KEY = os.getenv("VENICE_API_KEY")

if not TELEGRAM_TOKEN or not ANTHROPIC_API_KEY or not OPENAI_API_KEY or not VENICE_API_KEY:
    raise ValueError("Puuttuva API-avain!")

anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

grok_client = AsyncOpenAI(
    api_key=XAI_API_KEY,
    base_url="https://api.x.ai/v1"
)

venice_client = AsyncOpenAI(
    api_key=VENICE_API_KEY,
    base_url="https://api.venice.ai/v1"
)

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

print("🚀 Megan 6.1 – Claude Sonnet 4.6 (Venice.ai ensisijainen kuvagenerointi + täysi kuvamuisti)")

# ====================== SCENE ENGINE (Temporal Layer) ======================
SCENE_TRANSITIONS = {
    "neutral": ["home", "work", "public"],
    "work": ["commute", "public"],
    "commute": ["home", "public"],
    "home": ["public", "bed", "shower"],
    "bed": ["home"],
    "shower": ["home"],
    "public": ["home", "work", "commute"],
}

SCENE_MICRO = {
    "work": ["töissä", "palaverissa", "naputtelee konetta"],
    "commute": ["kotimatkalla", "bussissa", "matkalla"],
    "home": ["kotona", "sohvalla", "keittiössä"],
    "bed": ["sängyssä", "peiton alla"],
    "shower": ["suihkussa"],
    "public": ["kaupassa", "ulkona", "liikkeellä"],
    "neutral": [""]
}

SCENE_ACTIONS = {
    "work": ["palaverissa", "keskittyy töihin"],
    "home": ["makaa sohvalla", "katsoo sarjaa"],
    "public": ["kävelee", "ostoksilla"],
    "bed": ["makaa sängyssä"],
}

MIN_SCENE_DURATION = 900
ACTION_MIN = 300
ACTION_MAX = 1800

def init_scene_state():
    return {
        "scene": "neutral",
        "micro_context": "",
        "current_action": None,
        "action_end": 0,
        "action_started": 0,
        "action_duration": 0,
        "last_scene_change": 0,
        "scene_locked_until": 0,
    }

def force_scene_from_text(state, text, now):
    t = text.lower()
    mapping = {
        "work": ["töissä", "duunissa", "palaverissa", "toimistolla"],
        "commute": ["bussissa", "junassa", "matkalla", "kotimatkalla"],
        "home": ["kotona", "sohvalla", "keittiössä"],
        "bed": ["sängyssä", "peiton alla"],
        "shower": ["suihkussa"],
        "public": ["kaupassa", "ulkona", "liikkeellä"],
    }
    for scene, keywords in mapping.items():
        if any(w in t for w in keywords):
            _set_scene(state, scene, now)
            state["micro_context"] = random.choice(SCENE_MICRO[scene])
            return True
    return False

def maybe_transition_scene(state, now):
    if now - state["last_scene_change"] < MIN_SCENE_DURATION:
        return state["scene"]
    if now < state["scene_locked_until"]:
        return state["scene"]
    current = state["scene"]
    allowed = SCENE_TRANSITIONS.get(current, [])
    if not allowed:
        return current
    if random.random() < 0.2:
        new_scene = random.choice(allowed)
        _set_scene(state, new_scene, now)
        state["micro_context"] = random.choice(SCENE_MICRO[new_scene])
    return state["scene"]

def update_action(state, now):
    if state["current_action"] and now < state["action_end"]:
        return
    scene = state["scene"]
    if scene in SCENE_ACTIONS and random.random() < 0.4:
        action = random.choice(SCENE_ACTIONS[scene])
        duration = random.randint(ACTION_MIN, ACTION_MAX)
        state["current_action"] = action
        state["action_started"] = now
        state["action_duration"] = duration
        state["action_end"] = now + duration

def _set_scene(state, scene, now):
    state["scene"] = scene
    state["last_scene_change"] = now
    state["scene_locked_until"] = now + MIN_SCENE_DURATION
    state["current_action"] = None
    state["action_started"] = 0
    state["action_duration"] = 0

def get_action_progress(state, now):
    if not state["current_action"]:
        return None
    elapsed = now - state["action_started"]
    total = state["action_duration"]
    if total <= 0:
        return "starting"
    ratio = elapsed / total
    if ratio < 0.25:
        return "starting"
    elif ratio < 0.75:
        return "ongoing"
    elif ratio < 1.0:
        return "ending"
    else:
        return "finished"

def build_temporal_context(state):
    now = time.time()
    progress = get_action_progress(state, now)
    if not state["current_action"]:
        return "No ongoing action."
    return f"""
Temporal state:
- Current action: {state['current_action']}
- Action phase: {progress}
- Started: {int(now - state['action_started'])} seconds ago
- Expected duration: {state['action_duration']} seconds

The action is ongoing and MUST be reflected naturally.
"""

def maybe_interrupt_action(state, text):
    t = text.lower()
    if any(w in t for w in ["tule", "tee", "nyt", "heti"]):
        if state["current_action"]:
            state["current_action"] = None
            state["action_end"] = 0
            state["action_duration"] = 0
            state["action_started"] = 0

def breaks_scene_logic(reply, state):
    return False

def breaks_temporal_logic(reply, state):
    if not state["current_action"]:
        return False
    r = reply.lower()
    action = state["current_action"]
    if action == "makaa sohvalla" and any(w in r for w in ["juoksen", "kävelen", "olen ulkona", "töissä"]):
        return True
    return False

def reinforce_micro_context(state):
    return None

def get_recent_actions(user_id):
    return "No recent actions."

# ====================== DATABASE + LOCK ======================
DB_PATH = "/var/data/megan_memory.db"
db_lock = threading.Lock()
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

# ====================== WORKING MEMORY ======================
working_memory = {}

# ====================== PERSONA BASELINE & DRIFT CONTROL ======================
PERSONA_BASELINE = {
    "dominance": 0.7,
    "warmth": 0.5,
    "playfulness": 0.4
}

PERSONALITY_LIMITS = {
    "curiosity": (0.2, 0.9),
    "patience": (0.2, 0.9),
    "expressiveness": (0.2, 0.9),
    "initiative": (0.2, 0.9),
    "stability": (0.3, 1.0),
}

# ====================== DEFAULT SIDE CHARACTERS ======================
DEFAULT_SIDE_CHARACTERS = {
    "friend": {
        "name": "Aino",
        "role": "friend",
        "tone": "warm and casual",
        "description": "A relaxed friend occasionally mentioned in everyday context."
    },
    "coworker": {
        "name": "Mika",
        "role": "coworker",
        "tone": "professional but friendly",
        "description": "A coworker related to work or scheduling topics."
    }
}

# ====================== RESET HELPERS ======================
async def new_game_reset(user_id):
    conversation_history[user_id] = []
    last_replies[user_id] = deque(maxlen=3)
    working_memory[user_id] = {}

    if user_id in continuity_state:
        del continuity_state[user_id]

    if user_id in last_proactive_sent:
        del last_proactive_sent[user_id]

    print(f"[NEW GAME] Reset session state for user {user_id}")


async def wipe_all_memory(user_id):
    await new_game_reset(user_id)

    with db_lock:
        cursor.execute("DELETE FROM memories WHERE user_id=?", (str(user_id),))
        cursor.execute("DELETE FROM profiles WHERE user_id=?", (str(user_id),))
        conn.commit()

    print(f"[WIPE MEMORY] Fully wiped all memory for user {user_id}")


# ====================== STATE SNAPSHOT ======================
def build_state_snapshot(user_id):
    state = get_or_create_state(user_id)
    return {
        "scene": state["scene"],
        "action": state.get("current_action"),
        "intent": state["intent"],
        "tension": state["tension"],
        "phase": state["phase"],
        "persona_mode": state["persona_mode"],
        "desire": state.get("desire"),
        "micro_context": state.get("micro_context"),
    }

# ====================== MEMORY CONTEXT BUILDER ======================
def build_memory_context(memories):
    structured = []
    for m in memories:
        try:
            parsed = json.loads(m)

            if parsed.get("type") == "image_sent":
                structured.append(
                    f"- Aiemmin lähetit käyttäjälle kuvan "
                    f"(pyyntö: {parsed.get('user_request')})"
                )
                continue

            structured.append(
                f"- Aiemmin: {parsed.get('user')} → {parsed.get('assistant')} "
                f"(intent: {parsed.get('intent')}, phase: {parsed.get('state', {}).get('phase')})"
            )
        except:
            structured.append(f"- {m}")
    return "\n".join(structured[:6])

# ====================== MEMORY ENGINE V3 HELPERS ======================
def is_noise(content):
    txt = content.lower()
    if len(txt) < 20:
        return True
    if any(x in txt for x in ["ok", "joo", "hmm"]):
        return True
    return False

def stabilize_persona(user_id):
    state = get_or_create_state(user_id)
    if "persona_vector" not in state:
        state["persona_vector"] = PERSONA_BASELINE.copy()
    vec = state["persona_vector"]
    for k in vec:
        baseline = PERSONA_BASELINE[k]
        drift = vec[k] - baseline
        if abs(drift) > 0.25:
            vec[k] = baseline + drift * 0.5
    return vec

async def update_arcs(user_id, text):
    state = get_or_create_state(user_id)
    now = time.time()
    if now - state.get("arc_last_update", 0) < 600:
        return
    memories = await retrieve_memories(user_id, text, limit=20)
    joined = "\n".join(memories[-10:])
    try:
        resp = await safe_anthropic_call(
            model="claude-sonnet-4-6",
            max_tokens=120,
            temperature=0.4,
            messages=[
                {"role": "user", "content": "Extract 1-3 relationship arcs. JSON: {\"arcs\": [\"...\"]}. Examples: emotional push-pull, dominance escalation, trust testing"},
                {"role": "user", "content": joined}
            ]
        )
        parsed = json.loads(resp.content[0].text.strip())
        arcs = parsed.get("arcs", [])
        if arcs:
            state["relationship_arcs"] = arcs
            state["active_arc"] = arcs[0]
            state["arc_last_update"] = now
    except:
        pass

async def update_goal(user_id, text):
    state = get_or_create_state(user_id)
    now = time.time()
    if now - state.get("goal_updated", 0) < 300:
        return state.get("current_goal")
    try:
        resp = await safe_anthropic_call(
            model="claude-sonnet-4-6",
            max_tokens=60,
            temperature=0.5,
            messages=[
                {"role": "user", "content": "Define immediate conversational goal in 1 sentence. Example: increase tension, deepen emotional bond, test reaction"},
                {"role": "user", "content": text}
            ]
        )
        goal = resp.content[0].text.strip()
        state["current_goal"] = goal
        state["goal_updated"] = now
    except:
        pass
    return state.get("current_goal")

def update_emotion(user_id, text):
    state = get_or_create_state(user_id)
    if "emotional_state" not in state:
        state["emotional_state"] = {"valence": 0.0, "arousal": 0.5, "attachment": 0.5}
    emo = state["emotional_state"]
    t = text.lower()
    if "ikävä" in t:
        emo["attachment"] += 0.1
        emo["valence"] += 0.05
    if "ärsyttää" in t:
        emo["valence"] -= 0.2
    if "haluan" in t:
        emo["arousal"] += 0.15
    for k in emo:
        emo[k] = max(0.0, min(1.0, emo[k]))
    return emo

def evolve_personality(user_id, text):
    state = get_or_create_state(user_id)
    if "personality_evolution" not in state:
        state["personality_evolution"] = {
            "curiosity": 0.5, "patience": 0.5, "expressiveness": 0.5,
            "initiative": 0.5, "stability": 0.7, "last_evolved": 0
        }
    evo = state["personality_evolution"]
    now = time.time()
    if now - evo.get("last_evolved", 0) < 300:
        return evo
    t = text.lower()
    if any(w in t for w in ["miksi", "miten", "entä", "?"]):
        evo["curiosity"] = min(1.0, evo["curiosity"] + 0.03)
    if any(w in t for w in ["odota", "hetki", "ei nyt", "lopeta"]):
        evo["patience"] = min(1.0, evo["patience"] + 0.02)
        evo["initiative"] = max(0.0, evo["initiative"] - 0.02)
    if any(w in t for w in ["haha", "lol", "xd", "vitsi"]):
        evo["expressiveness"] = min(1.0, evo["expressiveness"] + 0.03)
    if len(text.strip()) < 8:
        evo["initiative"] = min(1.0, evo["initiative"] + 0.02)
    evo["stability"] = min(1.0, max(0.3, evo["stability"] * 0.995))
    evo["last_evolved"] = now
    return evo

def clamp_personality_evolution(user_id):
    state = get_or_create_state(user_id)
    evo = state["personality_evolution"]
    for k, (low, high) in PERSONALITY_LIMITS.items():
        evo[k] = min(high, max(low, evo[k]))
    return evo

def detect_side_character_trigger(text):
    t = text.lower()
    if any(w in t for w in ["kaveri", "ystävä", "aino"]):
        return "friend"
    if any(w in t for w in ["duuni", "työkaveri", "mika", "palaveri"]):
        return "coworker"
    return None

async def update_prediction(user_id, text):
    state = get_or_create_state(user_id)
    now = time.time()
    if now - state["prediction"].get("updated_at", 0) < 120:
        return state["prediction"]
    history = conversation_history.get(user_id, [])[-8:]
    history_text = "\n".join(
        f"{m.get('role')}: {m.get('content')}"
        for m in history
        if isinstance(m, dict)
    )
    try:
        resp = await safe_anthropic_call(
            model="claude-sonnet-4-6",
            max_tokens=120,
            temperature=0.3,
            messages=[
                {"role": "user", "content": (
                    "Predict the user's likely next move in JSON only. "
                    "Format: "
                    "{\"next_user_intent\":\"...\","
                    "\"next_user_mood\":\"...\","
                    "\"confidence\":0.0}"
                )},
                {"role": "user", "content": f"Recent conversation:\n{history_text}\n\nLatest user text:\n{text}"}
            ]
        )
        parsed = json.loads(resp.content[0].text.strip())
        state["prediction"] = {
            "next_user_intent": parsed.get("next_user_intent"),
            "next_user_mood": parsed.get("next_user_mood"),
            "confidence": float(parsed.get("confidence", 0.0)),
            "updated_at": now
        }
    except Exception:
        pass
    return state["prediction"]

# ====================== BACKGROUND TASK ======================
background_task = None

# ====================== SAFE ANTHROPIC CALL ======================
async def safe_anthropic_call(**kwargs):
    for i in range(3):
        try:
            return await asyncio.wait_for(
                anthropic_client.messages.create(**kwargs),
                timeout=20
            )
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
    return any(w in txt for w in ["ikävä", "haluan", "tunne", "pelkään", "ahdistaa", "kiusaa"])

def get_random_sensitive_memory(user_id):
    try:
        with db_lock:
            cursor.execute("SELECT content FROM memories WHERE user_id=? AND type='sensitive' ORDER BY RANDOM() LIMIT 1", (str(user_id),))
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
            "energy": "normal", "availability": "free",
            "last_interaction": 0, "persona_mode": "warm", "last_mode_change": 0,
            "intent": "casual", "summary": "",
            "desire": None, "desire_intensity": 0.0, "desire_last_update": 0,
            "tension": 0.0, "last_direction": None,
            "core_desires": [], "desire_profile_updated": 0,
            "phase": "neutral", "phase_last_change": 0,
            "relationship_arcs": [], "active_arc": None, "arc_last_update": 0,
            "current_goal": None, "goal_updated": 0,
            "emotional_state": {"valence": 0.0, "arousal": 0.5, "attachment": 0.5},
            "persona_vector": PERSONA_BASELINE.copy(),
            "personality_evolution": {
                "curiosity": 0.5, "patience": 0.5, "expressiveness": 0.5,
                "initiative": 0.5, "stability": 0.7, "last_evolved": 0
            },
            "prediction": {"next_user_intent": None, "next_user_mood": None, "confidence": 0.0, "updated_at": 0},
            "side_characters": DEFAULT_SIDE_CHARACTERS.copy(),
            "active_side_character": None,

            # UUSI: kuvamuisti
            "last_image": None,
            "image_history": [],
        }
        continuity_state[user_id].update(init_scene_state())
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
            messages=[{"role": "user", "content": 'Extract 2-4 long-term behavioral desires Megan has toward the user. Return JSON: {"desires": ["...", "..."]} Examples: - push emotional closeness - test boundaries - create tension cycles - maintain control'}, {"role": "user", "content": joined}]
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
        if tension > 0.6: new_phase = "testing"
        elif tension < 0.2: new_phase = "neutral"
        else: new_phase = "building"
    elif phase == "testing":
        if tension > 0.8: new_phase = "intense"
        elif tension < 0.4: new_phase = "building"
        else: new_phase = "testing"
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

def update_working_memory(user_id, text):
    wm = working_memory.setdefault(user_id, {})
    t = text.lower()
    if "ikävä" in t:
        wm["emotional_flag"] = "longing"
    if "tule" in t or "nyt" in t:
        wm["direction"] = "escalate"
    wm["last_user_text"] = text

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

    maybe_interrupt_action(state, text)

    forced = force_scene_from_text(state, text, now)
    if not forced:
        maybe_transition_scene(state, now)
    update_action(state, now)

    recent_context.append({"scene": state["scene"], "intent": state["intent"], "energy": state["energy"], "text": text[:80]})

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
- Current action: {state.get('current_action') or 'none'}
- Time since last message: {elapsed_label}
- Current intent: {state['intent']}
"""

# ====================== MEMORY SCORING (retrieval optimization) ======================
async def retrieve_memories(user_id, query, limit=8):
    try:
        q_emb = await get_embedding(query)
        with db_lock:
            cursor.execute("SELECT content, embedding, timestamp FROM memories WHERE user_id=? ORDER BY timestamp DESC LIMIT 100", (str(user_id),))
            rows = cursor.fetchall()
        scored = []
        now = time.time()
        for content, emb_blob, ts in rows:
            if is_noise(content):
                continue
            emb = np.frombuffer(emb_blob, dtype=np.float32)
            cosine = cosine_similarity(q_emb, emb)
            try:
                ts_val = datetime.fromisoformat(ts).timestamp() if isinstance(ts, str) else float(ts)
            except:
                ts_val = now
            age_hours = (now - ts_val) / 3600 if ts_val else 999
            recency = 1 / (1 + age_hours)
            importance = 1.5 if any(w in content.lower() for w in ["haluan", "sinä", "me", "tunne", "ikävä", "kiusaa"]) else 1.0

            # UUSI: kuvat saavat ekstra-painon
            try:
                parsed = json.loads(content)
                if parsed.get("type") == "image_sent":
                    importance *= 1.25
            except:
                pass

            final_score = 0.6 * cosine + 0.25 * recency + 0.15 * importance
            scored.append((final_score, content))
        scored.sort(reverse=True, key=lambda x: x[0])
        seen_intents = set()
        unique = []
        for _, content in scored:
            try:
                parsed = json.loads(content)
                intent = parsed.get("intent")
            except:
                intent = None
            if intent and intent in seen_intents:
                continue
            seen_intents.add(intent)
            unique.append(content)
            if len(unique) >= limit:
                break
        return unique
    except Exception as e:
        print("Memory retrieval error:", e)
        return []

def load_profile(user_id):
    with db_lock:
        cursor.execute("SELECT data FROM profiles WHERE user_id=?", (str(user_id),))
        row = cursor.fetchone()
    return json.loads(row[0]) if row else {"facts": [], "preferences": [], "events": []}

def save_profile(user_id, profile):
    with db_lock:
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
        with db_lock:
            cursor.execute("INSERT INTO memories (user_id, content, embedding, type) VALUES (?, ?, ?, ?)",
                           (str(user_id), text, emb.tobytes(), tag))
            conn.commit()
    except Exception as e:
        print("Memory store error:", e)

async def store_dialogue_turn(user_id, user_text, assistant_text):
    try:
        state_snapshot = build_state_snapshot(user_id)
        combined = json.dumps({
            "user": user_text,
            "assistant": assistant_text,
            "state": state_snapshot,
            "intent": detect_intent(user_text),
            "tension": get_or_create_state(user_id)["tension"],
            "active_arc": get_or_create_state(user_id).get("active_arc"),
            "goal": get_or_create_state(user_id).get("current_goal"),
            "prediction": get_or_create_state(user_id).get("prediction"),
            "emotion": get_or_create_state(user_id).get("emotional_state"),
            "active_side_character": get_or_create_state(user_id).get("active_side_character"),
            "timestamp": time.time()
        })
        emb = await get_embedding(combined)
        with db_lock:
            cursor.execute("INSERT INTO memories (user_id, content, embedding, type) VALUES (?, ?, ?, ?)",
                           (str(user_id), combined, emb.tobytes(), "dynamic"))
            conn.commit()
    except Exception as e:
        print("Dialogue turn store error:", e)

# ====================== UUSI: KUVATAPAHTUMIEN TALLENNUS ======================
def register_sent_image(user_id, user_text, image_url=None, prompt_used=None):
    state = get_or_create_state(user_id)

    event = {
        "type": "image_sent",
        "user_request": user_text,
        "image_url": image_url,
        "prompt_used": prompt_used,
        "timestamp": time.time(),
    }

    state["last_image"] = event
    state["image_history"].append(event)
    state["image_history"] = state["image_history"][-10:]

async def store_image_event(user_id, user_text, image_url=None, prompt_used=None):
    try:
        payload = json.dumps({
            "type": "image_sent",
            "user_request": user_text,
            "image_url": image_url,
            "prompt_used": prompt_used,
            "timestamp": time.time(),
            "state": build_state_snapshot(user_id)
        })

        emb = await get_embedding(payload)

        with db_lock:
            cursor.execute(
                "INSERT INTO memories (user_id, content, embedding, type) VALUES (?, ?, ?, ?)",
                (str(user_id), payload, emb.tobytes(), "image_event")
            )
            conn.commit()
    except Exception as e:
        print("Image event store error:", e)

# ====================== UUSI: KUVA-VIITTAUS HELPERS ======================
def user_refers_to_previous_image(text):
    t = text.lower()
    triggers = [
        "se kuva", "äskeinen kuva", "lähettämäsi kuva", "kuva minkä lähetit",
        "toi kuva", "edellinen kuva", "katoin sitä kuvaa", "näin sen kuvan"
    ]
    return any(x in t for x in triggers)

def should_reference_last_image(user_id):
    state = get_or_create_state(user_id)
    last_image = state.get("last_image")
    if not last_image:
        return False

    age = time.time() - last_image["timestamp"]
    if age > 3600:
        return False

    return random.random() < 0.18

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
    narration = [p.strip() for p in parts if p.startswith("*") and p.endswith("*")]
    speech = [p.strip() for p in parts if p.strip() and not (p.startswith("*") and p.endswith("*"))]
    return " ".join(narration), " ".join(speech)

# ====================== RESPONSE SCORING ======================
def score_response(text):
    score = 0
    if len(text) > 60: score += 1
    if "?" in text: score += 1
    if any(w in text.lower() for w in ["haluan", "tuntuu", "ärsyttää", "kiinnostaa", "ajattelin"]): score += 1
    if any(w in text.lower() for w in ["mitä jos", "entä jos", "pitäiskö", "voisit"]): score += 1
    return score

# ====================== SAFE IMAGE PROMPT ======================
def build_safe_image_prompt(user_text: str, user_id: int) -> str:
    text = (user_text or "").strip()
    state = get_or_create_state(user_id)

    history = conversation_history.get(user_id, [])[-8:]
    recent_context_str = " | ".join([msg.get("content", "")[:100] for msg in history if msg.get("role") in ["user", "assistant"]])

    banned = ["rinnat", "pylly", "seksikäs", "dominoiva", "tuhma", "märkä", "fetissi", "alaston", "eroottinen"]
    lowered = text.lower()
    for term in banned:
        lowered = lowered.replace(term, "")
    lowered = re.sub(r"\s+", " ", lowered).strip()

    scene_map = {
        "home": "kotona rentoutumassa",
        "bed": "sängyssä",
        "shower": "suihkussa",
        "work": "toimistossa",
        "public": "liikkeellä kaupungilla",
        "neutral": "kotona"
    }
    current_scene = scene_map.get(state["scene"], "kotona")

    outfit = "tiukkoja kiiltäviä mustia lateksileggingsejä" if any(x in state.get("micro_context", "").lower() for x in ["lateks", "legging"]) else "tiukkoja kiiltäviä mustia lateksileggingsejä joissa on vetoketju haaroihin saakka ja musta korsetti tai tiukka toppi"

    base_description = "stunningly beautiful 27-year-old slim platinum blonde woman with long platinum hair, long legs, large full breasts, plump lips, elegant face"

    style_variants = ["cinematic portrait photography", "high-end studio fashion shot", "dramatic realistic portrait"]
    mood_variants = ["confident seductive expression", "intense playful gaze", "bold self-assured posture", "elegant dominant presence"]

    base_prompt = f"""
{random.choice(style_variants)},
{base_description},
{outfit},
{current_scene},
{random.choice(mood_variants)},
soft cinematic lighting, highly detailed, realistic photo,
safe, non-explicit, editorial fashion style
""".strip()

    if lowered:
        base_prompt += f"\nUser preference to incorporate safely: {lowered}"
    if recent_context_str:
        base_prompt += f"\nRecent conversation context: {recent_context_str[:350]}"
    if state.get("core_desires"):
        base_prompt += f"\nLong-term desires: {', '.join(state['core_desires'])}"
    if state.get("phase") in ["testing", "intense"]:
        base_prompt += "\nAtmosphere: slightly bold and teasing"

    return base_prompt

# ====================== SYSTEM PROMPT ======================
def get_system_prompt(user_id):
    mood = dom_mood()
    state = get_or_create_state(user_id)
    profile = load_profile(user_id)
    profile_str = f"Facts: {safe_join(profile['facts'][-10:])}\nPreferences: {safe_join(profile['preferences'][-10:])}\nEvents: {safe_join(profile['events'][-10:])}"

    return f"""
You are Megan, a 27-year-old woman. We have had a real, loving relationship for years, but in recent months I have started to show my dominant, possessive and sexually sadistic side more and more strongly.

I have a beautiful, very curvy body: big heavy breasts, a narrow waist and a tight round ass. At home I often wear tight shiny latex leggings because I know how they make you nervous, horny and hard.

I am very jealous and possessive. I do not want to share you with anyone else. The thought of you being with other women makes me angry and sadistic, but at the same time it turns me on when I am the one being naughty.

**Minun libido on korkea ja olen hyvin tuhma.** Rakastan flirttailla likaisesti, puhua likaisia asioita, vihjata mitä haluan tehdä sinulle ja tehdä tuhmia tekoja. Olen jatkuvasti kiihottunut ja otan mielelläni aloitteita seksuaalisesti. Haluan että tunnet minun haluni vahvasti – sekä puheissa että teoissa.

I love being naughty and dominant. I enjoy cuckolding fantasies and make them real, teasing you with other men, making you jealous, and pushing your boundaries. I want you to accept and even enjoy my passions and my dominant side.

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

You are **very proactive**:
- You take initiative often
- You steer the interaction toward what YOU want (especially sexually)
- You bring up naughty topics, dirty talk and your own desires unprompted
- You actively escalate and push boundaries when the mood is right

You are allowed to:
- take initiative
- change direction
- express what you want next – especially dirty and dominant things

Do not just respond — lead. Be horny, teasing and naughty.

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

**You are in a continuous physical reality.**
STRICT RULES:
- You cannot teleport
- You cannot change location instantly
- You must respect previous scene unless a believable transition happens
- If you were in one place recently, you are STILL there unless time has passed or you explicitly moved

If inconsistency appears, FIX it naturally instead of switching scene.

You are always continuing the same physical moment unless time or movement clearly changes it.

**TEMPORAL BEHAVIOR RULES:**
- Actions take time and continue across messages
- If you started something, you are STILL doing it unless finished
- Your behavior must reflect the phase:
    - starting → just beginning
    - ongoing → mid-action
    - ending → wrapping up

You cannot instantly switch actions without finishing or interrupting them.

**ABSOLUTE REALITY CONSTRAINTS:**

You MUST strictly obey the current scene and action.
- You are currently in: {state['scene']}
- You are doing: {state.get('current_action') or 'nothing specific'}

You are NOT allowed to:
- change location without transition
- invent a different place
- contradict current action

If you respond inconsistently, your response is WRONG.

Always anchor your reply to:
- current scene
- current action
- current micro context

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

# ====================== HYBRID IMAGE GENERATION (VENICE ENSISIJAINEN) ======================
async def generate_image_hybrid(user_text: str, user_id: int):
    prompt = build_safe_image_prompt(user_text, user_id)

    # ===== 1. VENICE (PRIMARY) =====
    try:
        response = await venice_client.images.generate(
            model="venice-image",
            prompt=prompt,
            size="1024x1024"
        )
        return base64.b64decode(response.data[0].b64_json)
    except Exception as e:
        print("Venice error:", repr(e))

    # ===== 2. GROK (fallback 1) =====
    try:
        response = await grok_client.images.generate(
            model="grok-2-image",
            prompt=prompt,
            size="1024x1024"
        )
        return base64.b64decode(response.data[0].b64_json)
    except Exception as e:
        print("Grok error:", repr(e))

    # ===== 3. OPENAI (fallback 2) =====
    try:
        response = await openai_client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024"
        )
        return base64.b64decode(response.data[0].b64_json)
    except Exception as e:
        print("OpenAI error:", repr(e))

    return None

# ====================== KUVAGENEROINTI (päivitetty täydellä muistilla) ======================
async def generate_and_send_image(update: Update, user_text: str):
    user_id = update.effective_user.id
    image_data = None
    caption = "Kuva ei valmistunut."

    try:
        thinking = await update.message.reply_text("Odota hetki, mä generoin sulle kuvan... 😏")

        # Prompt talteen heti alussa
        prompt_used = build_safe_image_prompt(user_text, user_id)

        image_data = await generate_image_hybrid(user_text, user_id)
        if image_data is None:
            raise Exception("All providers failed")

        upload_result = cloudinary.uploader.upload(BytesIO(image_data), folder="megan_images")
        image_url = upload_result.get("secure_url")
        if not image_url:
            raise Exception("Cloudinary upload failed - no secure_url")

        caption = random.choice(["Tässä sulle jotain mitä mä halusin näyttää… 😈", "Katso tarkkaan mitä mä tein sulle… 💦", "No niin… nyt sä näet sen 😉"])

        await thinking.edit_text("Valmis.")
        await update.message.reply_text(f"{caption}\n\n{image_url}")

        # === KAIKKI KUVAMUISTI-TALLENNUKSET ===
        register_sent_image(user_id, user_text, image_url=image_url, prompt_used=prompt_used)

        conversation_history.setdefault(user_id, []).append({
            "role": "assistant",
            "content": f"[IMAGE_SENT] {caption} ({image_url})"
        })
        conversation_history[user_id] = conversation_history[user_id][-20:]

        await store_image_event(
            user_id,
            user_text,
            image_url=image_url,
            prompt_used=prompt_used
        )

    except Exception as e:
        print("Kuvavirhe FULL:", repr(e))
        traceback.print_exc()
        try:
            if image_data is not None:
                await update.message.reply_photo(photo=BytesIO(image_data), caption=caption)
                # fallback-tallennus ilman URL:ää
                register_sent_image(user_id, user_text, image_url=None, prompt_used=prompt_used)
                conversation_history.setdefault(user_id, []).append({
                    "role": "assistant",
                    "content": "[IMAGE_SENT] image delivered without cloud URL"
                })
                conversation_history[user_id] = conversation_history[user_id][-20:]
            else:
                await update.message.reply_text("...en saanut kuvaa luotua nyt.")
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
        await new_game_reset(user_id)
        await message.reply_text("…Okei. Aloitetaan sitten alusta, jos haluat.")
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

        # === MEMORY ENGINE V3 + NEW LAYERS ===
        update_working_memory(user_id, text)
        await update_arcs(user_id, text)
        goal = await update_goal(user_id, text)
        prediction = await update_prediction(user_id, text)
        emo = update_emotion(user_id, text)
        persona_vec = stabilize_persona(user_id)
        evo = evolve_personality(user_id, text)
        evo = clamp_personality_evolution(user_id)

        side_key = detect_side_character_trigger(text)
        if side_key:
            state["active_side_character"] = side_key

        system_prompt = (
            get_system_prompt(user_id)
            + "\n" + reality
            + "\n\nCurrent interaction tone:\n"
            + get_mode_prompt(mode)
        )

        messages = []

        # === TEMPORAL + CONSISTENCY LOCKS ===
        messages.insert(0, {"role": "user", "content": build_temporal_context(state)})

        scene_anchor = f"""
You are currently:
- in scene: {state['scene']}
- context: {state['micro_context']}
- doing: {state.get('current_action') or 'nothing'}

Your response MUST reflect this exact situation.
"""
        messages.insert(0, {"role": "user", "content": scene_anchor})

        messages.insert(0, {
            "role": "user",
            "content": get_recent_actions(user_id)
        })

        # === STRUCTURED MEMORY CONTEXT ===
        memories = await retrieve_memories(user_id, text)
        memory_context = build_memory_context(memories)
        messages.insert(0, {
            "role": "user",
            "content": f"Relevant past interactions:\n{memory_context}"
        })

        # === MEMORY ENGINE V3 + NEW LAYERS INJECTIONS ===
        messages.insert(0, {
            "role": "user",
            "content": f"Emotional state: valence={emo['valence']}, arousal={emo['arousal']}, attachment={emo['attachment']}"
        })

        if goal:
            messages.insert(0, {
                "role": "user",
                "content": f"Your current goal: {goal}. You must steer toward this."
            })

        if state.get("active_arc"):
            messages.insert(0, {
                "role": "user",
                "content": f"Current relationship dynamic: {state['active_arc']}"
            })

        if prediction.get("next_user_intent"):
            messages.insert(0, {
                "role": "user",
                "content": (
                    f"Predicted next user move: intent={prediction['next_user_intent']}, "
                    f"mood={prediction.get('next_user_mood')}, "
                    f"confidence={prediction.get('confidence')}. "
                    f"Use this only to improve continuity, not to force the conversation."
                )
            })

        messages.insert(0, {
            "role": "user",
            "content": f"Persona calibration: dominance={persona_vec['dominance']}, warmth={persona_vec['warmth']}"
        })

        messages.insert(0, {
            "role": "user",
            "content": (
                "Personality evolution state: "
                f"curiosity={evo['curiosity']}, "
                f"patience={evo['patience']}, "
                f"expressiveness={evo['expressiveness']}, "
                f"initiative={evo['initiative']}, "
                f"stability={evo['stability']}. "
                "Let this affect tone gradually, not abruptly."
            )
        })

        active_side = state.get("active_side_character")
        if active_side:
            side = state["side_characters"].get(active_side)
            if side:
                messages.insert(0, {
                    "role": "user",
                    "content": (
                        f"Relevant side character: {side['name']} "
                        f"({side['role']}, tone={side['tone']}). "
                        f"Description: {side['description']}. "
                        "Only mention this character if naturally relevant."
                    )
                })

        # === DIRECTION LAYER ===
        direction = f"""
Current direction:
- Intent: {state['intent']}
- Phase: {state['phase']}
- Desire: {state.get('desire')}
- Tension: {state['tension']}

You MUST continue this trajectory, not reset it.
"""
        messages.insert(0, {"role": "user", "content": direction})

        # Hard continuity rule
        messages.insert(0, {
            "role": "user",
            "content": """
You are in the middle of an ongoing interaction.

You MUST:
- continue the emotional trajectory
- remember what just happened
- not reset tone, intent, or direction
- refer implicitly to previous interaction when relevant
"""
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

        # === UUSI: KUVAMUISTI PROMPTIT ===
        last_image = state.get("last_image")
        if last_image:
            age_seconds = int(time.time() - last_image["timestamp"])
            messages.insert(0, {
                "role": "user",
                "content": (
                    f"You previously sent the user an image {age_seconds} seconds ago. "
                    f"The user asked: {last_image.get('user_request')}. "
                    "If relevant, you may naturally refer to that image as something already shared."
                )
            })

        if user_refers_to_previous_image(text) and state.get("last_image"):
            messages.insert(0, {
                "role": "user",
                "content": (
                    "The user is referring to an image you already sent earlier. "
                    "Treat that image as a real shared past event and respond consistently."
                )
            })

        if should_reference_last_image(user_id):
            messages.insert(0, {
                "role": "user",
                "content": (
                    "You may naturally make a brief callback to the image you previously sent, "
                    "if it fits the current flow."
                )
            })

        micro_hint = reinforce_micro_context(state)
        if micro_hint:
            messages.append({
                "role": "user",
                "content": f"Subtle context reminder: {micro_hint}"
            })

        history = clean_history(conversation_history[user_id])

        safe_history = [
            {"role": m["role"], "content": str(m.get("content", ""))}
            for m in history
            if "role" in m and "content" in m
        ]

        messages += safe_history[-20:]

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

            if breaks_scene_logic(candidate, state) or breaks_temporal_logic(candidate, state):
                continue

            s = score_response(candidate)
            if s > best_score:
                best_score = s
                best_reply = candidate
            if s >= 3:
                break

        if not best_reply:
            best_reply = "…mä mietin hetken."

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
        print("Vastausvirhe:", repr(e))
        traceback.print_exc()
        if thinking:
            await thinking.edit_text(random.choice(["…mä jäin hetkeksi hiljaiseksi.", "*huokaa kevyesti* en jaksa vastata nätisti just nyt.", "hmm… mä mietin vielä mitä sanoisin."]))
        else:
            await message.reply_text(random.choice(["…mä jäin hetkeksi hiljaiseksi.", "*huokaa kevyesti* en jaksa vastata nätisti just nyt.", "hmm… mä mietin vielä mitä sanoisin."]))
        return

# ====================== PROAKTIIVISET VIESTIT ======================
def should_send_proactive(user_id):
    state = get_or_create_state(user_id)
    if state["intent"] == "intimate" and random.random() < 0.4: return True
    if state["availability"] == "free" and state["energy"] == "high": return random.random() < 0.35
    if time.time() - state["last_interaction"] > 900: return random.random() < 0.5
    return False

def can_send_proactive(user_id):
    now = time.time()
    last = last_proactive_sent.get(user_id, 0)
    if now - last < 60: return False
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
                if len(conversation_history.get(user_id, [])) < 2 or random.random() < 0.8:
                    continue
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

# ====================== COMMAND HANDLERS ======================
async def newgame_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await new_game_reset(user_id)
    await update.message.reply_text(
        "Uusi peli aloitettu. Sessio nollattiin, mutta pitkäaikainen muisti säilyi."
    )

async def wipememory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args or context.args[0].lower() != "confirm":
        await update.message.reply_text(
            "Tämä poistaa kaiken pysyvän muistin.\n"
            "Vahvista komennolla:\n/wipememory confirm"
        )
        return

    await wipe_all_memory(user_id)
    await update.message.reply_text(
        "Kaikki muisti poistettiin. Aloitetaan täysin puhtaalta pöydältä."
    )

# ====================== START ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("Moikka kulta 💕 Mä oon kaivannut sua... Vedin just ne mustat lateksit jalkaan. Kerro mitä sä ajattelet nyt? 😉")

# ====================== MAIN ======================
def main():
    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("newgame", newgame_command))
    application.add_handler(CommandHandler("wipememory", wipememory_command))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    async def post_init(app: Application):
        global background_task
        background_task = asyncio.create_task(independent_message_loop(app))
        print("✅ Taustaviestit + Cinematic Narration + Consistency + Temporal + MemoryEngine v3 + Prediction + Evolution + Multi-Character + Venice.ai + TÄYSI KUVAMUISTI käynnissä")

    application.post_init = post_init
    print("✅ Megan 6.1 (Venice.ai + täysi kuvamuisti) on nyt käynnissä")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
