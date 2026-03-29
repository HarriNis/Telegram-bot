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
from telegram import Update
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
    print(f"[DEBUG] XAI_API_KEY first 10 chars: {XAI_API_KEY[:10]}...")
    print(f"[DEBUG] XAI_API_KEY length: {len(XAI_API_KEY)}")

print("⚠️ Anthropic disabled - using Grok only")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

grok_client = AsyncOpenAI(
    api_key=XAI_API_KEY,
    base_url="https://api.x.ai/v1"
)

print(f"[DEBUG] Grok client base URL: {grok_client.base_url}")

venice_client = AsyncOpenAI(
    api_key=VENICE_API_KEY,
    base_url="https://api.venice.ai/v1"
)

# ====================== API KEY VALIDATION ======================
print("=" * 60)
print("🔑 API KEY VALIDATION:")
print(f"TELEGRAM_TOKEN: {'✅ OK' if TELEGRAM_TOKEN else '❌ MISSING'}")
print(f"OPENAI_API_KEY: {'✅ OK' if OPENAI_API_KEY else '❌ MISSING'}")
print(f"XAI_API_KEY: {'✅ OK' if XAI_API_KEY else '❌ MISSING'}")
print(f"VENICE_API_KEY: {'✅ OK' if VENICE_API_KEY else '❌ MISSING'}")

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
print(f"REPLICATE_API_TOKEN: {'✅ OK' if REPLICATE_API_TOKEN else '❌ MISSING'}")

if REPLICATE_API_TOKEN:
    print(f"REPLICATE_API_TOKEN length: {len(REPLICATE_API_TOKEN)}")
    print(f"REPLICATE_API_TOKEN preview: {REPLICATE_API_TOKEN[:10]}...")
else:
    print("⚠️ WARNING: REPLICATE_API_TOKEN missing! Image generation will fail.")

print("=" * 60)

print("🚀 Megan 6.2 – Cloudinary removed, direct Telegram image sending")

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

def _set_scene(state, scene, now):
    state["scene"] = scene
    state["last_scene_change"] = now
    state["scene_locked_until"] = now + MIN_SCENE_DURATION
    state["current_action"] = None
    state["action_started"] = 0
    state["action_duration"] = 0

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
            "side_characters": {"friend": {"name": "Aino", "role": "friend", "tone": "warm and casual", "description": "A relaxed friend"}, "coworker": {"name": "Mika", "role": "coworker", "tone": "professional but friendly", "description": "A coworker"}},
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
        }
        continuity_state[user_id].update(init_scene_state())
        continuity_state[user_id]["planned_events"] = load_plans_from_db(user_id)
    return continuity_state[user_id]

# ====================== DATABASE ======================
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

cursor.execute("DROP TABLE IF EXISTS planned_events")
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
conn.commit()
print("✅ Database initialized with FULL schema")

continuity_state = {}
conversation_history = {}
last_replies = {}
recent_user = deque(maxlen=12)
recent_context = deque(maxlen=6)

# ====================== MEMORY ENGINE ======================
async def get_embedding(text):
    try:
        resp = await openai_client.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        return np.array(resp.data[0].embedding, dtype=np.float32)
    except Exception as e:
        print(f"[get_embedding error] {e}")
        return np.zeros(1536, dtype=np.float32)

def cosine_similarity(a, b):
    if len(a) == 0 or len(b) == 0:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

async def store_memory(user_id, content, mem_type="general"):
    try:
        emb = await get_embedding(content)
        with db_lock:
            cursor.execute(
                "INSERT INTO memories (user_id, content, embedding, type) VALUES (?, ?, ?, ?)",
                (str(user_id), content, emb.tobytes(), mem_type)
            )
            conn.commit()
    except Exception as e:
        print(f"[store_memory error] {e}")

async def retrieve_memories(user_id, query, limit=8):
    try:
        q_emb = await get_embedding(query)
        with db_lock:
            cursor.execute("""
                SELECT content, embedding, timestamp 
                FROM memories 
                WHERE user_id=? 
                ORDER BY timestamp DESC 
                LIMIT 200
            """, (str(user_id),))
            rows = cursor.fetchall()
        
        scored = []
        now = time.time()
        
        for content, emb_blob, ts in rows:
            emb = np.frombuffer(emb_blob, dtype=np.float32)
            cosine = cosine_similarity(q_emb, emb)
            age_hours = (now - float(ts)) / 3600 if ts else 999
            recency = 1 / (1 + age_hours)
            final_score = 0.4 * cosine + 0.3 * recency + 0.3
            scored.append((final_score, content))
        
        scored.sort(reverse=True, key=lambda x: x[0])
        return [content for _, content in scored[:limit]]
    except Exception as e:
        print(f"[retrieve_memories error] {e}")
        return []

