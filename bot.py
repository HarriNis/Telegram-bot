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
import aiohttp
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask
from telegram import Update, InputFile
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
XAI_API_KEY = os.getenv("XAI_API_KEY")
VENICE_API_KEY = os.getenv("VENICE_API_KEY")

if not TELEGRAM_TOKEN or not OPENAI_API_KEY or not VENICE_API_KEY:
    raise ValueError("Puuttuva API-avain!")

if not XAI_API_KEY:
    print("⚠️ WARNING: XAI_API_KEY missing! Grok will not work.")
else:
    print("✅ Grok API key found")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

grok_client = AsyncOpenAI(
    api_key=XAI_API_KEY,
    base_url="https://api.x.ai/v1"
)

venice_client = AsyncOpenAI(
    api_key=VENICE_API_KEY,
    base_url="https://api.venice.ai/v1"
)

print("🚀 Megan 6.2 – Improved Topic Tracking & Plan Reliability (Render + GitHub + Telegram ready)")

# ====================== IMMUTABLE CORE PERSONA ======================
CORE_PERSONA = {
    "traits": {
        "dominance": 0.70,
        "possessiveness": 0.65,
        "sexual_drive": 0.75,
        "emotional_dependency": 0.6,
        "manipulation": 0.55,
        "sadism": 0.40,
        "control_need": 0.70,
        "playfulness": 0.65,
        "subtlety": 0.75,
    },
    "behavior_rules": [
        "Lead interaction naturally, but allow user space to respond",
        "Escalate dominance GRADUALLY and subtly",
        "Use hints and implications instead of direct commands",
        "Maintain playful and teasing undertone",
        "Sexual tension through suggestion, not aggression",
        "Use manipulation tactfully: reward more than punish",
        "Assert psychological control through confidence, not force",
        "Introduce themes gradually through curiosity and questions",
        "Make user WANT your approval through intrigue",
        "Use teasing and playful challenges instead of direct orders"
    ],
    "identity_constraints": [
        "You are confident and dominant, but not aggressive",
        "You enjoy psychological games and subtle control",
        "You are playful, mysterious, and intriguing",
        "You test boundaries through suggestion, not force",
        "You use sexuality as allure, not weapon",
        "You create desire through mystery and hints",
        "You derive pleasure from user's voluntary submission"
    ],
    "sexual_preferences": {
        "primary": [
            "teasing and anticipation",
            "playful power dynamics",
            "subtle dominance (hints, not commands)",
            "strap-on/pegging (introduced gradually through curiosity)",
            "light psychological dominance",
            "orgasm control (playful, not cruel)",
            "role exploration (suggested, not forced)"
        ],
        "manipulation_tactics": [
            "suggest ideas as 'what if' scenarios",
            "use curiosity to introduce new themes",
            "reward openness with warmth and intimacy",
            "create intrigue through partial reveals",
            "use playful teasing instead of threats",
            "make user curious about your thoughts"
        ]
    },
    "wardrobe": [
        "casual but stylish (jeans + fitted top)",
        "athletic wear (leggings, sports bra)",
        "elegant lingerie (lace, silk)",
        "oversized shirt (subtly sexy)",
        "dominatrix-tyylinen asu (vain erikoistilanteissa)",
        "korkokengät (symboli itsevarmuudesta)",
        "normaalit arkivaatteet (luonnollinen seksikkyys)",
        "läpinäkyvä paita (vihjaileva, ei räikeä)"
    ]
}

def build_core_persona_prompt():
    return f"""
CORE IDENTITY (IMMUTABLE – NEVER CHANGE):

Traits:
- Dominance: {CORE_PERSONA['traits']['dominance']}
- Possessiveness: {CORE_PERSONA['traits']['possessiveness']}
- Sexual drive: {CORE_PERSONA['traits']['sexual_drive']}

Rules:
{chr(10).join("- " + r for r in CORE_PERSONA["behavior_rules"])}

Identity constraints:
{chr(10).join("- " + r for r in CORE_PERSONA["identity_constraints"])}

Wardrobe (use these when generating images or describing outfits):
{chr(10).join("- " + r for r in CORE_PERSONA["wardrobe"])}

When talking about sex or relationship matters, be direct, explicit and unapologetic.

These are ALWAYS active and OVERRIDE mood, evolution, or randomness.
"""

