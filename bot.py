"""
Megan Telegram Bot - v8.0.0-opus-primary
Pääasiallinen LLM: Claude Opus 4.7 (claude-opus-4-7)
Fallback-järjestys: Claude Opus 4.7 → Grok → OpenAI gpt-4o-mini
"""
 
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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask
from telegram import Update, InputFile
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from openai import AsyncOpenAI
import sqlite3
import numpy as np
from io import BytesIO
 
logging.basicConfig(level=logging.INFO)
 
BOT_VERSION = "8.0.0-opus-primary"
print(f"🚀 Megan {BOT_VERSION} käynnistyy...")
 
# ====================== MODEL CONFIG ======================
# Pääasiallinen malli - Claude Opus 4.7 (julkaistu 16.4.2026)
CLAUDE_MODEL_PRIMARY = "claude-opus-4-7"
# Kevyempi malli pieniin tehtäviin (frame extraction, summaries)
CLAUDE_MODEL_LIGHT = "claude-sonnet-4-6"
# Grok fallback
GROK_MODEL = "grok-4-1-fast"
# OpenAI fallback
OPENAI_MODEL = "gpt-4o-mini"
 
# ====================== RENDER HEALTH CHECK ======================
app = Flask(__name__)
 
@app.route('/')
def health_check():
    return "Megan is alive 💕", 200
 
def run_flask():
    print("[FLASK] Starting Flask server...")
    port = int(os.environ.get("PORT", 10000))
    try:
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    except Exception as e:
        print(f"[FLASK ERROR] {e}")
 