# ====================== IMAGE GENERATION (SUORA TELEGRAM) ======================
async def generate_image_replicate(prompt: str):
    try:
        print(f"[REPLICATE] Starting Flux-schnell generation...")
        print(f"[REPLICATE] Prompt length: {len(prompt)}")

        if len(prompt) > 1000:
            prompt = prompt[:950] + "\n\n[TRUNCATED]"

        replicate_token = os.getenv("REPLICATE_API_TOKEN")
        if not replicate_token:
            print("[REPLICATE ERROR] REPLICATE_API_TOKEN missing!")
            return None

        async with aiohttp.ClientSession() as session:
            payload = {
                "version": "a6b5c5e4f0c5f7a2b8f3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4",
                "input": {
                    "prompt": prompt,
                    "width": 1024,
                    "height": 1024,
                    "num_inference_steps": 8,
                    "output_format": "jpg",
                    "output_quality": 95,
                    "safety_tolerance": 3
                }
            }

            async with session.post(
                "https://api.replicate.com/v1/predictions",
                headers={"Authorization": f"Token {replicate_token}", "Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status != 201:
                    print(f"[REPLICATE ERROR] Failed to create: {resp.status}")
                    return None
                prediction = await resp.json()
                prediction_id = prediction["id"]
                print(f"[REPLICATE] Prediction ID: {prediction_id}")

            for i in range(180):
                await asyncio.sleep(1)
                async with session.get(
                    f"https://api.replicate.com/v1/predictions/{prediction_id}",
                    headers={"Authorization": f"Token {replicate_token}"},
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    result = await resp.json()
                    status = result.get("status")

                    if i % 10 == 0:
                        print(f"[REPLICATE] Status: {status} ({i+1}s)")

                    if status == "succeeded":
                        output = result["output"]
                        image_url = output[0] if isinstance(output, list) else output
                        print(f"[REPLICATE] ✅ Image URL: {image_url}")

                        async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=30)) as img_resp:
                            if img_resp.status == 200:
                                return await img_resp.read()
                    elif status == "failed":
                        print(f"[REPLICATE ERROR] Failed: {result.get('error')}")
                        return None

            print("[REPLICATE ERROR] Timeout")
            return None

    except Exception as e:
        print(f"[REPLICATE CRITICAL] {type(e).__name__}: {e}")
        traceback.print_exc()
        return None


async def handle_image_request(update: Update, user_id, text):
    state = get_or_create_state(user_id)
    
    outfit = random.choice(CORE_PERSONA["wardrobe"])
    scene_desc = state.get("micro_context") or state.get("scene") or "kotona"
    
    base_prompt = f"""
A photorealistic portrait of a beautiful Finnish woman in her mid-20s.

Physical features:
- Natural blonde hair, shoulder-length, slightly wavy
- Blue-green eyes, expressive and confident
- Athletic yet feminine build
- Fair Nordic skin tone with natural freckles
- Natural makeup, subtle and elegant
- Confident, friendly expression

Clothing:
{outfit}

Setting:
{scene_desc}, natural lighting, warm atmosphere

Style:
Professional photography, cinematic lighting, high detail, realistic skin texture
"""

    await update.message.reply_text("Hetki, otan kuvan...")

    print(f"[IMAGE] Starting generation for user {user_id}")

    try:
        image_bytes = await generate_image_replicate(base_prompt)
        
        if not image_bytes:
            await update.message.reply_text("Kuvan generointi epäonnistui. Yritä uudelleen.")
            return

        await update.message.reply_photo(
            photo=image_bytes,
            caption="📸 Tässä kuva sinulle ✨"
        )
        print(f"[IMAGE] ✅ Photo sent directly to Telegram!")

    except Exception as e:
        print(f"[IMAGE ERROR] {e}")
        await update.message.reply_text(f"Virhe: {str(e)}")
        return

    state["last_image"] = {
        "prompt": base_prompt,
        "user_request": text,
        "timestamp": time.time()
    }
    state.setdefault("image_history", []).append(state["last_image"])
    state["image_history"] = state["image_history"][-20:]

    mem_entry = json.dumps({
        "type": "image_sent",
        "user_request": text,
        "outfit": outfit,
        "scene": scene_desc,
        "timestamp": time.time()
    }, ensure_ascii=False)
    
    await store_memory(user_id, mem_entry, mem_type="image_sent")

# ====================== COMMAND HANDLERS ======================
async def cmd_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in continuity_state:
        del continuity_state[user_id]
    if user_id in conversation_history:
        del conversation_history[user_id]
    await update.message.reply_text("🔄 Session reset. Muistot säilyvät, mutta keskustelu alkaa alusta.")

async def cmd_wipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with db_lock:
        cursor.execute("DELETE FROM memories WHERE user_id=?", (str(user_id),))
        cursor.execute("DELETE FROM planned_events WHERE user_id=?", (str(user_id),))
        conn.commit()
    if user_id in continuity_state:
        del continuity_state[user_id]
    if user_id in conversation_history:
        del conversation_history[user_id]
    await update.message.reply_text("🗑️ Kaikki muistot ja tila poistettu. Täysi uusi alku.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    status = f"""
📊 **STATUS**
**Scene:** {state['scene']}
**Micro context:** {state.get('micro_context') or 'none'}
**Location status:** {state.get('location_status')}
**Emotional mode:** {state.get('emotional_mode')}
**Tension:** {state.get('tension', 0):.2f}
**Dominance level:** {state.get('dominance_level', 1)}
**Submission level:** {state.get('submission_level', 0):.2f}
"""
    await update.message.reply_text(status)

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    plans = state.get("planned_events", [])
    if not plans:
        await update.message.reply_text("📋 Ei suunnitelmia.")
        return
    text = "📋 **SUUNNITELMAT:**\n\n"
    for i, plan in enumerate(plans[-10:], 1):
        text += f"{i}. {plan['description'][:100]}\n   Status: {plan['status']}\n\n"
    await update.message.reply_text(text)

async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with db_lock:
        cursor.execute("SELECT COUNT(*) FROM memories WHERE user_id=?", (str(user_id),))
        total = cursor.fetchone()[0]
    await update.message.reply_text(f"🧠 Muistoja yhteensä: {total}")

async def cmd_scene(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    args = context.args
    if not args:
        await update.message.reply_text("Käyttö: /scene home|work|public|bed|shower|commute|neutral")
        return
    new_scene = args[0].lower()
    valid = ["home", "work", "public", "bed", "shower", "commute", "neutral"]
    if new_scene not in valid:
        await update.message.reply_text(f"Virheellinen scene. Vaihtoehdot: {', '.join(valid)}")
        return
    now = time.time()
    _set_scene(state, new_scene, now)
    state["micro_context"] = random.choice(SCENE_MICRO.get(new_scene, [""]))
    await update.message.reply_text(f"✅ Scene vaihdettu: {new_scene}")

async def cmd_together(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    state["location_status"] = "together"
    state["with_user_physically"] = True
    await update.message.reply_text("✅ Olet nyt fyysisesti Meganin kanssa.")

async def cmd_separate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    state["location_status"] = "separate"
    state["with_user_physically"] = False
    await update.message.reply_text("✅ Et ole enää fyysisesti Meganin kanssa.")

async def cmd_mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    args = context.args
    if not args:
        await update.message.reply_text(f"Nykyinen mood: {state.get('emotional_mode', 'calm')}")
        return
    new_mood = args[0].lower()
    state["emotional_mode"] = new_mood
    await update.message.reply_text(f"✅ Emotional mode vaihdettu: {new_mood}")

async def cmd_tension(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    args = context.args
    if not args:
        await update.message.reply_text(f"Nykyinen tension: {state.get('tension', 0):.2f}")
        return
    try:
        new_t = float(args[0])
        state["tension"] = max(0.0, min(1.0, new_t))
        await update.message.reply_text(f"✅ Tension asetettu: {state['tension']:.2f}")
    except:
        await update.message.reply_text("Anna numero 0.0–1.0")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
🤖 **MEGAN 6.2 KOMENNOT**
/newgame – Reset session
/wipe – Poista kaikki muistot
/status – Näytä tila
/plans – Näytä suunnitelmat
/memory – Muistien määrä
/scene <scene> – Vaihda scene
/together – Fyysinen läsnäolo
/separate – Ei fyysistä läsnäoloa
/mood <mood> – Vaihda mood
/tension <0.0-1.0> – Aseta tension
/help – Tämä viesti
""")

# ====================== MAIN HANDLER ======================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        text = update.message.text.strip()
        if not text:
            return

        print(f"[USER {user_id}] {text}")

        t = text.lower()
        if any(x in t for x in ["lähetä kuva", "haluan kuvan", "tee kuva", "näytä kuva", "ota kuva"]):
            await handle_image_request(update, user_id, text)
            return

        state = get_or_create_state(user_id)
        state["last_interaction"] = time.time()

        memories = await retrieve_memories(user_id, text, limit=6)
        memory_context = "\n".join(memories)

        system_prompt = build_core_persona_prompt() + f"\n\nCurrent scene: {state['scene']}\nTension: {state.get('tension', 0):.2f}"

        history = conversation_history.setdefault(user_id, [])
        history.append({"role": "user", "content": text})
        history = history[-15:]

        messages = [{"role": "user", "content": f"{text}\n\nMuistikonteksti:\n{memory_context}"}]

        response = await grok_client.chat.completions.create(
            model="grok-4-1-fast",
            messages=messages,
            max_tokens=300,
            temperature=0.85
        )

        reply = response.choices[0].message.content.strip()

        await update.message.reply_text(reply)

        history.append({"role": "assistant", "content": reply})
        conversation_history[user_id] = history[-15:]

        mem_entry = json.dumps({"user": text, "assistant": reply, "timestamp": time.time()}, ensure_ascii=False)
        await store_memory(user_id, mem_entry)

    except Exception as e:
        print(f"[HANDLE ERROR] {e}")
        traceback.print_exc()
        await update.message.reply_text("Tapahtui virhe, yritä uudelleen.")

# ====================== BACKGROUND TASK ======================
async def check_proactive_triggers(application):
    while True:
        await asyncio.sleep(60)
        # Tässä voi olla myöhemmin proaktiivisia viestejä

# ====================== MAIN ======================
async def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("✅ Flask health check started")

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

    print("✅ Megan 6.2 käynnistyy...")

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