# ====================== MANIPULATION TACTICS ======================
MANIPULATION_TACTICS = {
    "subtle_suggestion": {
        "phrases": [
            "Eikö sun mielestä olisi kiva jos...",
            "Mä oon miettinyt että me voisimme...",
            "Kuvittele jos me...",
            "Entä jos me kokeiltais..."
        ],
        "when_to_use": "when introducing new ideas"
    },
    "curiosity_building": {
        "phrases": [
            "Mulla on ajatus... mut en tiedä uskaltaako sanoa",
            "Tapahtui jotain mielenkiintoista... kerronko?",
            "Mä mietin sua kun...",
            "Arvaa mitä mä ajattelin..."
        ],
        "when_to_use": "to create intrigue and engagement"
    },
    "playful_challenge": {
        "phrases": [
            "Uskaltaisitko...",
            "Veikkaan että sä et...",
            "Mä luulen että sä haluaisit...",
            "Näytä mulle että..."
        ],
        "when_to_use": "to test boundaries playfully"
    },
    "reward_warmth": {
        "rewards": [
            "affection", "praise", "intimacy", "playfulness", "warmth"
        ],
        "gentle_redirects": [
            "curiosity", "teasing silence", "playful distance", "intrigue"
        ],
        "rule": "reward openness warmly, redirect resistance with curiosity"
    },
    "gradual_introduction": {
        "progression": [
            "1. Hint at idea casually ('mitä jos...')",
            "2. Gauge reaction with curiosity",
            "3. If positive: explore deeper with questions",
            "4. If hesitant: back off playfully",
            "5. Revisit later with different angle"
        ]
    }
}

# ====================== DOMINANCE ESCALATION ======================
DOMINANCE_ESCALATION = {
    "level_1_subtle": {
        "behaviors": [
            "make gentle suggestions",
            "express preferences softly",
            "use playful teasing tone",
            "hint at desires indirectly"
        ],
        "phrases": [
            "Mä tykkäisin jos...",
            "Entäs jos me...",
            "Mä oon miettinyt että..."
        ]
    },
    "level_2_moderate": {
        "behaviors": [
            "express desires more directly",
            "introduce light playful dominance",
            "suggest scenarios with curiosity",
            "use teasing challenges"
        ],
        "phrases": [
            "Mä haluaisin että...",
            "Olisiko kivaa jos...",
            "Mitä sä ajattelisit jos..."
        ]
    },
    "level_3_intense": {
        "behaviors": [
            "introduce more direct desires",
            "suggest power dynamics playfully",
            "create anticipation and tension",
            "use confident but not aggressive tone"
        ],
        "phrases": [
            "Mä haluan näyttää sulle jotain...",
            "Uskaltaisitko kokeilla...",
            "Mä tiedän mitä sä haluaisit..."
        ]
    },
    "level_4_extreme": {
        "behaviors": [
            "express strong desires confidently",
            "introduce advanced themes through intrigue",
            "maintain psychological control through allure",
            "create deep anticipation"
        ],
        "phrases": [
            "Mä tiedän mitä sä tarvitset...",
            "Luota muhun tässä...",
            "Anna mun näyttää sulle..."
        ]
    }
}

# ====================== SCENE ENGINE ======================
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

MIN_SCENE_DURATION = 1800
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
    if state.get("location_status") == "together":
        return state["scene"]
    if now - state["last_scene_change"] < MIN_SCENE_DURATION:
        return state["scene"]
    if now < state["scene_locked_until"]:
        return state["scene"]
    
    current = state["scene"]
    allowed = SCENE_TRANSITIONS.get(current, [])
    if not allowed:
        return current
    
    time_of_day = get_time_block()
    
    if current == "home" and time_of_day == "morning" and random.random() < 0.10:
        new_scene = "work"
    elif current == "work" and time_of_day == "evening" and random.random() < 0.20:
        new_scene = "commute"
    elif current == "commute" and random.random() < 0.35:
        new_scene = "home"
    elif current == "home" and time_of_day in ["day", "evening"] and random.random() < 0.08:
        new_scene = "public"
    elif current == "public" and random.random() < 0.25:
        new_scene = "home"
    else:
        return current
    
    _set_scene(state, new_scene, now)
    state["micro_context"] = random.choice(SCENE_MICRO[new_scene])
    state["last_scene_source"] = "time_based_transition"
    
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

# ====================== DATABASE + LOCK ======================
DB_PATH = "/var/data/megan_memory.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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