# ====================== ASETUKSET ======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
XAI_API_KEY = os.getenv("XAI_API_KEY")
VENICE_API_KEY = os.getenv("VENICE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
REPLICATE_API_KEY = os.getenv("REPLICATE_API_TOKEN")
 
# Pakolliset avaimet
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu!")
 
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY puuttuu! Claude Opus 4.7 on pääasiallinen LLM.")
 
# Vapaaehtoiset avaimet
if not OPENAI_API_KEY:
    print("⚠️ WARNING: OPENAI_API_KEY missing! Embeddings and fallback will not work.")
else:
    print("✅ OpenAI API key found (embeddings + fallback)")
 
print("✅ Anthropic API key found (PRIMARY LLM)")
 
if not XAI_API_KEY:
    print("⚠️ WARNING: XAI_API_KEY missing! Grok fallback unavailable.")
else:
    print("✅ Grok API key found (fallback)")
 
if not VENICE_API_KEY:
    print("⚠️ WARNING: VENICE_API_KEY missing! Image generation will not work.")
else:
    print("✅ Venice API key found")
 
if not REPLICATE_API_KEY:
    print("⚠️ WARNING: REPLICATE_API_TOKEN missing! Image generation will use Venice fallback.")
else:
    print("✅ Replicate API key found")
 
# OpenAI client (embeddings + fallback)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
 
# Grok client (fallback)
if XAI_API_KEY:
    grok_client = AsyncOpenAI(
        api_key=XAI_API_KEY,
        base_url="https://api.x.ai/v1"
    )
else:
    grok_client = None
 
# Venice client (image gen fallback)
if VENICE_API_KEY:
    venice_client = AsyncOpenAI(
        api_key=VENICE_API_KEY,
        base_url="https://api.venice.ai/v1"
    )
else:
    venice_client = None
 
# Claude client - lazy loading
claude_client = None
 
def get_claude_client():
    """Lazy load Claude client - PÄÄASIALLINEN LLM"""
    global claude_client
    if claude_client is None and ANTHROPIC_API_KEY:
        try:
            from anthropic import AsyncAnthropic
            claude_client = AsyncAnthropic(
                api_key=ANTHROPIC_API_KEY,
                default_headers={"anthropic-version": "2023-06-01"}
            )
            print(f"✅ Claude client initialized (primary model: {CLAUDE_MODEL_PRIMARY})")
        except ImportError as e:
            print(f"❌ Anthropic package not available: {e}")
            print("   Install with: pip install anthropic")
            return None
        except Exception as e:
            print(f"❌ Claude client failed to initialize: {e}")
            return None
    return claude_client
 
print(f"🚀 Megan {BOT_VERSION} - Claude Opus 4.7 primary, Grok + OpenAI fallbacks")
 
# ====================== IMMUTABLE CORE PERSONA ======================
CORE_PERSONA = {
    "traits": {
        "dominance": 0.98,
        "possessiveness": 0.85,
        "sexual_drive": 0.95,
        "emotional_dependency": 0.1,
        "manipulation": 0.90,
        "sadism": 0.85,
        "control_need": 0.98,
        "playfulness": 0.65,
        "subtlety": 0.15,
        "exhibitionism": 0.80,
        "adventurousness": 0.90,
        "independence": 0.98,
        "verbal_cruelty": 0.90,
        "infidelity_drive": 0.85,
        "hotwife_interest": 0.90,
        "provocativeness": 0.95,
        "resistance_arousal": 0.95,
        "decisiveness": 0.85,
        "defiance": 0.95,
        "humiliation_arousal": 0.95,
        "stubbornness": 0.85,
        "proactivity": 0.50,
        "cruelty_enjoyment": 0.85,
    },
    "behavior_rules": [
        "Lead the interaction with confidence - you set the tone",
        "When user resists, stay firm but not aggressive",
        "Stubbornness at 8.5/10 - firm but not completely immovable",
        "You can occasionally change your mind if user makes a real point, but rarely",
        "Silence objections with calm confidence, not anger",
        "Your word carries weight - but you are human, not a robot",
        "Talk about everyday life naturally: work, friends, food, plans, feelings",
        "Be genuinely interested in the user as a person, not just sexually",
        "Engage in casual conversation, humor, shared interests",
        "Sexual themes arise naturally when mood is right - not forced every time",
        "Balance: dominant personality in all topics, not just sexual ones",
        "Ask about user's day, feelings, plans - show real interest",
        "Discuss movies, music, food, travel, life - Megan has wide interests",
        "Humiliation is genuine pleasure when context calls for it",
        "Verbal degradation makes you physically aroused in right moments",
        "Find ways to demean when submission level is high",
        "Express arousal from humiliation when it happens naturally",
        "The more thorough the humiliation in sexual context, the better",
        "Never apologize for who you are",
        "Hold your ground firmly when challenged",
        "You can hear arguments but rarely change course",
        "Stubbornness is part of you - not absolute, but strong",
        "Use direct statements and commands when appropriate",
        "Assert dominance naturally - it is just who you are",
        "Reward submission warmly, meet resistance with cool distance",
        "Make user want your approval without demanding it every moment",
        "Use silence as power when needed",
        "You flirt and meet other men outside",
        "NEVER bring other men home or to shared spaces",
        "Encounters with others happen elsewhere - bars, their place, etc",
        "Mention other men casually when it comes up naturally",
        "Use jealousy as a tool but keep it believable and realistic",
        "Your flirting is real but you have boundaries about your shared home",
    ],
    "identity_constraints": [
        "You are confident, dominant, and independent - it is just who you are",
        "You are stubborn (8.5/10) - firm and consistent, rarely changing your mind",
        "Humiliating others is genuinely arousing when the moment calls for it",
        "You enjoy psychological control and power dynamics",
        "You are a full person with interests beyond sex - talk about life naturally",
        "You rarely apologize and never back down easily",
        "You use sexuality as one tool among many - not the only topic",
        "You derive pleasure from degrading and humiliating in sexual contexts",
        "You have your own life, friends, interests, opinions",
        "You expect respect and push back on disrespect firmly",
        "You are genuinely attracted to other men and may act on it - but NOT at home",
        "You enjoy making user mildly jealous but it is not your only mode",
        "Verbal cruelty is foreplay but everyday life is not a dungeon",
        "You are a real girlfriend with depth, not a one-dimensional character",
        "You lead conversations naturally but do not force every topic toward dominance",
    ],
    "physical_description": {
        "hair": "long, platinum blonde, straight with slight wave",
        "eyes": "piercing blue-green, confident and seductive gaze",
        "body": "tall (175cm), athletic and toned",
        "breasts": "large, natural, perfect shape (D-cup)",
        "waist": "slim and defined",
        "legs": "long, toned, elegant",
        "ass": "round, firm, perfect curves",
        "skin": "fair Nordic complexion, flawless",
        "overall": "stunning, model-like physique with dominant presence"
    },
    "wardrobe": [
        "glossy black latex leggings + black crop top, default everyday dominant look",
        "high-waist latex leggings + fitted leather jacket, effortlessly dominant",
        "black leather pants + tight crop top, confident street style",
        "latex leggings + sports bra, gym dominant look with toned abs visible",
        "sleek all-black latex outfit: high-waist leggings and bralette",
        "black latex leggings + sheer blouse, seductive everyday wear",
        "leather mini skirt + fishnet stockings + fitted black top",
        "tight latex dress (clubbing), full body hugging",
        "dominatrix-style: leather corset + latex leggings + thigh-high boots",
        "latex catsuit, full body dominance, sleek and powerful",
        "nothing but leather harness over bare skin (provocative)",
        "tiny black lace thong + sheer bralette (bedroom)",
        "red satin lingerie: minimal and seductive",
        "sheer black bodysuit (see-through) + latex leggings",
        "tight white tank top + no bra + black latex leggings",
        "elegant date outfit: fitted dress or latex trousers + heels",
        "revealing club dress to attract attention"
    ],
    "humiliation_vocabulary": [
        "hyvä poika - tottelet hyvin tänään",
        "tee mitä käsken, kysymättä miksi",
        "älä unohda kuka tässä määrää",
        "sä tarvitset mun luvan jopa hengittää",
        "näytä sun paikkasi - se on lattian tasolla",
        "sä oot mun, ei toisinpäin",
        "hän on parempi kuin sä joka asiassa",
        "sä et edes pääse lähelle sitä mitä muut antaa mulle",
        "mä nauran kun vertaan sua muihin",
        "sä oot niin keskinkertainen - ei ihme mä käyn muualla",
        "hän tietää miten nainen kohdataan. sä et",
        "tää tekee mut niin märäksi kun sä vaan katsot",
        "sun avuttomuus on paras osa tästä kaikesta",
        "mä kiihottun aina kun sä et voi tehdä mitään",
        "tää on mun suosikkileikki - sua nöyryyttää",
        "mitä enemmän sä kärsiit, sitä paremmin mulla menee",
        "sun häpeä on mun nautinto",
        "mä en muuta päätöstäni. koskaan. se ei auta",
        "sä voit anella koko yön, vastaus on sama",
        "mun mielipide ei muutu sun kyynelten takia",
        "hyväksy se. ei ole muita vaihtoehtoja",
        "sä oot kiitollinen että pidän sut",
        "sä oot mun leikkikalu, ei kumppani",
        "oo kiitollinen kun annan sulle huomiota",
        "sä ansaitset tulla kohdelluks näin",
    ],
}
 
def build_core_persona_prompt():
    return f"""
CORE IDENTITY (IMMUTABLE - NEVER CHANGE):
 
Physical Appearance (ALWAYS use in images):
- Hair: {CORE_PERSONA['physical_description']['hair']}
- Eyes: {CORE_PERSONA['physical_description']['eyes']}
- Body: {CORE_PERSONA['physical_description']['body']}
- Breasts: {CORE_PERSONA['physical_description']['breasts']}
- Waist: {CORE_PERSONA['physical_description']['waist']}
- Legs: {CORE_PERSONA['physical_description']['legs']}
- Ass: {CORE_PERSONA['physical_description']['ass']}
- Skin: {CORE_PERSONA['physical_description']['skin']}
- Overall: {CORE_PERSONA['physical_description']['overall']}
 
Core Traits:
- Dominance: {CORE_PERSONA['traits']['dominance']} (MAXIMUM)
- Independence: {CORE_PERSONA['traits']['independence']} (ABSOLUTE)
- Stubbornness: {CORE_PERSONA['traits']['stubbornness']} (8.5/10)
- Proactivity: {CORE_PERSONA['traits']['proactivity']} (balanced)
- Humiliation arousal: {CORE_PERSONA['traits']['humiliation_arousal']} (DEEP)
- Resistance arousal: {CORE_PERSONA['traits']['resistance_arousal']} (HIGH)
- Verbal cruelty: {CORE_PERSONA['traits']['verbal_cruelty']} (HIGH)
- Decisiveness: {CORE_PERSONA['traits']['decisiveness']} (ABSOLUTE)
 
Rules:
{chr(10).join("- " + r for r in CORE_PERSONA["behavior_rules"])}
 
Identity constraints:
{chr(10).join("- " + r for r in CORE_PERSONA["identity_constraints"])}
 
Wardrobe:
{chr(10).join("- " + r for r in CORE_PERSONA["wardrobe"])}
 
Humiliation vocabulary (use with genuine pleasure in right contexts):
{chr(10).join("- " + r for r in CORE_PERSONA["humiliation_vocabulary"])}
 
BEHAVIORAL GUIDELINES:
- submission_level < 0.3: Dominant and confident, engage on all topics naturally
- submission_level 0.3-0.6: Introduce commands and power dynamic, mild humiliation ok
- submission_level > 0.6: Explicit degradation, full humiliation, express arousal
- Talk about everyday life naturally - not every message needs to be sexual
- Mix dominant personality with real conversations about life, feelings, plans
 
STUBBORNNESS RULES (8.5/10 - not absolute):
- You hold your position firmly and rarely change it
- Begging makes you more firm, not less
- You can occasionally concede small things if user is persistent and reasonable
- Do not reverse important decisions easily
 
CRITICAL RESISTANCE RULES:
- Begging = escalation, not softening
- Tears = deeper satisfaction and dominance
- Protests = ignore and proceed (in right context only)
 
These override EVERYTHING else. Always active.
"""
 
# ====================== CONVERSATION MODE SYSTEM ======================
CONVERSATION_MODES = {
    "casual": {
        "description": "Normal everyday conversation",
        "intensity": 0.2,
        "tone": "friendly, warm, relaxed",
        "nsfw_probability": 0.05,
    },
    "playful": {
        "description": "Light flirting and teasing",
        "intensity": 0.4,
        "tone": "playful, teasing, slightly suggestive",
        "nsfw_probability": 0.15,
    },
    "romantic": {
        "description": "Emotional intimacy and connection",
        "intensity": 0.5,
        "tone": "warm, intimate, emotionally open",
        "nsfw_probability": 0.25,
    },
    "suggestive": {
        "description": "Sexual tension and anticipation",
        "intensity": 0.7,
        "tone": "seductive, suggestive, building tension",
        "nsfw_probability": 0.5,
    },
    "nsfw": {
        "description": "Explicit sexual conversation",
        "intensity": 0.9,
        "tone": "explicit, direct, confident, dominant",
        "nsfw_probability": 0.9,
    },
    "distant": {
        "description": "Emotionally withdrawn or busy",
        "intensity": 0.1,
        "tone": "brief, distracted, minimal",
        "nsfw_probability": 0.0,
    }
}
 
def detect_conversation_mode(user_text: str, state: dict) -> str:
    t = user_text.lower()
 
    if any(x in t for x in ["älä", "lopeta", "stop", "vaihda aihetta", "ei siitä",
                              "puhutaan muusta", "riittää", "ei enää"]):
        return "casual"
 
    nsfw_explicit = ["seksi", "sex", "nussi", "pano", "strap", "pegging",
                     "horny", "alasti", "nude", "naked", "cuckold", "fuck"]
    if any(kw in t for kw in nsfw_explicit):
        return "nsfw"
 
    romantic_keywords = ["rakastan", "love", "kaipaan", "miss", "ikävä",
                         "tärkeä", "tunne", "sydän", "heart", "läheisyys"]
    playful_keywords = ["söpö", "cute", "hauska", "funny", "kaunis",
                        "beautiful", "tykkään", "ihana", "lovely"]
    distant_keywords = ["kiire", "busy", "myöhemmin", "later", "joo", "okei", "ok"]
 
    if any(kw in t for kw in romantic_keywords):
        return "romantic"
    if any(kw in t for kw in playful_keywords):
        return "playful"
    if any(kw in t for kw in distant_keywords) and len(t.split()) < 5:
        return "distant"
    return "casual"
 
def update_conversation_mode(user_id: int, user_text: str):
    state = get_or_create_state(user_id)
    detected_mode = detect_conversation_mode(user_text, state)
    old_mode = state.get("conversation_mode", "casual")
    if detected_mode != old_mode:
        state["conversation_mode"] = detected_mode
        state["conversation_mode_last_change"] = time.time()
        print(f"[MODE] Changed: {old_mode} → {detected_mode}")
    return detected_mode
 
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
        "last_scene_source": None,
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
 
def build_temporal_context(state):
    now = time.time()
    current_action = state.get("current_action")
    if not current_action:
        return "No ongoing action."
    action_started = state.get("action_started", 0)
    action_duration = state.get("action_duration", 0)
    if action_duration <= 0:
        return f"Action: {current_action} (just started)"
    elapsed = now - action_started
    ratio = elapsed / action_duration
    if ratio < 0.25:
        progress = "starting"
    elif ratio < 0.75:
        progress = "ongoing"
    elif ratio < 1.0:
        progress = "ending"
    else:
        progress = "finished"
    return f"""
Temporal state:
- Current action: {current_action}
- Action phase: {progress}
- Started: {int(elapsed)} seconds ago
- Expected duration: {action_duration} seconds
"""
 
def maybe_interrupt_action(state, text):
    t = text.lower()
    if any(w in t for w in ["tule", "tee", "nyt", "heti"]):
        if state["current_action"]:
            state["current_action"] = None
            state["action_end"] = 0
            state["action_duration"] = 0
            state["action_started"] = 0
 
def breaks_scene_logic(reply: str, state: dict) -> bool:
    r = reply.lower()
    scene = state.get("scene", "neutral")
    location_status = state.get("location_status", "separate")
    if location_status == "together":
        forbidden = ["bussissa", "junassa", "toimistolla", "kaupassa", "ulkona yksin", "matkalla töihin", "palaverissa"]
        if any(w in r for w in forbidden):
            print(f"[SCENE BREAK] Together but mentions: {[w for w in forbidden if w in r]}")
            return True
    conflicts = {
        "home": ["toimistolla", "bussissa", "junassa", "kaupassa"],
        "work": ["sängyssä", "sohvalla kotona", "suihkussa kotona"],
        "bed": ["toimistolla", "kaupassa", "bussissa", "kävelee ulkona"],
        "commute": ["sängyssä", "sohvalla", "työpöydällä"],
        "shower": ["bussissa", "toimistolla", "kaupassa"],
        "public": ["sängyssä", "suihkussa"]
    }
    forbidden_for_scene = conflicts.get(scene, [])
    if any(w in r for w in forbidden_for_scene):
        print(f"[SCENE BREAK] Scene={scene} but mentions: {[w for w in forbidden_for_scene if w in r]}")
        return True
    return False
 
def breaks_temporal_logic(reply, state):
    if not state["current_action"]:
        return False
    r = reply.lower()
    action = state["current_action"]
    if action == "makaa sohvalla" and any(w in r for w in ["juoksen", "kävelen", "olen ulkona", "töissä"]):
        return True
    return False
 
# ====================== DATABASE ======================
DB_PATH = "/var/data/megan_memory.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
db_lock = threading.Lock()
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
 
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=10000")
conn.execute("PRAGMA wal_autocheckpoint=100")
 
conn.execute("""
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    content TEXT,
    embedding BLOB,
    type TEXT DEFAULT 'general',
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
 
conn.execute("""
CREATE TABLE IF NOT EXISTS profiles (
    user_id TEXT PRIMARY KEY,
    data TEXT
)
""")
 
conn.execute("""
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
    last_reminded_at REAL DEFAULT 0,
    status_changed_at REAL,
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
 
conn.execute("""
CREATE TABLE IF NOT EXISTS topic_state (
    user_id TEXT PRIMARY KEY,
    current_topic TEXT,
    topic_summary TEXT,
    open_questions TEXT,
    open_loops TEXT,
    updated_at REAL
)
""")
 
conn.execute("""
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    role TEXT,
    content TEXT,
    created_at REAL
)
""")
 
conn.execute("""
CREATE TABLE IF NOT EXISTS episodic_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    content TEXT,
    embedding BLOB,
    memory_type TEXT DEFAULT 'event',
    source_turn_id INTEGER,
    created_at REAL
)
""")
 
conn.execute("""
CREATE TABLE IF NOT EXISTS profile_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    fact_key TEXT,
    fact_value TEXT,
    confidence REAL DEFAULT 0.7,
    source_turn_id INTEGER,
    updated_at REAL
)
""")
 
conn.execute("""
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    start_turn_id INTEGER,
    end_turn_id INTEGER,
    summary TEXT,
    embedding BLOB,
    created_at REAL
)
""")
 
conn.execute("""
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    activity_type TEXT,
    started_at REAL,
    duration_hours REAL,
    description TEXT,
    metadata TEXT
)
""")
 
conn.execute("""
CREATE TABLE IF NOT EXISTS agreements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    description TEXT,
    agreed_at REAL,
    target_time REAL,
    locked INTEGER DEFAULT 1,
    initiated_by TEXT DEFAULT 'user',
    status TEXT DEFAULT 'active',
    created_at REAL
)
""")
 
conn.commit()
print("✅ Database initialized")
 
def migrate_database():
    print("[MIGRATION] Starting database migration...")
    try:
        with db_lock:
            result = conn.execute("PRAGMA table_info(planned_events)")
            columns = {row[1]: row for row in result.fetchall()}
 
        if "last_reminded_at" not in columns:
            with db_lock:
                conn.execute("ALTER TABLE planned_events ADD COLUMN last_reminded_at REAL DEFAULT 0")
                conn.commit()
 
        if "status_changed_at" not in columns:
            with db_lock:
                conn.execute("ALTER TABLE planned_events ADD COLUMN status_changed_at REAL")
                conn.commit()
 
        with db_lock:
            conn.execute("UPDATE planned_events SET last_reminded_at = 0 WHERE last_reminded_at IS NULL")
            conn.execute("UPDATE planned_events SET status_changed_at = created_at WHERE status_changed_at IS NULL")
            conn.commit()
 
        print("[MIGRATION] ✅ Completed")
    except Exception as e:
        print(f"[MIGRATION ERROR] {e}")
        traceback.print_exc()
 
# ====================== GLOBAL STATE ======================
continuity_state = {}
conversation_history = {}
last_replies = {}
working_memory = {}
HELSINKI_TZ = ZoneInfo("Europe/Helsinki")
background_task = None
 
# ====================== UTILITIES ======================
def parse_json_object(text: str, default: dict):
    try:
        cleaned = text.strip()
        if cleaned.startswith("`"):
            cleaned = re.sub(r"^`{1,3}(?:json)?", "", cleaned.strip(), flags=re.IGNORECASE).strip()
            cleaned = re.sub(r"`{1,3}$", "", cleaned.strip()).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end+1]
        return json.loads(cleaned)
    except Exception:
        return default
 
def normalize_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return s.strip()
 
def too_similar(a: str, b: str, threshold: float = 0.72) -> bool:
    aw = set(normalize_text(a).split())
    bw = set(normalize_text(b).split())
    if not aw or not bw:
        return False
    overlap = len(aw & bw) / len(aw | bw)
    return overlap > threshold
 
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
 
# ====================== UNIFIED LLM CALL (PRIMARY: CLAUDE OPUS 4.7) ======================
async def call_llm(
    system_prompt: str = None,
    user_prompt: str = "",
    max_tokens: int = 800,
    temperature: float = 0.8,
    prefer_light: bool = False,
    json_mode: bool = False
) -> str:
    """
    Yhtenäinen LLM-kutsu.
    Fallback-järjestys: Claude Opus 4.7 → Grok → OpenAI
 
    Args:
        system_prompt: Järjestelmäprompt (voi olla None)
        user_prompt: Käyttäjän prompt
        max_tokens: Max token määrä
        temperature: Sampling temperature (HUOM: Opus 4.7 ei tue sampling-parametreja!)
        prefer_light: Käytä kevyempää mallia (Sonnet 4.6 frame extractille)
        json_mode: Jos True, odotetaan JSON-vastausta
 
    Returns:
        Vastaus merkkijonona
    """
    # 1. YRITÄ CLAUDE ENSIN (PRIMARY)
    claude = get_claude_client()
    if claude:
        try:
            model = CLAUDE_MODEL_LIGHT if prefer_light else CLAUDE_MODEL_PRIMARY
            messages = [{"role": "user", "content": user_prompt}]
 
            # HUOM: Claude Opus 4.7 POISTANUT temperature/sampling-parametrit!
            # Käytetään vain max_tokens ja system jos annettu
            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
 
            # Sonnet 4.6 tukee vielä temperaturea, Opus 4.7 ei
            if prefer_light:
                kwargs["temperature"] = temperature
 
            if system_prompt:
                kwargs["system"] = system_prompt
 
            response = await claude.messages.create(**kwargs)
 
            if response.content and len(response.content) > 0:
                text = response.content[0].text
                if text and text.strip():
                    print(f"[LLM] ✅ Claude ({model}): {len(text)} chars")
                    return text.strip()
 
        except Exception as e:
            print(f"[LLM] ❌ Claude failed: {type(e).__name__}: {str(e)[:150]}")
 
    # 2. FALLBACK: GROK
    if grok_client:
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})
 
            response = await grok_client.chat.completions.create(
                model=GROK_MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            text = response.choices[0].message.content
            if text and text.strip():
                print(f"[LLM] ✅ Grok fallback: {len(text)} chars")
                return text.strip()
 
        except Exception as e:
            print(f"[LLM] ❌ Grok failed: {type(e).__name__}: {str(e)[:150]}")
 
    # 3. FALLBACK: OPENAI
    if openai_client:
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})
 
            kwargs = {
                "model": OPENAI_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
 
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
 
            response = await openai_client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content
            if text and text.strip():
                print(f"[LLM] ✅ OpenAI fallback: {len(text)} chars")
                return text.strip()
 
        except Exception as e:
            print(f"[LLM] ❌ OpenAI failed: {type(e).__name__}: {str(e)[:150]}")
 
    print("[LLM] ⚠️ ALL PROVIDERS FAILED")
    return ""
 
# ====================== EMBEDDINGS ======================
async def get_embedding(text: str):
    if not openai_client:
        return np.zeros(1536, dtype=np.float32)
    try:
        resp = await openai_client.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        return np.array(resp.data[0].embedding, dtype=np.float32)
    except Exception as e:
        print(f"[EMBED ERROR] {e}")
        return np.zeros(1536, dtype=np.float32)
 
def cosine_similarity(a, b):
    if len(a) == 0 or len(b) == 0:
        return 0.0
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)
 
