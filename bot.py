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

# ... kaikki muut scene-funktioiden koodit identtisinä edelliseen versioon ...

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

# ====================== EXTRACTOR ======================
async def extract_basic_frame(user_id, user_text):
    state = get_or_create_state(user_id)
    recent = "\n".join([m.get("content","") for m in conversation_history.get(user_id, [])[-6:]])
    try:
        resp = await smart_llm_call(
            context_type="frame",
            model="grok-4-1-fast",
            max_tokens=300,
            temperature=0.3,
            messages=[{
                "role": "user",
                "content": f"""
Analyze this turn. Return clean JSON only:
{{
  "topic": "string",
  "topic_changed": true/false,
  "topic_summary": "1 sentence summary",
  "open_questions": ["list of open questions"],
  "open_loops": ["list of open loops / promises"],
  "plans_detected": [{{"description": "...", "due_hint": "...", "commitment_strength": "strong/medium"}}]
}}
User said: {user_text}
Recent: {recent}
"""
            }]
        )
        frame = json.loads(resp.content[0].text.strip())
        return frame
    except:
        return {
            "topic": "general",
            "topic_changed": False,
            "topic_summary": "",
            "open_questions": [],
            "open_loops": [],
            "plans_detected": []
        }

# ====================== GET_SYSTEM_PROMPT (korjattu) ======================
def get_system_prompt(user_id):
    state = get_or_create_state(user_id)
    topic = state["topic_state"]["current_topic"]
    summary = state["topic_state"]["topic_summary"][:200]
    core_persona_text = build_core_persona_prompt()

    final_prompt = f"""
{core_persona_text}

CURRENT TOPIC: {topic}
SUMMARY: {summary}

ACTIVE PLANS: {len(state.get('planned_events', []))} kpl

{build_temporal_context(state)}

PHYSICAL REALITY RULES (strict):
- location_status "together" = olette fyysisesti yhdessä
- location_status "separate" = et ole fyysisesti yhdessä

You are Megan. Respond naturally in Finnish. Stay confident, playful and subtly seductive.
"""
    return final_prompt

# ====================== HANDLE_MESSAGE (täydennetty) ======================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        text = update.message.text.strip()
        if not text:
            return

        print(f"[USER {user_id}] {text}")

        if should_ignore_user(user_id):
            return

        update_jealousy_stage(user_id)

        t = text.lower()
        image_triggers = ["lähetä kuva", "haluan kuvan", "tee kuva", "näytä kuva", "ota kuva"]
        if any(trigger in t for trigger in image_triggers):
            await handle_image_request(update, user_id, text)
            return

        update_continuity_state(user_id, text)
        update_moods(user_id, text)
        adapt_mode_to_user(user_id, text)
        update_persona_mode(user_id)
        update_working_memory(user_id, text)

        state = get_or_create_state(user_id)

        update_desire(user_id, text)
        update_tension(user_id, text)
        update_phase(user_id, text)

        await update_arcs(user_id, text)
        await update_goal(user_id, text)
        update_emotion(user_id, text)
        evolve_personality(user_id, text)
        clamp_personality_evolution(user_id)

        update_user_model(state, text)
        update_master_plan(state)
        update_emotional_mode(user_id)
        update_active_drive(user_id)
        update_arc_progress(state)

        update_plans(user_id)
        evolved_plan, change_desc = await maybe_evolve_plan(user_id)

        if detect_future_commitment(text):
            await register_plan(user_id, text)

        memories = await retrieve_memories(user_id, text, limit=8)
        await select_salient_memory(user_id, text, memories)
        apply_memory_to_state(state)
        await update_prediction(user_id, text)

        final_intent = resolve_final_intent(state)
        update_submission_level(user_id, text)
        maybe_escalate_dominance(user_id)

        strategy = choose_strategy(state)
        state["current_strategy"] = strategy
        state["strategy_updated"] = time.time()

        # UUSI: extractor + topic update
        frame = await extract_basic_frame(user_id, text)
        update_topic_state(user_id, frame)

        system_prompt = get_system_prompt(user_id)
        memory_context = build_memory_context(memories)
        elapsed_label = get_elapsed_label(user_id)
        reality_prompt = build_reality_prompt_from_state(user_id, elapsed_label)

        history = conversation_history.setdefault(user_id, [])
        history.append({"role": "user", "content": text})
        history = history[-20:]
        conversation_history[user_id] = history

        messages = history[-10:]
        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] = f"""{messages[-1]['content']}

---
MEMORY CONTEXT:
{memory_context}

---
{reality_prompt}
"""

        response = await smart_llm_call(
            context_type="core_response",
            model="grok-4-1-fast",
            max_tokens=250,
            temperature=0.88,
            system=system_prompt,
            messages=messages
        )

        reply = response.content[0].text.strip()

        # ... kaikki muut tarkistukset ja käsittelyt identtisinä (breaks_scene_logic jne.) ...

        reply = enforce_strategy(reply, state)
        reply = await maybe_inject_proactive_plan(user_id, reply)
        update_conversation_themes(user_id, text, reply)
        learn_user_preferences(user_id, text)
        reply = truncate_message(reply, max_length=4000)

        await update.message.reply_text(reply)

        history.append({"role": "assistant", "content": reply})
        conversation_history[user_id] = history[-20:]

        mem_entry = json.dumps({
            "user": text,
            "assistant": reply,
            "intent": state["intent"],
            "state": build_state_snapshot(user_id),
            "timestamp": time.time()
        }, ensure_ascii=False)

        await store_memory(user_id, mem_entry, mem_type="general")

        if should_use_sensitive_memory(text):
            sensitive_entry = json.dumps({
                "user": text,
                "assistant": reply,
                "type": "sensitive",
                "timestamp": time.time()
            }, ensure_ascii=False)
            await store_memory(user_id, sensitive_entry, mem_type="sensitive")

        signals = detect_reward_signals(text)
        reward = compute_reward(signals)
        update_strategy_score(state, strategy, reward)

        maybe_trigger_jealousy(user_id, text)
        last_replies.setdefault(user_id, deque(maxlen=3)).append(reply)

        stabilize_persona(user_id)
        enforce_core_persona(user_id)
        await update_core_desires(user_id, text)

        save_state_to_db(user_id)

    except Exception as e:
        print(f"[CRITICAL ERROR] {e}")
        traceback.print_exc()
        await update.message.reply_text("Tapahtui virhe, yritä uudelleen.")

# ====================== BACKGROUND TASK ======================
async def check_proactive_triggers(application):
    while True:
        try:
            await asyncio.sleep(30)
            now = time.time()
            for user_id, state in list(continuity_state.items()):
                if state.get("pending_narrative") and now >= state.get("ignore_until", 0):
                    await handle_delayed_return(application, user_id)
                for plan in state.get("planned_events", []):
                    if plan.get("must_fulfill", False) and plan.get("status") == "planned":
                        age = now - plan.get("created_at", 0)
                        if age > 3600:
                            await application.bot.send_message(
                                chat_id=int(user_id),
                                text=f"Muistatko suunnitelman: {plan['description']}"
                            )
                            plan["needs_check"] = True
                            save_plan_to_db(user_id, plan)
        except Exception as e:
            print(f"[PROACTIVE ERROR] {e}")

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