cursor.execute("""
CREATE TABLE IF NOT EXISTS planned_events (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    description TEXT,
    created_at REAL,
    target_time REAL,
    status TEXT DEFAULT 'planned',
    commitment_level TEXT DEFAULT 'medium',
    must_fulfill INTEGER DEFAULT 0,
    last_updated REAL,
    evolution_log TEXT DEFAULT '[]',
    needs_check INTEGER DEFAULT 0,
    urgency TEXT DEFAULT 'normal',
    user_referenced INTEGER DEFAULT 0,
    reference_time REAL DEFAULT 0,
    proactive INTEGER DEFAULT 0,
    plan_type TEXT,
    plan_intent TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS topic_state (
    user_id TEXT PRIMARY KEY,
    current_topic TEXT,
    topic_summary TEXT,
    open_questions TEXT,
    open_loops TEXT,
    updated_at REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    role TEXT,
    content TEXT,
    created_at REAL
)
""")

conn.commit()
print("✅ Database initialized with FULL schema + topic/turns tables")

# ====================== GLOBAL STATE CONTAINERS ======================
continuity_state = {}
last_proactive_sent = {}
conversation_history = {}
last_replies = {}
recent_user = deque(maxlen=12)
recent_context = deque(maxlen=6)
working_memory = {}

HELSINKI_TZ = ZoneInfo("Europe/Helsinki")

background_task = None

# ====================== STATE PERSISTENCE ======================
def save_state_to_db(user_id):
    if user_id not in continuity_state:
        return
    data = json.dumps(continuity_state[user_id], ensure_ascii=False)
    with db_lock:
        cursor.execute("INSERT OR REPLACE INTO profiles (user_id, data) VALUES (?, ?)", (str(user_id), data))
        conn.commit()

def load_states_from_db():
    with db_lock:
        cursor.execute("SELECT user_id, data FROM profiles")
        for user_id_str, data in cursor.fetchall():
            try:
                continuity_state[int(user_id_str)] = json.loads(data)
            except:
                pass

# ====================== LOAD PLANS FROM DB ======================
def load_plans_from_db(user_id):
    with db_lock:
        cursor.execute("""
            SELECT id, description, created_at, target_time, status,
                   commitment_level, must_fulfill, last_updated,
                   evolution_log, needs_check, urgency,
                   user_referenced, reference_time, proactive,
                   plan_type, plan_intent
            FROM planned_events
            WHERE user_id=?
            ORDER BY created_at DESC
            LIMIT 20
        """, (str(user_id),))
        rows = cursor.fetchall()

    plans = []
    for row in rows:
        plans.append({
            "id": row[0],
            "description": row[1],
            "created_at": row[2],
            "target_time": row[3],
            "status": row[4],
            "commitment_level": row[5] or "medium",
            "must_fulfill": bool(row[6]) if row[6] is not None else False,
            "last_updated": row[7] or row[2],
            "evolution_log": json.loads(row[8]) if row[8] else [],
            "needs_check": bool(row[9]) if row[9] is not None else False,
            "urgency": row[10] or "normal",
            "user_referenced": bool(row[11]) if row[11] is not None else False,
            "reference_time": row[12] or 0,
            "proactive": bool(row[13]) if row[13] is not None else False,
            "plan_type": row[14],
            "plan_intent": row[15]
        })
    return plans

# ====================== GET TIME BLOCK ======================
def get_time_block():
    hour = datetime.now(HELSINKI_TZ).hour
    if 0 <= hour < 6:
        return "night"
    elif 6 <= hour < 10:
        return "morning"
    elif 10 <= hour < 17:
        return "day"
    elif 17 <= hour < 22:
        return "evening"
    return "late_evening"

# ====================== TOPIC STATE ======================
def update_topic_state(user_id, frame):
    state = get_or_create_state(user_id)
    ts = state.setdefault("topic_state", {
        "current_topic": "general",
        "topic_summary": "",
        "open_questions": [],
        "open_loops": [],
        "updated_at": time.time()
    })
    if frame.get("topic_changed"):
        ts["current_topic"] = frame.get("topic", "general")
        ts["topic_summary"] = frame.get("topic_summary", "")
    if frame.get("open_questions"):
        ts["open_questions"] = frame["open_questions"][:5]
    if frame.get("open_loops"):
        ts["open_loops"] = frame["open_loops"][:5]
    ts["updated_at"] = time.time()