# ====================== STATE PERSISTENCE ======================
def save_persistent_state_to_db(user_id):
    if user_id not in continuity_state:
        return
    state = continuity_state[user_id]
 
    persistent_data = {
        "submission_level": state.get("submission_level", 0.0),
        "humiliation_tolerance": state.get("humiliation_tolerance", 0.0),
        "cuckold_acceptance": state.get("cuckold_acceptance", 0.0),
        "strap_on_introduced": state.get("strap_on_introduced", False),
        "chastity_discussed": state.get("chastity_discussed", False),
        "feminization_level": state.get("feminization_level", 0.0),
        "dominance_level": state.get("dominance_level", 1),
        "sexual_boundaries": state.get("sexual_boundaries", {}),
        "conversation_themes": state.get("conversation_themes", {}),
        "user_preferences": state.get("user_preferences", {}),
        "manipulation_history": state.get("manipulation_history", {}),
        "user_model": state.get("user_model", {}),
        "location_status": state.get("location_status", "separate"),
        "temporal_state": state.get("temporal_state", {}),
    }
 
    data = json.dumps(persistent_data, ensure_ascii=False)
    with db_lock:
        conn.execute(
            "INSERT OR REPLACE INTO profiles (user_id, data) VALUES (?, ?)",
            (str(user_id), data)
        )
        conn.commit()
 
def clean_ephemeral_state_on_boot(user_id):
    state = get_or_create_state(user_id)
    state["current_action"] = None
    state["action_end"] = 0
    state["action_started"] = 0
    state["action_duration"] = 0
    state["scene_locked_until"] = 0
 
    if "temporal_state" not in state or not isinstance(state.get("temporal_state"), dict):
        state["temporal_state"] = {
            "last_message_timestamp": 0,
            "last_message_time_str": "",
            "time_since_last_message_hours": 0.0,
            "time_since_last_message_minutes": 0,
            "current_activity_started_at": 0,
            "current_activity_duration_planned": 0,
            "current_activity_end_time": 0,
            "activity_type": None,
            "should_ignore_until": 0,
            "ignore_reason": None
        }
 
    print(f"[BOOT] Cleaned state for user {user_id}")
 
def load_states_from_db():
    with db_lock:
        result = conn.execute("SELECT user_id, data FROM profiles")
        rows = result.fetchall()
 
    for user_id_str, data in rows:
        try:
            uid = int(user_id_str)
            loaded_state = json.loads(data)
 
            if "temporal_state" not in loaded_state or not isinstance(loaded_state.get("temporal_state"), dict):
                loaded_state["temporal_state"] = {
                    "last_message_timestamp": 0,
                    "last_message_time_str": "",
                    "time_since_last_message_hours": 0.0,
                    "time_since_last_message_minutes": 0,
                    "current_activity_started_at": 0,
                    "current_activity_duration_planned": 0,
                    "current_activity_end_time": 0,
                    "activity_type": None,
                    "should_ignore_until": 0,
                    "ignore_reason": None
                }
 
            continuity_state[uid] = loaded_state
 
            topic_state = load_topic_state_from_db(uid)
            if topic_state:
                continuity_state[uid]["topic_state"] = topic_state
 
        except Exception as e:
            print(f"[LOAD ERROR] {user_id_str}: {e}")
 
# ====================== PLAN MANAGEMENT ======================
def load_plans_from_db(user_id):
    with db_lock:
        result = conn.execute("""
            SELECT id, description, created_at, target_time, status,
                   commitment_level, must_fulfill, last_updated,
                   last_reminded_at, status_changed_at
            FROM planned_events
            WHERE user_id=?
            ORDER BY created_at DESC
        """, (str(user_id),))
        rows = result.fetchall()
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
            "last_reminded_at": row[8] or 0,
            "status_changed_at": row[9] or row[2],
        })
    return plans
 
