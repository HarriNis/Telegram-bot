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

# ====================== MANIPULAATIOSTRATEGIAT ======================
MANIPULATION_TACTICS = { ... }  # identtinen edelliseen

DOMINANCE_ESCALATION = { ... }  # identtinen edelliseen

# ====================== SCENE ENGINE (Temporal Layer) ======================
# ... kaikki scene-funktioiden koodi identtinen edelliseen ...

# ====================== NARRATIVE EXIT SYSTEM ======================
# ... identtinen ...

# ====================== MULTI-STAGE JEALOUSY SYSTEM ======================
# ... identtinen ...

# ====================== FYYSINEN TODELLISUUS - LUKITUS ======================
# ... identtinen ...

# ====================== EMOTION ESCALATION MAP ======================
# ... identtinen ...

# ====================== ACTIVE DRIVE SYSTEM ======================
# ... identtinen ...

# ====================== USER MODEL + MASTER PLAN + STRATEGY ======================
# ... identtinen ...

# ====================== STRATEGY LEARNING (REWARD SYSTEM) ======================
# ... identtinen ...

# ====================== PLANNED EVENTS / COMMITMENTS SYSTEM ======================
# ... identtinen register_plan, save_plan_to_db, load_plans_from_db, update_plans ...

# Suunnitelman evoluutio on nyt luotettavampi (ei satunnaista muutosta vahvoille sitoumuksille)
async def maybe_evolve_plan(user_id):
    state = get_or_create_state(user_id)
    for plan in state["planned_events"]:
        if plan.get("must_fulfill", False):   # ÄLÄ muuta käyttäjän vahvoja lupauksia satunnaisesti
            continue
        # vain proaktiiviset / heikot suunnitelmat voivat kehittyä
        if plan.get("needs_check") and state.get("scene") in ["home", "public"]:
            if random.random() < 0.03:
                if state.get("emotional_mode") in ["provocative", "testing", "jealous"]:
                    if state.get("tension", 0.0) > 0.6:
                        change = random.choice(["muutin vähän suunnitelmaa", "se meni vähän eri tavalla kuin ajattelin", "jotain tuli väliin"])
                        plan["status"] = "changed"
                        plan["last_updated"] = time.time()
                        plan["evolution_log"].append({"time": time.time(), "change": change, "reason": f"emotional_mode={state['emotional_mode']}, tension={state['tension']:.2f}"})
                        save_plan_to_db(user_id, plan)
                        return plan, change
    return None, None

# ====================== DATABASE + LOCK ======================
DB_PATH = "/var/data/megan_memory.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
db_lock = threading.Lock()
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""CREATE TABLE IF NOT EXISTS memories (...)""")
cursor.execute("""CREATE TABLE IF NOT EXISTS profiles (...)""")
cursor.execute("""CREATE TABLE IF NOT EXISTS planned_events (...)""")

# Uusi taulu topic_state ja turns (kevyempi muistirakenne)
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

# ====================== TOPIC STATE (uusi kerros) ======================
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

# ====================== GET_OR_CREATE_STATE (lisätty topic_state) ======================
def get_or_create_state(user_id):
    if user_id not in continuity_state:
        continuity_state[user_id] = {
            # ... kaikki edelliset kentät identtisinä ...
            "topic_state": {
                "current_topic": "general",
                "topic_summary": "",
                "open_questions": [],
                "open_loops": [],
                "updated_at": time.time()
            },
            # ... loput kentät identtisinä ...
        }
        continuity_state[user_id].update(init_scene_state())
        continuity_state[user_id]["planned_events"] = load_plans_from_db(user_id)
    return continuity_state[user_id]

# ====================== LIGHT EXTRACTOR (yksi kutsu per viesti) ======================
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

# ====================== HANDLE_MESSAGE (parannettu flow) ======================
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

        # ... kaikki vanhat päivitykset identtisinä (scene, mood, desire, tension jne.) ...

        # Uusi extractor + topic update
        frame = await extract_basic_frame(user_id, text)
        update_topic_state(user_id, frame)

        # ... loput handle_message-koodi identtinen edelliseen versioon ...

        # Tallenna tila
        save_state_to_db(user_id)

    except Exception as e:
        print(f"[CRITICAL ERROR] {e}")
        traceback.print_exc()
        await update.message.reply_text("Tapahtui virhe, yritä uudelleen.")

# ====================== SYSTEM PROMPT (kevennetty) ======================
def get_system_prompt(user_id):
    state = get_or_create_state(user_id)
    topic = state["topic_state"]["current_topic"]
    summary = state["topic_state"]["topic_summary"][:200]

    # Core + dominance + reality + topic + plans (muut kerrokset poistettu / tiivistetty)
    final_prompt = f"""
{CORE_PERSONA text}

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

# ====================== BACKGROUND TASK ======================
async def check_proactive_triggers(application):
    while True:
        try:
            await asyncio.sleep(30)
            now = time.time()
            for user_id, state in list(continuity_state.items()):
                # ... vanha pending_narrative-logiikka identtinen ...
                # Plan checker vain vahvoille sitoumuksille (ei satunnaista muutosta)
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

    # ... kaikki command handlerit identtisinä ...

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