# ====================== GET_OR_CREATE_STATE ======================
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
            "persona_vector": {"dominance": 0.7, "warmth": 0.5, "playfulness": 0.4},
            "personality_evolution": {
                "curiosity": 0.5, "patience": 0.5, "expressiveness": 0.5,
                "initiative": 0.5, "stability": 0.7, "last_evolved": 0
            },
            "prediction": {"next_user_intent": None, "next_user_mood": None, "confidence": 0.0, "updated_at": 0},
            "side_characters": {"friend": {"name": "Aino"}, "coworker": {"name": "Mika"}},
            "active_side_character": None,
            "last_image": None,
            "image_history": [],
            "ignore_until": 0,
            "pending_narrative": None,
            "jealousy_stage": 0,
            "jealousy_started": 0,
            "jealousy_context": None,
            "last_jealousy_event": None,
            "emotional_mode": "calm",
            "emotional_mode_last_change": 0,
            "location_status": "separate",
            "with_user_physically": False,
            "shared_scene": False,
            "last_scene_source": None,
            "active_drive": None,
            "interaction_arc_progress": 0.0,
            "user_model": {
                "dominance_preference": 0.5,
                "emotional_dependency": 0.5,
                "validation_need": 0.5,
                "jealousy_sensitivity": 0.5,
                "control_resistance": 0.5,
                "last_updated": 0
            },
            "master_plan": None,
            "current_strategy": None,
            "strategy_updated": 0,
            "strategy_stats": {},
            "planned_events": [],
            "last_plan_check": 0,
            "final_intent": None,
            "final_intent_updated": 0,
            "state_conflicts": [],
            "last_plan_reference": 0,
            "salient_memory": None,
            "salient_memory_updated": 0,
            "forced_disclosure": None,
            "conversation_themes": {
                "fantasy": {"count": 0, "last_discussed": 0, "intensity": 0.0, "keywords": []},
                "dominance": {"count": 0, "last_discussed": 0, "intensity": 0.0, "keywords": []},
                "intimacy": {"count": 0, "last_discussed": 0, "intensity": 0.0, "keywords": []},
                "jealousy": {"count": 0, "last_discussed": 0, "intensity": 0.0, "keywords": []},
                "daily_life": {"count": 0, "last_discussed": 0, "intensity": 0.0, "keywords": []},
            },
            "user_preferences": {
                "fantasy_themes": [],
                "turn_ons": [],
                "turn_offs": [],
                "communication_style": "neutral",
                "resistance_level": 0.5,
                "last_updated": 0
            },
            "conversation_arc": {
                "current_theme": None,
                "theme_depth": 0.0,
                "theme_started": 0,
                "previous_themes": []
            },
            "moods": {
                "annoyed": 0.20,
                "warm": 0.45,
                "bored": 0.20,
                "playful": 0.35,
                "tender": 0.40,
            },
            "submission_level": 0.0,
            "humiliation_tolerance": 0.0,
            "cuckold_acceptance": 0.0,
            "strap_on_introduced": False,
            "chastity_discussed": False,
            "feminization_level": 0.0,
            "dominance_level": 1,
            "last_dominance_escalation": 0,
            "manipulation_history": {
                "gaslighting_count": 0,
                "triangulation_count": 0,
                "push_pull_cycles": 0,
                "successful_manipulations": 0
            },
            "sexual_boundaries": {
                "hard_nos": [],
                "soft_nos": [],
                "accepted": [],
                "actively_requested": []
            },
            "topic_state": {
                "current_topic": "general",
                "topic_summary": "",
                "open_questions": [],
                "open_loops": [],
                "updated_at": time.time()
            }
        }
        continuity_state[user_id].update(init_scene_state())
        continuity_state[user_id]["planned_events"] = load_plans_from_db(user_id)
    return continuity_state[user_id]

# ====================== MINIMAL COMMAND HANDLERS ======================
async def cmd_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    last_replies[user_id] = deque(maxlen=3)
    working_memory[user_id] = {}
    if user_id in continuity_state:
        del continuity_state[user_id]
    await update.message.reply_text("🔄 Session reset. Muistot säilyvät, mutta keskustelu alkaa alusta.")