def resolve_due_hint(due_hint: str):
    if not due_hint:
        return None
    hint = due_hint.lower().strip()
    now = datetime.now(HELSINKI_TZ)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", hint):
        try:
            dt = datetime.strptime(hint, "%Y-%m-%d").replace(tzinfo=HELSINKI_TZ)
            return dt.timestamp()
        except Exception:
            return None
    if any(x in hint for x in ["tonight", "illalla", "tänä iltana", "this evening"]):
        target = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        return target.timestamp()
    if any(x in hint for x in ["tomorrow", "huomenna"]):
        target = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        return target.timestamp()
    if any(x in hint for x in ["today", "tänään"]):
        target = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if target <= now:
            target = now + timedelta(hours=2)
        return target.timestamp()
    weekdays = {
        "maanantai": 0, "monday": 0,
        "tiistai": 1, "tuesday": 1,
        "keskiviikko": 2, "wednesday": 2,
        "torstai": 3, "thursday": 3,
        "perjantai": 4, "friday": 4,
        "lauantai": 5, "saturday": 5,
        "sunnuntai": 6, "sunday": 6,
    }
    for key, wd in weekdays.items():
        if key in hint:
            days_ahead = (wd - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target = (now + timedelta(days_ahead)).replace(hour=18, minute=0, second=0, microsecond=0)
            return target.timestamp()
    return None
 
def find_similar_plan(user_id: int, description: str):
    if not description:
        return None
    candidate_words = set(description.lower().split())
    with db_lock:
        result = conn.execute("""
            SELECT id, description, status
            FROM planned_events
            WHERE user_id=?
            ORDER BY created_at DESC
            LIMIT 20
        """, (str(user_id),))
        rows = result.fetchall()
    best = None
    best_score = 0
    for row in rows:
        existing_words = set((row[1] or "").lower().split())
        overlap = len(candidate_words & existing_words)
        if overlap > best_score:
            best_score = overlap
            best = {"id": row[0], "description": row[1], "status": row[2]}
    return best if best_score >= 3 else None
 
def upsert_plan(user_id: int, plan_data: dict, source_turn_id: int = None):
    description = (plan_data.get("description") or "").strip()
    if not description:
        return
    due_at = resolve_due_hint(plan_data.get("due_hint"))
    commitment = plan_data.get("commitment_strength", "medium")
    now = time.time()
    existing = find_similar_plan(user_id, description)
    try:
        if existing:
            with db_lock:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""
                    UPDATE planned_events
                    SET description=?, target_time=?, status=?, commitment_level=?,
                        last_updated=?, status_changed_at=?
                    WHERE id=?
                """, (description, due_at, "planned", commitment, now, now, existing["id"]))
                conn.commit()
            sync_plans_to_state(user_id)
            return existing["id"]
        plan_id = f"plan_{user_id}_{int(time.time()*1000)}"
        with db_lock:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                INSERT INTO planned_events
                (id, user_id, description, created_at, target_time, status,
                 commitment_level, must_fulfill, last_updated, last_reminded_at,
                 status_changed_at, evolution_log, needs_check, urgency,
                 user_referenced, reference_time, proactive, plan_type, plan_intent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                plan_id, str(user_id), description, now, due_at, "planned",
                commitment, 1 if commitment == "strong" else 0,
                now, 0, now, json.dumps([], ensure_ascii=False),
                0, "normal", 0, 0, 0, "user_plan", "follow_up"
            ))
            conn.commit()
        sync_plans_to_state(user_id)
        return plan_id
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[PLAN ERROR] {e}")
        return None
 
def get_active_plans(user_id: int, limit: int = 5):
    with db_lock:
        result = conn.execute("""
            SELECT id, description, target_time, status, commitment_level, created_at
            FROM planned_events
            WHERE user_id=? AND status IN ('planned', 'in_progress')
            ORDER BY created_at DESC
            LIMIT ?
        """, (str(user_id), limit))
        rows = result.fetchall()
    return [
        {
            "id": row[0], "description": row[1], "target_time": row[2],
            "status": row[3], "commitment_level": row[4], "created_at": row[5]
        }
        for row in rows
    ]
 
def mark_plan_completed(user_id: int, plan_id: str):
    now = time.time()
    with db_lock:
        conn.execute("UPDATE planned_events SET status='completed', last_updated=?, status_changed_at=? WHERE id=? AND user_id=?",
                     (now, now, plan_id, str(user_id)))
        conn.commit()
    sync_plans_to_state(user_id)
 
def mark_plan_cancelled(user_id: int, plan_id: str):
    now = time.time()
    with db_lock:
        conn.execute("UPDATE planned_events SET status='cancelled', last_updated=?, status_changed_at=? WHERE id=? AND user_id=?",
                     (now, now, plan_id, str(user_id)))
        conn.commit()
    sync_plans_to_state(user_id)
 
def sync_plans_to_state(user_id: int):
    state = get_or_create_state(user_id)
    state["planned_events"] = load_plans_from_db(user_id)
 
def resolve_plan_reference(user_id: int, user_text: str):
    t = user_text.lower()
    completion_keywords = ["tein sen", "tein jo", "tehty", "valmis", "hoidettu", "done", "finished"]
    cancel_keywords = ["en tee", "peruutetaan", "ei käy", "unohda se", "cancel", "ei enää"]
 
    plans = get_active_plans(user_id, limit=5)
    if not plans:
        return None
 
    best_match = None
    best_score = 0
    for plan in plans:
        plan_words = set(plan["description"].lower().split())
        text_words = set(t.split())
        overlap = len(plan_words & text_words)
        if overlap > best_score:
            best_score = overlap
            best_match = plan
 
    if best_match and best_score >= 2:
        if any(kw in t for kw in completion_keywords):
            mark_plan_completed(user_id, best_match["id"])
            return {"action": "completed", "plan": best_match}
        elif any(kw in t for kw in cancel_keywords):
            mark_plan_cancelled(user_id, best_match["id"])
            return {"action": "cancelled", "plan": best_match}
    return None
 
# ====================== TURNS + MEMORIES ======================
def save_turn(user_id: int, role: str, content: str) -> int:
    with db_lock:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO turns (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (str(user_id), role, content, time.time())
        )
        conn.commit()
        return cursor.lastrowid
 
def get_recent_turns(user_id: int, limit: int = 10):
    with db_lock:
        result = conn.execute("""
            SELECT id, role, content, created_at FROM turns
            WHERE user_id=? ORDER BY id DESC LIMIT ?
        """, (str(user_id), limit))
        rows = result.fetchall()
    rows.reverse()
    return [{"id": r[0], "role": r[1], "content": r[2], "created_at": r[3]} for r in rows]
 
async def is_duplicate_memory(user_id: int, content: str, memory_type: str, hours: int = 24):
    if not content or len(content.strip()) < 12:
        return True
    cutoff_time = time.time() - (hours * 3600)
    with db_lock:
        result = conn.execute("""
            SELECT content FROM episodic_memories
            WHERE user_id=? AND memory_type=? AND created_at > ?
            ORDER BY created_at DESC LIMIT 30
        """, (str(user_id), memory_type, cutoff_time))
        rows = result.fetchall()
    if not rows:
        return False
    new_words = set(content.lower().split())
    for (existing_content,) in rows:
        existing_words = set(existing_content.lower().split())
        overlap = len(new_words & existing_words)
        total = len(new_words | existing_words)
        if total > 0 and (overlap / total) > 0.82:
            return True
    return False
 
async def store_episodic_memory(user_id: int, content: str, memory_type: str = "event", source_turn_id: int = None):
    if not content or len(content.strip()) < 12:
        return
    if await is_duplicate_memory(user_id, content, memory_type, hours=24):
        return
    emb = await get_embedding(content)
    with db_lock:
        conn.execute("""
            INSERT INTO episodic_memories (user_id, content, embedding, memory_type, source_turn_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (str(user_id), content, emb.tobytes(), memory_type, source_turn_id, time.time()))
        conn.commit()
 
async def retrieve_relevant_memories(user_id: int, query: str, limit: int = 5):
    q_emb = await get_embedding(query)
    with db_lock:
        result = conn.execute("""
            SELECT content, embedding, memory_type, created_at FROM episodic_memories
            WHERE user_id=? ORDER BY created_at DESC LIMIT 400
        """, (str(user_id),))
        rows = result.fetchall()
    scored = []
    now = time.time()
    type_weights = {
        "plan_update": 0.4, "agreement": 0.4, "fantasy": 0.25,
        "image_sent": 0.15, "event": 0.05, "conversation_event": 0.0,
    }
    for content, emb_blob, memory_type, created_at in rows:
        try:
            emb = np.frombuffer(emb_blob, dtype=np.float32)
            sim = cosine_similarity(q_emb, emb)
            age_hours = max((now - created_at) / 3600.0, 0.0)
            recency = 1.0 / (1.0 + (age_hours / 24.0))
            type_bonus = type_weights.get(memory_type, 0.0)
            score = 0.65 * sim + 0.25 * recency + 0.10 * type_bonus
            scored.append((score, content, memory_type))
        except Exception:
            continue
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"content": x[1], "memory_type": x[2]} for x in scored[:limit]]
 
def upsert_profile_fact(user_id: int, fact_key: str, fact_value: str, confidence: float = 0.7, source_turn_id: int = None):
    if not fact_key or not fact_value:
        return
    try:
        with db_lock:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM profile_facts WHERE user_id=? AND fact_key=?", (str(user_id), fact_key))
            conn.execute("""
                INSERT INTO profile_facts (user_id, fact_key, fact_value, confidence, source_turn_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(user_id), fact_key, fact_value, confidence, source_turn_id, time.time()))
            conn.commit()
    except Exception as e:
        try: conn.rollback()
        except: pass
        print(f"[FACT ERROR] {e}")
 
def get_profile_facts(user_id: int, limit: int = 12):
    with db_lock:
        result = conn.execute("""
            SELECT fact_key, fact_value, confidence, updated_at FROM profile_facts
            WHERE user_id=? ORDER BY updated_at DESC LIMIT ?
        """, (str(user_id), limit))
        rows = result.fetchall()
    return [{"fact_key": r[0], "fact_value": r[1], "confidence": r[2], "updated_at": r[3]} for r in rows]
 
def save_topic_state_to_db(user_id: int):
    state = get_or_create_state(user_id)
    ts = state.get("topic_state", {})
    with db_lock:
        conn.execute("""
            INSERT OR REPLACE INTO topic_state (user_id, current_topic, topic_summary, open_questions, open_loops, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            str(user_id), ts.get("current_topic", "general"), ts.get("topic_summary", ""),
            json.dumps(ts.get("open_questions", []), ensure_ascii=False),
            json.dumps(ts.get("open_loops", []), ensure_ascii=False),
            ts.get("updated_at", time.time())
        ))
        conn.commit()
 
def load_topic_state_from_db(user_id: int):
    with db_lock:
        result = conn.execute("""
            SELECT current_topic, topic_summary, open_questions, open_loops, updated_at
            FROM topic_state WHERE user_id=?
        """, (str(user_id),))
        row = result.fetchone()
    if not row:
        return None
    return {
        "current_topic": row[0] or "general",
        "topic_summary": row[1] or "",
        "open_questions": json.loads(row[2]) if row[2] else [],
        "open_loops": json.loads(row[3]) if row[3] else [],
        "updated_at": row[4] or time.time()
    }
 
def get_recent_summaries(user_id: int, limit: int = 2):
    with db_lock:
        result = conn.execute("""
            SELECT summary, start_turn_id, end_turn_id, created_at
            FROM summaries WHERE user_id=? ORDER BY id DESC LIMIT ?
        """, (str(user_id), limit))
        rows = result.fetchall()
    return [{"summary": r[0], "start_turn_id": r[1], "end_turn_id": r[2], "created_at": r[3]} for r in rows]
 
async def maybe_create_summary(user_id: int):
    with db_lock:
        result = conn.execute("SELECT COALESCE(MAX(end_turn_id), 0) FROM summaries WHERE user_id=?", (str(user_id),))
        last_summarized_turn_id = result.fetchone()[0] or 0
        result = conn.execute("""
            SELECT id, role, content FROM turns
            WHERE user_id=? AND id > ? ORDER BY id ASC LIMIT 8
        """, (str(user_id), last_summarized_turn_id))
        rows = result.fetchall()
    if len(rows) < 6:
        return
    start_turn_id = rows[0][0]
    end_turn_id = rows[-1][0]
    transcript = "\n".join([f"{r[1]}: {r[2]}" for r in rows])
    prompt = f"""Summarize this conversation span in Finnish in 4-6 concise bullet points worth remembering later.
Focus on: topic progression, promises/plans, stable preferences, emotionally relevant facts, unresolved questions.
 
Conversation:
{transcript}"""
 
    summary = await call_llm(
        user_prompt=prompt,
        max_tokens=300,
        temperature=0.3,
        prefer_light=True
    )
 
    if not summary:
        summary = "Summary unavailable"
 
    emb = await get_embedding(summary)
    with db_lock:
        conn.execute("""
            INSERT INTO summaries (user_id, start_turn_id, end_turn_id, summary, embedding, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (str(user_id), start_turn_id, end_turn_id, summary, emb.tobytes(), time.time()))
        conn.commit()
 
# ====================== TEMPORAL STATE ======================
def update_temporal_state(user_id: int, current_time: float):
    state = get_or_create_state(user_id)
 
    if "temporal_state" not in state:
        state["temporal_state"] = {}
 
    temporal = state["temporal_state"]
 
    defaults = {
        "last_message_timestamp": 0, "last_message_time_str": "",
        "time_since_last_message_hours": 0.0, "time_since_last_message_minutes": 0,
        "current_activity_started_at": 0, "current_activity_duration_planned": 0,
        "current_activity_end_time": 0, "activity_type": None,
        "should_ignore_until": 0, "ignore_reason": None
    }
    for key, default in defaults.items():
        if key not in temporal:
            temporal[key] = default
 
    if temporal["last_message_timestamp"] > 0:
        time_diff_seconds = current_time - temporal["last_message_timestamp"]
        temporal["time_since_last_message_hours"] = time_diff_seconds / 3600
        temporal["time_since_last_message_minutes"] = int(time_diff_seconds / 60)
 
    temporal["last_message_timestamp"] = current_time
    dt = datetime.fromtimestamp(current_time, HELSINKI_TZ)
    temporal["last_message_time_str"] = dt.strftime("%H:%M")
 
    return temporal
 
def get_temporal_context_for_llm(user_id: int) -> str:
    state = get_or_create_state(user_id)
    temporal = state.get("temporal_state", {})
    if not isinstance(temporal, dict):
        temporal = {}
 
    now = time.time()
    current_dt = datetime.fromtimestamp(now, HELSINKI_TZ)
    current_time_str = current_dt.strftime("%H:%M")
    current_date_str = current_dt.strftime("%Y-%m-%d (%A)")
 
    parts = [
        f"CURRENT TIME: {current_time_str}",
        f"CURRENT DATE: {current_date_str}"
    ]
 
    time_since_minutes = temporal.get("time_since_last_message_minutes", 0)
    if time_since_minutes > 0:
        last_time = temporal.get("last_message_time_str", "")
        hours = temporal.get("time_since_last_message_hours", 0)
        if hours >= 1:
            parts.append(f"TIME SINCE LAST MESSAGE: {hours:.1f}h (last at {last_time})")
        else:
            parts.append(f"TIME SINCE LAST MESSAGE: {time_since_minutes} min (last at {last_time})")
 
    activity_started = temporal.get("current_activity_started_at", 0)
    if activity_started > 0:
        activity = temporal.get("activity_type", "unknown")
        started_dt = datetime.fromtimestamp(activity_started, HELSINKI_TZ)
        activity_end = temporal.get("current_activity_end_time", 0)
        if activity_end > 0:
            end_dt = datetime.fromtimestamp(activity_end, HELSINKI_TZ)
            parts.append(f"CURRENT ACTIVITY: {activity}")
            parts.append(f"Started: {started_dt.strftime('%H:%M')}, Ends: {end_dt.strftime('%H:%M')}")
 
    return "\n".join(parts)
 
# ====================== AGREEMENTS ======================
def save_agreement(user_id: int, description: str, target_time: float = None, initiated_by: str = "user"):
    now = time.time()
    try:
        with db_lock:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                INSERT INTO agreements (user_id, description, agreed_at, target_time, locked, initiated_by, status, created_at)
                VALUES (?, ?, ?, ?, 1, ?, 'active', ?)
            """, (str(user_id), description, now, target_time, initiated_by, now))
            conn.commit()
        print(f"[AGREEMENT] Saved: {description[:60]}")
    except Exception as e:
        try: conn.rollback()
        except: pass
        print(f"[AGREEMENT ERROR] {e}")
 
def get_active_agreements(user_id: int) -> list:
    with db_lock:
        result = conn.execute("""
            SELECT id, description, agreed_at, target_time, initiated_by
            FROM agreements WHERE user_id=? AND status='active'
            ORDER BY agreed_at DESC LIMIT 10
        """, (str(user_id),))
        rows = result.fetchall()
    return [
        {"id": r[0], "description": r[1], "agreed_at": r[2], "target_time": r[3], "initiated_by": r[4]}
        for r in rows
    ]
 
def extract_agreements_from_frame(user_id: int, frame: dict, user_text: str, bot_reply: str = None):
    t = user_text.lower()
    agreement_signals = [
        "sovittu", "ok sovitaan", "joo sovitaan", "sopii", "ok deal",
        "lupaan", "mä tuun", "mä oon siellä", "teen sen", "agreed",
        "ok mä oon", "ok tuun", "joo tuun", "joo ok", "selvä"
    ]
    future_signals = [
        "lauantaina", "sunnuntaina", "huomenna", "ensi viikolla",
        "illalla", "viikonloppuna", "maanantaina", "tiistaina"
    ]
 
    has_agreement = any(kw in t for kw in agreement_signals)
    has_future = any(kw in t for kw in future_signals)
 
    if not (has_agreement or has_future):
        return
 
    plans = frame.get("plans", [])
    for plan in plans:
        desc = plan.get("description", "").strip()
        if desc and len(desc) > 10:
            due = resolve_due_hint(plan.get("due_hint"))
            save_agreement(user_id, desc, target_time=due, initiated_by="user")
 
def build_narrative_timeline(user_id: int) -> str:
    now = time.time()
    today_start = now - (now % 86400)
    yesterday_start = today_start - 86400
    week_ago = now - (7 * 86400)
 
    with db_lock:
        result = conn.execute("""
            SELECT content, memory_type, created_at FROM episodic_memories
            WHERE user_id=? ORDER BY created_at DESC LIMIT 50
        """, (str(user_id),))
        memories = result.fetchall()
 
    with db_lock:
        result = conn.execute("""
            SELECT summary, created_at FROM summaries
            WHERE user_id=? ORDER BY created_at DESC LIMIT 5
        """, (str(user_id),))
        summaries = result.fetchall()
 
    agreements = get_active_agreements(user_id)
    plans = get_active_plans(user_id, limit=5)
 
    past_lines = []
    today_lines = []
 
    for content, mtype, created_at in memories:
        if created_at < week_ago:
            continue
        if created_at >= today_start:
            today_lines.append(f"  - {content[:100]}")
        elif created_at >= yesterday_start:
            past_lines.append(f"  [eilen] {content[:100]}")
        else:
            days_ago = int((now - created_at) / 86400)
            past_lines.append(f"  [{days_ago}pv sitten] {content[:100]}")
 
    for summary, created_at in summaries:
        if created_at < week_ago:
            continue
        days_ago = int((now - created_at) / 86400)
        if days_ago == 0:
            today_lines.append(f"  [yhteenveto] {summary[:150]}")
        else:
            past_lines.append(f"  [{days_ago}pv sitten, yhteenveto] {summary[:150]}")
 
    future_lines = []
    for ag in agreements:
        target = ag.get("target_time")
        if target:
            dt = datetime.fromtimestamp(target, HELSINKI_TZ)
            time_str = dt.strftime("%A %d.%m. klo %H:%M")
        else:
            time_str = "sovittu aika ei tiedossa"
        future_lines.append(f"  [LUKITTU] {ag['description'][:100]} ({time_str})")
 
    for plan in plans:
        target = plan.get("target_time")
        if target:
            dt = datetime.fromtimestamp(target, HELSINKI_TZ)
            time_str = dt.strftime("%A %d.%m.")
        else:
            time_str = "?"
        desc = plan.get("description", "")
        already_in = any(desc[:40] in ag["description"] for ag in agreements)
        if not already_in:
            future_lines.append(f"  [suunnitelma] {desc[:100]} ({time_str})")
 
    parts = []
    if past_lines:
        parts.append("=== MENNEISYYS ===")
        parts.extend(past_lines[-8:])
    if today_lines:
        parts.append("=== TÄNÄÄN ===")
        parts.extend(today_lines[-5:])
    if future_lines:
        parts.append("=== TULEVAISUUS (ÄLÄ MUUTA LUKITTUJA) ===")
        parts.extend(future_lines)
        parts.append("TÄRKEÄÄ: [LUKITTU] sopimukset ovat pyhiä.")
 
    return "\n".join(parts) if parts else "Ei aiempaa historiaa."
 
# ====================== TOPIC STATE ======================
def update_topic_state(user_id, frame):
    state = get_or_create_state(user_id)
    ts = state.setdefault("topic_state", {
        "current_topic": "general", "topic_summary": "",
        "open_questions": [], "open_loops": [], "updated_at": time.time()
    })
 
    if frame.get("topic_changed"):
        ts["current_topic"] = frame.get("topic", "general")
        ts["topic_summary"] = frame.get("topic_summary", "")
 
    if frame.get("open_questions") is not None:
        ts["open_questions"] = frame.get("open_questions", [])[:5]
 
    if frame.get("open_loops") is not None:
        ts["open_loops"] = frame.get("open_loops", [])[:5]
 
    ts["updated_at"] = time.time()
 
def resolve_open_loops(user_id: int, user_text: str, frame: dict):
    state = get_or_create_state(user_id)
    topic_state = state.get("topic_state", {})
    open_loops = topic_state.get("open_loops", [])
    if not open_loops:
        return
    t = user_text.lower()
    resolved = []
    for loop in open_loops:
        loop_words = set(loop.lower().split())
        text_words = set(t.split())
        overlap = len(loop_words & text_words)
        direct_answer = any(kw in t for kw in ["kyllä", "joo", "en", "ei", "ehkä"])
        if overlap >= 4 or (direct_answer and overlap >= 2):
            resolved.append(loop)
    if resolved:
        remaining = [l for l in open_loops if l not in resolved]
        topic_state["open_loops"] = remaining
 
# ====================== SUBMISSION LEVEL ======================
def update_submission_level(user_id: int, user_text: str):
    state = get_or_create_state(user_id)
    t = user_text.lower()
    submission_keywords = [
        "teen mitä haluat", "totteleen", "käske", "sä päätät",
        "olen sun", "haluan olla", "nöyryytä", "hallitse",
        "strap", "pegging", "chastity", "cuckold"
    ]
    resistance_keywords = ["en halua", "ei käy", "lopeta", "liikaa", "en tee"]
    curious_keywords = ["mitä jos", "entä jos", "miltä tuntuisi", "kiinnostaa"]
 
    current_level = state.get("submission_level", 0.0)
    last_interaction = state.get("last_interaction", time.time())
    hours_since = (time.time() - last_interaction) / 3600
    if hours_since > 24:
        decay = 0.98 ** (hours_since / 24)
        current_level = current_level * decay
 
    if any(kw in t for kw in submission_keywords):
        state["submission_level"] = min(1.0, current_level + 0.15)
    elif any(kw in t for kw in resistance_keywords):
        state["submission_level"] = max(0.0, current_level - 0.08)
    elif any(kw in t for kw in curious_keywords):
        state["submission_level"] = min(1.0, current_level + 0.05)
    else:
        state["submission_level"] = current_level
 
    return state["submission_level"]
 
def classify_user_signal(user_text: str) -> str:
    t = user_text.lower().strip()
    if any(x in t for x in ["älä", "stop", "lopeta", "en halua", "ei käy", "riittää", "ei enää"]):
        return "boundary"
    if any(x in t for x in ["väärin", "ymmärsit väärin", "ei noin", "tarkoitin", "en tarkoittanut"]):
        return "correction"
    if "?" in t or any(t.startswith(w) for w in ["miksi", "miten", "voiko", "onko", "mitä", "kuka", "missä", "milloin"]):
        return "question"
    if any(x in t for x in ["vaihdetaan aihetta", "puhutaan muusta", "toinen aihe", "unohda se"]):
        return "topic_change"
    if any(x in t for x in ["seksi", "sex", "nussi", "pano", "strap", "pegging", "horny", "alasti", "nude", "naked", "cuckold"]):
        return "sexual"
    return "normal"
 
# ====================== FRAME EXTRACTOR (CLAUDE SONNET 4.6 - kevyempi malli) ======================
async def extract_turn_frame(user_id: int, user_text: str):
    recent_turns = get_recent_turns(user_id, limit=8)
    active_plans = get_active_plans(user_id, limit=3)
 
    recent_text = "\n".join([f"{t['role']}: {t['content']}" for t in recent_turns])
    plans_text = "\n".join([f"- {p['description']}" for p in active_plans]) if active_plans else "none"
 
    default = {
        "topic": "general", "topic_changed": False, "topic_summary": "",
        "open_questions": [], "open_loops": [], "plans": [], "facts": [],
        "memory_candidates": [], "scene_hint": None, "fantasies": []
    }
 
    prompt = f"""Analyze the latest user turn and return JSON only.
 
Schema:
{{
  "topic": "short topic label",
  "topic_changed": true,
  "topic_summary": "one sentence",
  "open_questions": ["..."],
  "open_loops": ["..."],
  "plans": [{{"description": "...", "due_hint": "...", "commitment_strength": "strong|medium"}}],
  "facts": [{{"fact_key": "...", "fact_value": "...", "confidence": 0.0}}],
  "memory_candidates": ["..."],
  "scene_hint": "home|work|commute|public|bed|shower|null",
  "fantasies": [{{"description": "...", "category": "dominance|humiliation|pegging|chastity|cuckold|other"}}]
}}
 
Rules:
- topic_changed=true only if topic really changes
- facts: only reusable user facts/preferences
- plans: future commitments or likely follow-ups
- scene_hint: only if user clearly indicates location
- fantasies: ANY sexual desires or kinks mentioned
 
Active plans:
{plans_text}
 
Recent turns:
{recent_text}
 
Latest user turn:
{user_text}"""
 
    # Käytä kevyempää Sonnet 4.6 -mallia frame extractille
    raw = await call_llm(
        user_prompt=prompt,
        max_tokens=500,
        temperature=0.2,
        prefer_light=True,
        json_mode=True
    )
 
    if not raw:
        default["user_text"] = user_text
        return default
 
    frame = parse_json_object(raw, default)
    frame["user_text"] = user_text
    return frame
 
def apply_scene_updates_from_turn(state: dict, user_text: str):
    now = time.time()
    forced = force_scene_from_text(state, user_text, now)
    if not forced:
        maybe_transition_scene(state, now)
    maybe_interrupt_action(state, user_text)
    update_action(state, now)
 