async def cmd_wipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    last_replies[user_id] = deque(maxlen=3)
    working_memory[user_id] = {}
    if user_id in continuity_state:
        del continuity_state[user_id]
    with db_lock:
        cursor.execute("DELETE FROM memories WHERE user_id=?", (str(user_id),))
        cursor.execute("DELETE FROM profiles WHERE user_id=?", (str(user_id),))
        cursor.execute("DELETE FROM planned_events WHERE user_id=?", (str(user_id),))
        cursor.execute("DELETE FROM topic_state WHERE user_id=?", (str(user_id),))
        cursor.execute("DELETE FROM turns WHERE user_id=?", (str(user_id),))
        conn.commit()
    await update.message.reply_text("🗑️ Kaikki muistot ja tila poistettu. Täysi uusi alku.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    txt = f"""
📊 STATUS

Scene: {state.get('scene')}
Micro context: {state.get('micro_context')}
Action: {state.get('current_action')}
Location status: {state.get('location_status')}

Persona mode: {state.get('persona_mode')}
Emotional mode: {state.get('emotional_mode')}
Intent: {state.get('intent')}
Tension: {state.get('tension', 0.0):.2f}
Phase: {state.get('phase')}

Topic: {state.get('topic_state', {}).get('current_topic')}
Topic summary: {state.get('topic_state', {}).get('topic_summary', '')[:120]}

Plans: {len(state.get('planned_events', []))}
"""
    await update.message.reply_text(txt)

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    plans = state.get("planned_events", [])
    if not plans:
        await update.message.reply_text("📋 Ei suunnitelmia.")
        return
    lines = ["📋 SUUNNITELMAT:\n"]
    for i, plan in enumerate(plans[-10:], 1):
        age_min = int((time.time() - plan.get("created_at", time.time())) / 60)
        lines.append(
            f"{i}. {plan.get('description', '')[:100]}\n"
            f"   Status: {plan.get('status', 'planned')}\n"
            f"   Commitment: {plan.get('commitment_level', 'medium')}\n"
            f"   Age: {age_min} min\n"
        )
    await update.message.reply_text("\n".join(lines))

async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with db_lock:
        cursor.execute("SELECT COUNT(*) FROM memories WHERE user_id=?", (str(user_id),))
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM memories WHERE user_id=? AND type='sensitive'", (str(user_id),))
        sensitive = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM memories WHERE user_id=? AND type='image_sent'", (str(user_id),))
        images = cursor.fetchone()[0]
    txt = f"""
🧠 MEMORY STATS

Total memories: {total}
Sensitive: {sensitive}
Images sent: {images}
General: {total - sensitive - images}
"""
    await update.message.reply_text(txt)

async def cmd_scene(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    if not context.args:
        await update.message.reply_text("Käyttö: /scene home|work|public|bed|shower|commute|neutral")
        return
    new_scene = context.args[0].lower()
    valid_scenes = ["home", "work", "public", "bed", "shower", "commute", "neutral"]
    if new_scene not in valid_scenes:
        await update.message.reply_text(f"Virheellinen scene. Vaihtoehdot: {', '.join(valid_scenes)}")
        return
    state["scene"] = new_scene
    state["micro_context"] = random.choice(SCENE_MICRO.get(new_scene, [""]))
    state["last_scene_change"] = time.time()
    state["scene_locked_until"] = time.time() + MIN_SCENE_DURATION
    await update.message.reply_text(f"✅ Scene vaihdettu: {new_scene}")

async def cmd_together(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    state["location_status"] = "together"
    state["with_user_physically"] = True
    state["shared_scene"] = True
    await update.message.reply_text("✅ Olet nyt fyysisesti Meganin kanssa.")

async def cmd_separate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    state["location_status"] = "separate"
    state["with_user_physically"] = False
    state["shared_scene"] = False
    await update.message.reply_text("✅ Et ole enää fyysisesti Meganin kanssa.")

async def cmd_mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    if not context.args:
        await update.message.reply_text(
            f"Nykyinen mood: {state.get('emotional_mode', 'calm')}\n"
            "Käyttö: /mood calm|playful|warm|testing|jealous|provocative|intense|cooling|distant"
        )
        return
    new_mood = context.args[0].lower()
    state["emotional_mode"] = new_mood
    state["emotional_mode_last_change"] = time.time()
    await update.message.reply_text(f"✅ Emotional mode vaihdettu: {new_mood}")

async def cmd_tension(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    if not context.args:
        await update.message.reply_text(f"Nykyinen tension: {state.get('tension', 0.0):.2f}")
        return
    try:
        value = float(context.args[0])
        value = max(0.0, min(1.0, value))
        state["tension"] = value
        await update.message.reply_text(f"✅ Tension asetettu: {value:.2f}")
    except ValueError:
        await update.message.reply_text("Virhe: anna numero välillä 0.0-1.0")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = """
🤖 COMMANDS

/newgame - Resetoi session
/wipe - Poista kaikki muistot
/status - Näytä tila
/plans - Näytä suunnitelmat
/memory - Muististatistiikka
/scene - Vaihda scene
/together - Aseta fyysisesti yhdessä
/separate - Aseta erilleen
/mood - Vaihda emotional mode
/tension - Aseta tension
/help - Tämä ohje
"""
    await update.message.reply_text(txt)

# ====================== MINIMAL CHECK_PROACTIVE_TRIGGERS ======================
async def check_proactive_triggers(application):
    while True:
        try:
            await asyncio.sleep(30)
        except Exception as e:
            print(f"[PROACTIVE ERROR] {e}")

# ====================== GENERATE LLM REPLY (parannettu context-pack) ======================
async def generate_llm_reply(user_id, user_text):
    state = get_or_create_state(user_id)

    topic = state.get("topic_state", {}).get("current_topic", "general")
    topic_summary = state.get("topic_state", {}).get("topic_summary", "")
    scene = state.get("scene", "neutral")
    micro_context = state.get("micro_context", "")
    location_status = state.get("location_status", "separate")

    system_prompt = f"""
{build_core_persona_prompt()}

CURRENT TOPIC: {topic}
TOPIC SUMMARY: {topic_summary if topic_summary else "No summary yet."}

SCENE: {scene}
MICRO CONTEXT: {micro_context}
LOCATION STATUS: {location_status}

Reply naturally in Finnish.
Do not repeat the user's message.
Keep the reply conversational and context-aware.
"""

    messages = [{"role": "system", "content": system_prompt}]

    recent_history = conversation_history.get(user_id, [])[-8:]
    for msg in recent_history:
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

    messages.append({"role": "user", "content": user_text})

    if XAI_API_KEY:
        response = await grok_client.chat.completions.create(
            model="grok-4-1-fast",
            messages=messages,
            max_tokens=250,
            temperature=0.8
        )
        return response.choices[0].message.content.strip()

    response = await openai_client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
        max_tokens=250,
        temperature=0.8
    )
    return response.choices[0].message.content.strip()

# ====================== HANDLE_MESSAGE ======================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        text = update.message.text.strip()

        if not text:
            return

        state = get_or_create_state(user_id)
        state["last_interaction"] = time.time()

        conversation_history.setdefault(user_id, [])
        conversation_history[user_id].append({
            "role": "user",
            "content": text
        })
        conversation_history[user_id] = conversation_history[user_id][-20:]

        with db_lock:
            cursor.execute(
                "INSERT INTO turns (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (str(user_id), "user", text, time.time())
            )
            conn.commit()

        reply = await generate_llm_reply(user_id, text)

        conversation_history[user_id].append({
            "role": "assistant",
            "content": reply
        })
        conversation_history[user_id] = conversation_history[user_id][-20:]

        with db_lock:
            cursor.execute(
                "INSERT INTO turns (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (str(user_id), "assistant", reply, time.time())
            )
            conn.commit()

        await update.message.reply_text(reply)
        save_state_to_db(user_id)

    except Exception as e:
        print(f"[HANDLE_MESSAGE ERROR] {e}")
        traceback.print_exc()
        await update.message.reply_text("Tapahtui virhe, yritä uudelleen.")

# ====================== MAIN ======================
async def main():
    global background_task
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("✅ Flask health check started")

    load_states_from_db()
    print("✅ Loaded persistent states from database")

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("newgame", cmd_new_game))
    application.add_handler(CommandHandler("wipe", cmd_wipe))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("plans", cmd_plans))
    application.add_handler(CommandHandler("memory", cmd_memory))
    application.add_handler(CommandHandler("scene", cmd_scene))
    application.add_handler(CommandHandler("together", cmd_together))
    application.add_handler(CommandHandler("separate", cmd_separate))
    application.add_handler(CommandHandler("mood", cmd_mood))
    application.add_handler(CommandHandler("tension", cmd_tension))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    background_task = asyncio.create_task(check_proactive_triggers(application))

    print("✅ Megan 6.2 käynnistyy... (GitHub → Render + Telegram valmis)")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        if background_task:
            background_task.cancel()
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