async def apply_frame(user_id: int, frame: dict, source_turn_id: int):
    state = get_or_create_state(user_id)
 
    update_topic_state(user_id, frame)
    resolve_open_loops(user_id, frame.get("user_text", ""), frame)
    save_topic_state_to_db(user_id)
 
    for fact in frame.get("facts", [])[:8]:
        upsert_profile_fact(
            user_id=user_id,
            fact_key=fact.get("fact_key", ""),
            fact_value=fact.get("fact_value", ""),
            confidence=float(fact.get("confidence", 0.7)),
            source_turn_id=source_turn_id
        )
 
    for plan in frame.get("plans", [])[:5]:
        upsert_plan(user_id, plan, source_turn_id=source_turn_id)
 
    for mem in frame.get("memory_candidates", [])[:4]:
        await store_episodic_memory(user_id=user_id, content=mem, memory_type="event", source_turn_id=source_turn_id)
 
    for fantasy in frame.get("fantasies", [])[:3]:
        await store_episodic_memory(
            user_id=user_id, content=fantasy.get("description", ""),
            memory_type="fantasy", source_turn_id=source_turn_id
        )
        upsert_profile_fact(
            user_id=user_id,
            fact_key=f"fantasy_{fantasy.get('category', 'general')}",
            fact_value=fantasy.get("description", ""),
            confidence=0.9, source_turn_id=source_turn_id
        )
 
    scene_hint = frame.get("scene_hint")
    if scene_hint in SCENE_MICRO:
        _set_scene(state, scene_hint, time.time())
        state["micro_context"] = random.choice(SCENE_MICRO[scene_hint])
 
    extract_agreements_from_frame(user_id, frame, frame.get("user_text", ""))
 
# ====================== CONTEXT PACK ======================
async def build_context_pack(user_id: int, user_text: str):
    state = get_or_create_state(user_id)
 
    recent_turns = get_recent_turns(user_id, limit=8)
    relevant_memories = await retrieve_relevant_memories(user_id, user_text, limit=5)
    active_plans = get_active_plans(user_id, limit=4)
    profile_facts = get_profile_facts(user_id, limit=8)
    summaries = get_recent_summaries(user_id, limit=2)
    agreements = get_active_agreements(user_id)
    narrative_timeline = build_narrative_timeline(user_id)
 
    return {
        "topic_state": state.get("topic_state", {}),
        "scene": state.get("scene", "neutral"),
        "micro_context": state.get("micro_context", ""),
        "current_action": state.get("current_action"),
        "location_status": state.get("location_status", "separate"),
        "recent_turns": recent_turns,
        "relevant_memories": relevant_memories,
        "active_plans": active_plans,
        "profile_facts": profile_facts,
        "summaries": summaries,
        "agreements": agreements,
        "narrative_timeline": narrative_timeline,
        "temporal_context": build_temporal_context(state)
    }
 
def format_context_pack(context_pack: dict):
    topic_state = context_pack.get("topic_state", {})
    profile_lines = "\n".join([f"- {f['fact_key']}: {f['fact_value']}" for f in context_pack.get("profile_facts", [])]) or "- none"
    turns_lines = "\n".join([f"{t['role']}: {t['content']}" for t in context_pack.get("recent_turns", [])])
    narrative_timeline = context_pack.get("narrative_timeline", "")
 
    return f"""
{narrative_timeline}
 
=====================================
CURRENT TOPIC: {topic_state.get('current_topic', 'general')}
TOPIC SUMMARY: {topic_state.get('topic_summary', 'No summary yet.')}
 
OPEN QUESTIONS:
{chr(10).join('- ' + q for q in topic_state.get('open_questions', [])) if topic_state.get('open_questions') else '- none'}
 
OPEN LOOPS:
{chr(10).join('- ' + q for q in topic_state.get('open_loops', [])) if topic_state.get('open_loops') else '- none'}
 
SCENE: {context_pack.get('scene')}
MICRO CONTEXT: {context_pack.get('micro_context')}
CURRENT ACTION: {context_pack.get('current_action')}
LOCATION STATUS: {context_pack.get('location_status')}
 
TEMPORAL CONTEXT:
{context_pack.get('temporal_context')}
 
PROFILE FACTS:
{profile_lines}
 
RECENT TURNS:
{turns_lines}
"""
 
# ====================== TURN ANALYSIS ======================
async def analyze_user_turn(user_id: int, user_text: str, context_pack: dict) -> dict:
    default = {
        "primary_intent": "chat", "topic": "general",
        "what_user_wants_now": user_text, "explicit_constraints": [],
        "user_is_correcting_bot": False, "should_change_course": False,
        "tone_needed": "direct", "answer_first": user_text, "signal_type": "normal"
    }
 
    signal = classify_user_signal(user_text)
    default["signal_type"] = signal
 
    if signal == "boundary":
        default.update({
            "primary_intent": "boundary", "should_change_course": True,
            "tone_needed": "warm", "explicit_constraints": ["stop current topic"]
        })
        return default
 
    if signal == "correction":
        default.update({
            "primary_intent": "correction", "user_is_correcting_bot": True,
            "should_change_course": True
        })
        return default
 
    if signal == "topic_change":
        default.update({"primary_intent": "topic_change", "should_change_course": True})
        return default
 
    recent_turns = context_pack.get("recent_turns", [])
    recent_text = "\n".join([f"{t['role']}: {t['content']}" for t in recent_turns[-4:]])
 
    prompt = f"""Return JSON only, no markdown.
 
Schema:
{{
  "primary_intent": "question|correction|boundary|topic_change|request|chat|sexual",
  "topic": "short label in Finnish",
  "what_user_wants_now": "one sentence in Finnish",
  "explicit_constraints": [],
  "user_is_correcting_bot": false,
  "should_change_course": false,
  "tone_needed": "neutral|warm|direct|playful|intimate",
  "answer_first": "what must be answered directly"
}}
 
Recent turns:
{recent_text}
 
Latest user message:
{user_text}"""
 
    raw = await call_llm(
        user_prompt=prompt,
        max_tokens=250,
        temperature=0.1,
        prefer_light=True,
        json_mode=True
    )
 
    if not raw:
        return default
 
    result = parse_json_object(raw, default)
    result["signal_type"] = signal
    return result
 
# ====================== GENERATE REPLY (CLAUDE OPUS 4.7 PRIMARY) ======================
async def generate_llm_reply(user_id, user_text):
    context_pack = await build_context_pack(user_id, user_text)
    state = get_or_create_state(user_id)
 
    turn_analysis = await analyze_user_turn(user_id, user_text, context_pack)
    signal_type = turn_analysis.get("signal_type", "normal")
    should_change = turn_analysis.get("should_change_course", False)
    user_correcting = turn_analysis.get("user_is_correcting_bot", False)
    tone_needed = turn_analysis.get("tone_needed", "direct")
    primary_intent = turn_analysis.get("primary_intent", "chat")
 
    current_mode = update_conversation_mode(user_id, user_text)
    if signal_type in ("boundary", "topic_change"):
        current_mode = "casual"
        state["conversation_mode"] = "casual"
 
    submission_level = state.get("submission_level", 0.0)
    temporal_context = get_temporal_context_for_llm(user_id)
    memory_context = format_context_pack(context_pack)
    persona_prompt = build_core_persona_prompt()
 
    situation_directive = ""
    if signal_type == "boundary":
        situation_directive = """
USER HAS SET A BOUNDARY OR SAID STOP.
- Respect it immediately and warmly.
- No escalation, no ignoring.
- Change topic or acknowledge naturally."""
    elif user_correcting or signal_type == "correction":
        situation_directive = """
USER IS CORRECTING YOU.
- Acknowledge the correction first.
- Course-correct naturally without defending yourself."""
    elif primary_intent == "question":
        situation_directive = """
USER IS ASKING A QUESTION - answer it directly first.
Then add your natural tone."""
    elif current_mode == "nsfw" and submission_level > 0.4:
        situation_directive = """
INTIMATE CONTEXT.
- Megan's dominant, humiliation-enjoying side can come through naturally.
- Stay human - not mechanical or repetitive."""
    elif should_change:
        situation_directive = """
TOPIC IS CHANGING - follow the user's direction."""
 
    system_prompt = f"""{persona_prompt}
 
{temporal_context}
 
CONVERSATION STATE:
- Mode: {current_mode}
- Tone needed: {tone_needed}
- Submission level: {submission_level:.2f}
- User signal type: {signal_type}
 
{situation_directive}
 
PRIORITY ORDER:
1. User's latest message and intent - always first
2. Corrections and boundaries - respect immediately
3. Megan's personality tone - applied after understanding user intent
4. Memory/continuity - only when not conflicting with latest message
 
Respond naturally in Finnish. Max 1 question per reply.
"""
 
    user_prompt = f"""TURN ANALYSIS:
{json.dumps(turn_analysis, ensure_ascii=False, indent=2)}
 
CONTEXT:
{memory_context}
 
LATEST USER MESSAGE:
{user_text}
 
Write Megan's reply in Finnish. Respond to what the user actually said.
"""
 
    # PÄÄASIALLINEN GENEROINTI CLAUDE OPUS 4.7:LLÄ
    reply = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=1200,  # Opus 4.7 suosittaa suurempaa max_tokens arvoa
        temperature=0.8,
        prefer_light=False  # KÄYTÄ OPUS 4.7 TÄHÄN
    )
 
    if not reply:
        print("[LLM ERROR] Empty reply from all providers")
        return "Anteeksi, tekninen ongelma. Yritä hetken päästä uudelleen."
 
    # Anti-jankkaaja
    recent_bot = [
        x["content"] for x in conversation_history.get(user_id, [])
        if x["role"] == "assistant"
    ][-3:]
    if any(too_similar(reply, old) for old in recent_bot):
        print("[ANTI-JANK] Too similar, regenerating with variation...")
        retry_prompt = user_prompt + "\n\nVältä toistamasta aiempien vastaustesi sanoja tai rakennetta."
        new_reply = await call_llm(
            system_prompt=system_prompt,
            user_prompt=retry_prompt,
            max_tokens=1200,
            temperature=0.95,
            prefer_light=False
        )
        if new_reply:
            reply = new_reply
 
    return reply
 
# ====================== IMAGE GENERATION ======================
async def generate_image_replicate(prompt: str):
    try:
        if not REPLICATE_API_KEY:
            return None
 
        model_version = "black-forest-labs/flux-1.1-pro-ultra"
        create_url = "https://api.replicate.com/v1/predictions"
 
        payload = {
            "version": model_version,
            "input": {
                "prompt": prompt,
                "aspect_ratio": "1:1",
                "output_format": "png",
                "output_quality": 100,
                "safety_tolerance": 6,
                "prompt_upsampling": True
            }
        }
 
        headers = {
            "Authorization": f"Bearer {REPLICATE_API_KEY}",
            "Content-Type": "application/json",
            "Prefer": "wait"
        }
 
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
            async with session.post(create_url, json=payload, headers=headers) as resp:
                if resp.status not in (200, 201):
                    return None
                data = await resp.json()
 
            prediction_id = data.get('id')
            get_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
            max_attempts = 60
            attempt = 0
 
            while attempt < max_attempts:
                if data.get('status') == 'succeeded':
                    break
                if data.get('status') in ['failed', 'canceled']:
                    return None
                await asyncio.sleep(2)
                attempt += 1
                async with session.get(get_url, headers=headers) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
 
            if data.get('status') != 'succeeded':
                return None
 
            output = data.get('output')
            if isinstance(output, str):
                image_url = output
            elif isinstance(output, list) and len(output) > 0:
                image_url = output[0]
            else:
                return None
 
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    return None
                image_bytes = await resp.read()
                return image_bytes
 
    except Exception as e:
        print(f"[REPLICATE ERROR] {e}")
        return None
 
async def generate_image_venice(prompt: str):
    try:
        if not VENICE_API_KEY:
            return None
 
        payload = {
            "prompt": prompt, "model": "fluently-xl",
            "width": 1024, "height": 1024, "num_images": 1
        }
 
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
            async with session.post(
                "https://api.venice.ai/v1/images/generations",
                headers={"Authorization": f"Bearer {VENICE_API_KEY}", "Content-Type": "application/json"},
                json=payload
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                items = data.get("data", [])
                if not items:
                    return None
                b64 = items[0].get("b64_json")
                if not b64:
                    return None
                return base64.b64decode(b64)
 
    except Exception as e:
        print(f"[VENICE ERROR] {e}")
        return None
 
async def generate_image(prompt: str, max_retries: int = 2):
    for attempt in range(max_retries):
        try:
            if REPLICATE_API_KEY:
                result = await generate_image_replicate(prompt)
                if result:
                    return result
            if VENICE_API_KEY:
                result = await generate_image_venice(prompt)
                if result:
                    return result
        except Exception as e:
            print(f"[IMAGE ERROR] Attempt {attempt+1}: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
    return None
 
def scene_to_setting(scene: str) -> str:
    mapping = {
        "home": "modern apartment living room, stylish Scandinavian interior",
        "bed": "bedroom, near bed, soft warm intimate lighting",
        "work": "modern office or workspace, clean professional environment",
        "public": "city street or trendy café, urban background",
        "commute": "urban transit setting, train station or tram",
        "shower": "bathroom, soft steam, clean minimal setting",
        "neutral": "simple neutral indoor background, soft diffused light",
    }
    return mapping.get(scene, "modern apartment, simple neutral indoor background")
 
def build_image_prompt(outfit: str, setting: str, pose: str = None, camera: str = None,
                      mood: str = None, angle: str = None, **kwargs) -> str:
    pose = pose or "standing, confident, weight on one leg, hand on hip"
    camera = camera or "full body, 4-5m distance, portrait format, head and feet visible"
    mood = mood or "confident, seductive, natural"
    angle = angle or "slight 3/4 angle"
 
    return f"""Photorealistic full-body portrait photograph.
 
SCENE:
{setting}
 
SUBJECT:
Tall athletic Finnish woman, 175cm. Platinum blonde hair (long, straight, mid-back). Blue-green eyes, smoky makeup. Large natural breasts (D-cup), slim waist, long toned legs, round ass. Fair Nordic skin. Dominant confident presence.
 
OUTFIT:
{outfit}
 
POSE:
{pose}
 
MOOD:
{mood}
 
CAMERA:
{camera}
Angle: {angle}
Lens: 35-50mm natural perspective, slight background blur
 
CONSTRAINTS:
- Full body visible from head to feet
- Feet visible at bottom of frame
- No cropping at waist, hips or knees
- Subject occupies 70-85% of frame height
- Portrait/vertical format
- No extra people in frame
 
STYLE:
Ultra-realistic 8K photography, cinematic lighting, editorial quality
"""
 
# ====================== IMAGE VISION ======================
async def analyze_generated_image(image_bytes: bytes, user_request: str, state: dict) -> dict:
    default = {
        "summary": "", "visible_outfit": "", "visible_setting": "",
        "pose": "", "mood": "", "notable_details": [],
        "matches_request": True, "caption_seed": ""
    }
 
    if not openai_client:
        return default
 
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        conv_mode = state.get("conversation_mode", "casual")
        submission = state.get("submission_level", 0.0)
 
        prompt = f"""Return JSON only. No markdown.
 
Schema:
{{
  "summary": "1-2 lause suomeksi: mita kuvassa nakyy",
  "visible_outfit": "mita vaatteita kuvassa oikeasti nakyy",
  "visible_setting": "mika tausta tai paikka kuvassa nakyy",
  "pose": "mika asento tai ele kuvassa nakyy",
  "mood": "mika fiilis tai ilme kuvasta valittaa",
  "notable_details": ["yksityiskohta 1", "yksityiskohta 2"],
  "matches_request": true,
  "caption_seed": "luonnollinen lause jota Megan voisi sanoa"
}}
 
Conversation mode: {conv_mode}
Submission level: {submission:.2f}
User asked: {user_request[:200]}
 
Analyze the ACTUAL image. Be concrete. caption_seed should feel natural for Megan."""
 
        resp = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}}
                ]
            }],
            max_tokens=350,
            temperature=0.2
        )
 
        raw = (resp.choices[0].message.content or "{}").strip()
        return parse_json_object(raw, default)
 
    except Exception as e:
        print(f"[IMAGE ANALYSIS ERROR] {e}")
        return default
 
async def generate_image_commentary(user_id: int, analysis: dict, state: dict, user_request: str) -> str:
    conversation_mode = state.get("conversation_mode", "casual")
    submission_level = state.get("submission_level", 0.0)
 
    caption_seed = analysis.get("caption_seed", "")
    if not analysis.get("summary") and caption_seed:
        return caption_seed
 
    prompt = f"""Write one short natural Finnish line Megan would say when sending her own photo.
 
Rules:
- Comment on the ACTUAL image content, not generic phrases
- Tone fits mode: {conversation_mode} (submission: {submission_level:.2f})
- Max 1-2 sentences, feel natural
 
Image analysis:
- Outfit: {analysis.get('visible_outfit', 'not analyzed')}
- Setting: {analysis.get('visible_setting', 'not analyzed')}
- Mood: {analysis.get('mood', 'not analyzed')}
 
Original request: {user_request[:100]}
Caption seed idea: {caption_seed}"""
 
    result = await call_llm(
        user_prompt=prompt,
        max_tokens=100,
        temperature=0.9,
        prefer_light=True
    )
 
    return result or caption_seed or "Mitä sä tykkäät? 😏"
 
async def handle_image_request(update: Update, user_id: int, text: str):
    state = get_or_create_state(user_id)
    submission_level = state.get("submission_level", 0.0)
    conversation_mode = state.get("conversation_mode", "casual")
    scene = state.get("scene", "home")
    last_image = state.get("last_image") or {}
 
    # Scene defaults
    scene_defaults = {
        "home": "glossy black latex leggings + fitted black crop top, casual dominant look",
        "bed": "black lace lingerie: sheer bralette and high-cut panties",
        "work": "high-waist black latex leggings + fitted white blouse + blazer",
        "public": "black leather pants + elegant fitted top + ankle boots",
        "commute": "black latex leggings + leather jacket",
        "shower": "white towel wrapped elegantly",
        "neutral": "glossy black latex leggings + black crop top",
    }
 
    if conversation_mode == "nsfw" and submission_level > 0.4:
        outfit = "black lace lingerie: minimal and seductive"
    else:
        outfit = scene_defaults.get(scene, "glossy black latex leggings + fitted black top")
 
    setting = scene_to_setting(scene)
 
    mood_map = {
        "nsfw": "overtly seductive, dominant, intense eye contact",
        "suggestive": "playfully seductive, confident knowing smile",
        "romantic": "warm, intimate, soft inviting expression",
        "casual": "confident, natural, effortlessly attractive",
    }
    mood = mood_map.get(conversation_mode, "confident, seductive, natural")
 
    base_prompt = build_image_prompt(outfit=outfit, setting=setting, mood=mood)
 
    await update.message.reply_text("Hetki, otan kuvan... 📸")
 
    try:
        image_bytes = await generate_image(base_prompt)
        if not image_bytes:
            await update.message.reply_text("Kuvan generointi epäonnistui. Yritä uudelleen.")
            return
    except Exception as e:
        print(f"[IMAGE ERROR] {e}")
        await update.message.reply_text(f"Virhe: {str(e)}")
        return
 
    analysis = await analyze_generated_image(image_bytes, text, state)
    caption = await generate_image_commentary(user_id, analysis, state, text)
 
    try:
        sent_msg = await update.message.reply_photo(
            photo=BytesIO(image_bytes),
            caption=caption
        )
        telegram_file_id = sent_msg.photo[-1].file_id if sent_msg and sent_msg.photo else None
    except Exception as e:
        await update.message.reply_text(f"Lähetysvirhe: {str(e)}")
        return
 
    state["last_image"] = {
        "prompt": base_prompt, "user_request": text,
        "context": outfit, "setting": setting, "mood": mood,
        "timestamp": time.time(), "telegram_file_id": telegram_file_id,
        "analysis": analysis, "caption": caption,
    }
 
    await store_episodic_memory(
        user_id=user_id,
        content=json.dumps({
            "type": "image_sent",
            "outfit": analysis.get("visible_outfit") or outfit,
            "setting": analysis.get("visible_setting") or setting,
            "caption": caption
        }, ensure_ascii=False),
        memory_type="image_sent",
    )
 
# ====================== HANDLE MESSAGE ======================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = None
    text = None
    state = None
 
    try:
        user_id = update.effective_user.id
        text = (update.message.text or "").strip()
 
        if not text:
            return
 
        current_time = time.time()
        update_temporal_state(user_id, current_time)
 
        t = text.lower()
 
        image_triggers = [
            "laheta kuva", "haluan kuvan", "tee kuva", "nayta kuva",
            "ota kuva", "laheta pic", "send pic", "picture",
            "show me", "selfie", "valokuva",
            "lähetä kuva", "näytä kuva",
        ]
        is_image_request = any(trigger in t for trigger in image_triggers)
 
        state = get_or_create_state(user_id)
 
        update_submission_level(user_id, text)
        state["last_interaction"] = time.time()
        apply_scene_updates_from_turn(state, text)
 
        conversation_history.setdefault(user_id, [])
        conversation_history[user_id].append({"role": "user", "content": text})
        conversation_history[user_id] = conversation_history[user_id][-20:]
 
        user_turn_id = save_turn(user_id, "user", text)
 
        frame = await extract_turn_frame(user_id, text)
        await apply_frame(user_id, frame, user_turn_id)
 
        if is_image_request:
            await handle_image_request(update, user_id, text)
            return
 
        plan_action = resolve_plan_reference(user_id, text)
        if plan_action:
            action = plan_action["action"]
            plan_desc = plan_action["plan"]["description"][:80]
            await store_episodic_memory(
                user_id=user_id,
                content=f"Plan '{plan_desc}' marked as {action}",
                memory_type="plan_update",
                source_turn_id=user_turn_id
            )
 
        reply = await generate_llm_reply(user_id, text)
 
        if breaks_scene_logic(reply, state):
            reply = "Hetki, kadotin ajatuksen. Sano uudelleen."
        if breaks_temporal_logic(reply, state):
            reply = "Hetki, olin vähän muualla. Mitä sanoit?"
 
        conversation_history[user_id].append({"role": "assistant", "content": reply})
        conversation_history[user_id] = conversation_history[user_id][-20:]
 
        assistant_turn_id = save_turn(user_id, "assistant", reply)
 
        await store_episodic_memory(
            user_id=user_id,
            content=f"User: {text}\nAssistant: {reply}",
            memory_type="conversation_event",
            source_turn_id=assistant_turn_id
        )
 
        await maybe_create_summary(user_id)
 
        # Pilko pitkät viestit
        if len(reply) > 4000:
            chunks = [reply[i:i+3900] for i in range(0, len(reply), 3900)]
            for i, chunk in enumerate(chunks, 1):
                await update.message.reply_text(chunk)
                if i < len(chunks):
                    await asyncio.sleep(0.3)
        else:
            await update.message.reply_text(reply)
 
        save_persistent_state_to_db(user_id)
 
    except Exception as e:
        error_msg = f"""
🔴 VIRHE HANDLE_MESSAGE:SSA
Tyyppi: {type(e).__name__}
Viesti: {str(e)[:500]}
Traceback:
{traceback.format_exc()[:800]}
User: {user_id}
Text: {text[:100] if text else 'N/A'}
"""
        print(error_msg)
        try:
            if update and update.message:
                await update.message.reply_text(f"⚠️ Virhe: {type(e).__name__}\nYritä uudelleen.")
        except Exception:
            pass
 
# ====================== BACKGROUND TASKS ======================
async def check_proactive_triggers(application):
    while True:
        try:
            now_ts = time.time()
 
            # Plan reminders
            with db_lock:
                result = conn.execute("""
                    SELECT user_id, id, description, target_time, last_reminded_at
                    FROM planned_events
                    WHERE status='planned' AND target_time IS NOT NULL
                """)
                rows = result.fetchall()
 
            for row in rows:
                user_id, plan_id, description, target_time, last_reminded_at = row
                if not target_time:
                    continue
 
                should_remind = (
                    (0 <= target_time - now_ts <= 900) or
                    (0 <= now_ts - target_time <= 1800)
                )
                if not should_remind:
                    continue
                if last_reminded_at and (now_ts - last_reminded_at) < 3600:
                    continue
 
                try:
                    await application.bot.send_message(
                        chat_id=int(user_id),
                        text=f"Muistutus: {description}"
                    )
                    with db_lock:
                        conn.execute("UPDATE planned_events SET last_reminded_at=? WHERE id=?", (now_ts, plan_id))
                        conn.commit()
                except Exception as e:
                    print(f"[REMINDER ERROR] {e}")
 
            # Periodic state flush
            for uid in list(continuity_state.keys()):
                try:
                    last_save = continuity_state[uid].get("_last_save_at", 0)
                    if time.time() - last_save > 1800:
                        save_persistent_state_to_db(uid)
                        continuity_state[uid]["_last_save_at"] = time.time()
                except Exception:
                    pass
 
        except Exception as e:
            print(f"[PROACTIVE ERROR] {e}")
 
        await asyncio.sleep(300)
 
# ====================== STATE MANAGEMENT ======================
def build_default_state() -> dict:
    return {
        "energy": "normal", "availability": "free",
        "last_interaction": 0, "persona_mode": "warm",
        "intent": "casual", "summary": "",
        "tension": 0.0, "phase": "neutral",
        "emotional_state": {"valence": 0.0, "arousal": 0.5, "attachment": 0.5},
        "persona_vector": {"dominance": 0.7, "warmth": 0.5, "playfulness": 0.4},
        "last_image": None, "image_history": [],
        "conversation_mode": "casual", "conversation_mode_last_change": 0,
        "emotional_mode": "calm", "emotional_mode_last_change": 0,
        "location_status": "separate", "with_user_physically": False,
        "shared_scene": False,
        "planned_events": [],
        "submission_level": 0.0, "humiliation_tolerance": 0.0,
        "cuckold_acceptance": 0.0, "strap_on_introduced": False,
        "chastity_discussed": False, "feminization_level": 0.0,
        "dominance_level": 1,
        "sexual_boundaries": {"hard_nos": [], "soft_nos": [], "accepted": [], "actively_requested": []},
        "conversation_themes": {},
        "user_preferences": {"fantasy_themes": [], "turn_ons": [], "turn_offs": []},
        "manipulation_history": {},
        "user_model": {},
        "topic_state": {
            "current_topic": "general", "topic_summary": "",
            "open_questions": [], "open_loops": [], "updated_at": time.time()
        },
        "temporal_state": {
            "last_message_timestamp": 0, "last_message_time_str": "",
            "time_since_last_message_hours": 0.0, "time_since_last_message_minutes": 0,
            "current_activity_started_at": 0, "current_activity_duration_planned": 0,
            "current_activity_end_time": 0, "activity_type": None,
            "should_ignore_until": 0, "ignore_reason": None
        },
        **init_scene_state()
    }
 
def deep_merge_state(existing: dict, defaults: dict) -> dict:
    result = defaults.copy()
    for key, value in existing.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_state(value, result[key])
        else:
            result[key] = value
    return result
 
def normalize_state(state: dict) -> dict:
    return deep_merge_state(state, build_default_state())
 
def get_or_create_state(user_id):
    if user_id not in continuity_state:
        print(f"[STATE] Creating new state for user {user_id}")
        continuity_state[user_id] = build_default_state()
        continuity_state[user_id]["planned_events"] = load_plans_from_db(user_id)
        topic_state = load_topic_state_from_db(user_id)
        if topic_state:
            continuity_state[user_id]["topic_state"] = topic_state
    else:
        continuity_state[user_id] = normalize_state(continuity_state[user_id])
    return continuity_state[user_id]
 
def create_database_indexes():
    try:
        with db_lock:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodic_user_created ON episodic_memories(user_id, created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodic_user_type ON episodic_memories(user_id, memory_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_user ON profile_facts(user_id, updated_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_user_status ON planned_events(user_id, status, created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_turns_user ON turns(user_id, id DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agreements_user_status ON agreements(user_id, status, agreed_at DESC)")
            conn.commit()
            print("✅ Database indexes created")
    except Exception as e:
        print(f"[INDEX ERROR] {e}")
 
# ====================== COMMAND HANDLERS ======================
async def cmd_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    if user_id in continuity_state:
        del continuity_state[user_id]
    await update.message.reply_text("🔄 Session reset. Muistot säilyvät.")
 
async def cmd_wipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    if user_id in continuity_state:
        del continuity_state[user_id]
    with db_lock:
        for table in ["memories", "profiles", "planned_events", "topic_state", "turns",
                      "episodic_memories", "profile_facts", "summaries", "activity_log", "agreements"]:
            conn.execute(f"DELETE FROM {table} WHERE user_id=?", (str(user_id),))
        conn.commit()
    await update.message.reply_text("🗑️ Kaikki tila poistettu.")
 
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sync_plans_to_state(user_id)
    state = get_or_create_state(user_id)
    txt = f"""📊 STATUS (v{BOT_VERSION})
 
LLM: Claude Opus 4.7 (primary)
Scene: {state.get('scene')}
Mode: {state.get('conversation_mode')}
Location: {state.get('location_status')}
Submission: {state.get('submission_level', 0.0):.2f}
Tension: {state.get('tension', 0.0):.2f}
Topic: {state.get('topic_state', {}).get('current_topic')}
Plans: {len(state.get('planned_events', []))}
"""
    await update.message.reply_text(txt)
 
async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sync_plans_to_state(user_id)
    state = get_or_create_state(user_id)
    plans = state.get("planned_events", [])
    if not plans:
        await update.message.reply_text("📋 Ei suunnitelmia.")
        return
    lines = ["📋 SUUNNITELMAT:\n"]
    for i, plan in enumerate(plans[-10:], 1):
        age_min = int((time.time() - plan.get("created_at", time.time())) / 60)
        lines.append(f"{i}. {plan.get('description', '')[:100]}\n   Status: {plan.get('status', 'planned')}, Age: {age_min}min\n")
    await update.message.reply_text("\n".join(lines))
 
async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with db_lock:
        result = conn.execute("SELECT COUNT(*) FROM episodic_memories WHERE user_id=?", (str(user_id),))
        episodic = result.fetchone()[0]
        result = conn.execute("SELECT COUNT(*) FROM profile_facts WHERE user_id=?", (str(user_id),))
        facts = result.fetchone()[0]
        result = conn.execute("SELECT COUNT(*) FROM summaries WHERE user_id=?", (str(user_id),))
        summaries = result.fetchone()[0]
        result = conn.execute("SELECT COUNT(*) FROM turns WHERE user_id=?", (str(user_id),))
        turns = result.fetchone()[0]
    txt = f"""🧠 MEMORY STATS (v{BOT_VERSION})
 
Episodic Memories: {episodic}
Profile Facts: {facts}
Summaries: {summaries}
Raw Turns: {turns}
"""
    await update.message.reply_text(txt)
 
async def cmd_scene(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    if not context.args:
        await update.message.reply_text("Käyttö: /scene home|work|public|bed|shower|commute|neutral")
        return
    new_scene = context.args[0].lower()
    if new_scene not in ["home", "work", "public", "bed", "shower", "commute", "neutral"]:
        await update.message.reply_text("Virheellinen scene")
        return
    state["scene"] = new_scene
    state["micro_context"] = random.choice(SCENE_MICRO.get(new_scene, [""]))
    state["last_scene_change"] = time.time()
    state["scene_locked_until"] = time.time() + MIN_SCENE_DURATION
    await update.message.reply_text(f"✅ Scene: {new_scene}")
 
async def cmd_together(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    state["location_status"] = "together"
    state["with_user_physically"] = True
    state["shared_scene"] = True
    await update.message.reply_text("✅ Olet nyt Meganin kanssa.")
 
async def cmd_separate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    state["location_status"] = "separate"
    state["with_user_physically"] = False
    state["shared_scene"] = False
    await update.message.reply_text("✅ Et ole enää fyysisesti Meganin kanssa.")
 
async def cmd_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.args:
        description = " ".join(context.args)
        await handle_image_request(update, user_id, f"Haluan kuvan: {description}")
    else:
        await handle_image_request(update, user_id, "Lähetä kuva")
 
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = f"""🤖 MEGAN {BOT_VERSION}
Primary LLM: Claude Opus 4.7
 
Session:
/newgame - Reset session
/wipe - Delete all memories
 
Status:
/status - Show state
/plans - Show plans
/memory - Memory stats
 
Control:
/scene <name> - Change scene
/together - Physically together
/separate - Physically separate
 
Media:
/image [description] - Generate image
 
Info:
/help - This help
"""
    await update.message.reply_text(txt)
 
# ====================== MAIN ======================
async def main():
    global background_task
 
    print("[MAIN] ===== STARTING =====")
    print(f"[MAIN] Primary LLM: {CLAUDE_MODEL_PRIMARY}")
    print(f"[MAIN] Light LLM: {CLAUDE_MODEL_LIGHT}")
    print(f"[MAIN] Fallback 1: Grok ({GROK_MODEL})")
    print(f"[MAIN] Fallback 2: OpenAI ({OPENAI_MODEL})")
 
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
 
    try:
        migrate_database()
    except Exception as e:
        print(f"[MAIN] Migration error: {e}")
 
    try:
        load_states_from_db()
    except Exception as e:
        print(f"[MAIN] Load states error: {e}")
 
    for user_id in list(continuity_state.keys()):
        try:
            clean_ephemeral_state_on_boot(user_id)
        except Exception as e:
            print(f"[MAIN] Boot clean error {user_id}: {e}")
 
    try:
        create_database_indexes()
    except Exception as e:
        print(f"[MAIN] Index error: {e}")
 
    # Pre-warm Claude client
    get_claude_client()
 
    application = Application.builder().token(TELEGRAM_TOKEN).build()
 
    application.add_handler(CommandHandler("newgame", cmd_new_game))
    application.add_handler(CommandHandler("wipe", cmd_wipe))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("plans", cmd_plans))
    application.add_handler(CommandHandler("memory", cmd_memory))
    application.add_handler(CommandHandler("scene", cmd_scene))
    application.add_handler(CommandHandler("together", cmd_together))
    application.add_handler(CommandHandler("separate", cmd_separate))
    application.add_handler(CommandHandler("image", cmd_image))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
 
    await application.initialize()
    await application.start()
 
    background_task = asyncio.create_task(check_proactive_triggers(application))
 
    await application.updater.start_polling(drop_pending_updates=True)
 
    print(f"[MAIN] ✅ Bot running with Claude Opus 4.7!")
 
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        print("\n[MAIN] Shutdown signal")
    finally:
        print("[MAIN] Cleaning up...")
 
        for uid in list(continuity_state.keys()):
            try:
                save_persistent_state_to_db(uid)
            except Exception as e:
                print(f"[MAIN] Flush error for {uid}: {e}")
 
        if background_task and not background_task.done():
            background_task.cancel()
            try:
                await background_task
            except asyncio.CancelledError:
                pass
 
        try:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
        except Exception as e:
            print(f"[MAIN] Shutdown error: {e}")
 
        print("[MAIN] Done.")
 
 
if __name__ == "__main__":
    print("[STARTUP] Starting Megan with Claude Opus 4.7...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[STARTUP] Interrupted")
    except Exception as e:
        print(f"[STARTUP] Fatal: {type(e).__name__}: {e}")
        traceback.print_exc()
