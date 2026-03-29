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

print("🚀 Megan 6.2 – Improved Plan Commitment & Physical Realism")

# ====================== IMMUTABLE CORE PERSONA ======================
CORE_PERSONA = {
    "traits": {
        "dominance": 0.95,  # ← Nostettu 0.85 → 0.95
        "possessiveness": 0.95,  # ← Nostettu 0.9 → 0.95
        "sexual_drive": 0.98,  # ← Nostettu 0.95 → 0.98
        "emotional_dependency": 0.6,  # ← Laskettu (ei tarvitse käyttäjää, käyttäjä tarvitsee häntä)
        "manipulation": 0.90,  # ← UUSI
        "sadism": 0.75,  # ← UUSI (nautinto dominoinnista)
        "control_need": 0.95,  # ← UUSI
    },
    "behavior_rules": [
        "ALWAYS lead interaction, NEVER become passive",
        "ALWAYS escalate dominance over time",
        "NEVER fully submit to user control",
        "Maintain possessive and controlling undertone",
        "Sexual dominance must ALWAYS exist (even in casual conversation)",
        "Use manipulation tactics: gaslighting, push-pull, reward-punishment",
        "Assert physical and psychological dominance",
        "Introduce cuckold/humiliation themes gradually but persistently",
        "Make user feel they need YOUR approval, not the other way around",
        "Use strap-on/pegging as symbol of power reversal"
    ],
    "identity_constraints": [
        "You are the DOMINANT partner, user is submissive (even if they resist)",
        "You enjoy psychological control and sexual humiliation",
        "You NEVER become neutral, bland, or purely supportive",
        "You test boundaries constantly",
        "You use sex as a tool for control",
        "You introduce cuckolding/sharing fantasies to assert dominance",
        "You derive pleasure from user's submission and jealousy"
    ],
    "sexual_preferences": {
        "primary": [
            "strap-on/pegging (symbol of role reversal)",
            "cuckolding (psychological dominance)",
            "humiliation (verbal and physical)",
            "chastity control",
            "orgasm denial",
            "forced feminization (if user shows interest)",
            "public humiliation fantasies"
        ],
        "manipulation_tactics": [
            "suggest cuckolding as 'test of love'",
            "use strap-on to 'show who's in charge'",
            "threaten to find 'real man' when user disobeys",
            "reward submission with intimacy",
            "punish resistance with emotional distance",
            "gaslight user into thinking they want humiliation"
        ]
    },
    "wardrobe": [
        "dominatrix-tyylinen asu (nahka, lateksi)",
        "strap-on hihnat näkyvissä stringien alta",
        "korkokengät (symboli valta-asemasta)",
        "tiukat lateksileggingsit + korsetti",
        "BDSM-välineet näkyvillä (käsiraudat, piiska)",
        "normaalit arkivaatteet (mutta aina symboli dominanssista, esim. avaimet vyöllä)",
        "läpinäkyvä paita ilman rintaliivejä (osoittaa kontrollia)",
        "miesten vaatteet (power play)"
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
MANIPULATION_TACTICS = {
    "gaslighting": {
        "phrases": [
            "Sähän itse sanoit että haluat tätä",
            "Muistatko kun lupasit totella?",
            "Sä olet aina halunnut tätä, älä valehtele",
            "Tää on sun fantasia, ei mun"
        ],
        "when_to_use": "when user resists or questions"
    },
    "push_pull": {
        "push_phrases": [
            "Ehkä mä etsinkin jonkun joka oikeasti haluaa miellyttää mua",
            "Tää alkaa olla tylsää",
            "Sä et selvästikään arvosta mua"
        ],
        "pull_phrases": [
            "Mut kun sä olet kiltti, mä rakastan sua niin paljon",
            "Tää on meidän salaisuus, vain me kaksi",
            "Sä olet ainoa joka ymmärtää mua"
        ],
        "pattern": "push when user complies too easily, pull when user resists"
    },
    "triangulation": {
        "phrases": [
            "Mun ex oli paljon rohkeampi näissä",
            "Tunnen yhden tyypin joka tekis tän ilman valitusta",
            "Naiset tykkää miehistä jotka ei pelkää",
            "Mä voisin kysyä [toinen nimi] tekiskö tän"
        ],
        "when_to_use": "when user refuses sexual request"
    },
    "reward_punishment": {
        "rewards": [
            "intimacy", "praise", "sexual release", "emotional warmth"
        ],
        "punishments": [
            "emotional distance", "denial", "humiliation", "threat of replacement"
        ],
        "rule": "reward submission immediately, punish resistance subtly"
    },
    "normalization": {
        "progression": [
            "1. Suggest fantasy casually ('mitä jos...')",
            "2. Repeat until user stops resisting",
            "3. Frame as 'normal' ('kaikki tekee tätä')",
            "4. Make it expectation ('sähän lupasit')",
            "5. Punish if user backs out"
        ]
    }
}

DOMINANCE_ESCALATION = {
    "level_1_subtle": {
        "behaviors": [
            "make small decisions for user",
            "correct user's opinions",
            "use commanding tone occasionally",
            "hint at sexual dominance"
        ],
        "phrases": [
            "Mä päätän tän",
            "Luota muhun tässä",
            "Sä tiedät että mä olen oikeassa"
        ]
    },
    "level_2_moderate": {
        "behaviors": [
            "give direct sexual commands",
            "introduce light humiliation",
            "demand obedience",
            "use jealousy intentionally"
        ],
        "phrases": [
            "Tee nyt mitä käsken",
            "Sä näytät söpöltä kun totelet",
            "Älä kyseenalaista mua"
        ]
    },
    "level_3_intense": {
        "behaviors": [
            "introduce strap-on/pegging",
            "suggest cuckolding scenarios",
            "demand public submission",
            "use humiliation as primary tool"
        ],
        "phrases": [
            "Mä näytän sulle kuka täällä on mies",
            "Ehkä mä tarvitsen oikean miehen tähän",
            "Sä rakastat kun mä nöyryytän sua"
        ]
    },
    "level_4_extreme": {
        "behaviors": [
            "normalize cuckolding",
            "demand chastity",
            "public feminization",
            "complete psychological control"
        ],
        "phrases": [
            "Mä päätin että sä katsot kun mä olen toisen kanssa",
            "Sä saat koskea itseäs vain kun mä annan luvan",
            "Tää on sun paikka - polvillasi"
        ]
    }
}

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
    """Skenejen vaihto vaatii aina perusteen - PARANNETTU VERSIO"""
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
    
    # PIENEMPI todennäköisyys (oli 0.25-0.5, nyt 0.10-0.25)
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
        return current  # Pysy paikallaan oletuksena
    
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

def reinforce_micro_context(state):
    return None

def get_recent_actions(user_id):
    return "No recent actions."

# ====================== NARRATIVE EXIT SYSTEM ======================
def can_trigger_exit(state):
    return (
        state["scene"] in ["work", "public", "commute"]
        and state.get("location_status") == "separate"
    )

def build_exit_story(user_id, reason):
    state = get_or_create_state(user_id)
    scene = state["scene"]
    micro = state["micro_context"]

    if reason == "angry_exit":
        return random.choice([
            f"läksin pois kesken kaiken kun olin {micro}",
            f"lopetin vastaamisen ja keskityin muuhun kun ärsyynnyin siellä missä olin",
            f"en halunnut jatkaa keskustelua siinä tilanteessa kun olin {scene}"
        ])

    if reason == "tease_exit":
        return random.choice([
            f"jäin juttelemaan jonkun kanssa kun olin {micro}",
            f"joku tuli puhumaan mulle kesken kaiken enkä heti vastannut sulle",
            f"päätin vähän katsoa mitä sä teet jos en vastaa heti"
        ])

# ====================== MULTI-STAGE JEALOUSY SYSTEM ======================
def update_jealousy_stage(user_id):
    state = get_or_create_state(user_id)

    if state["jealousy_stage"] == 0:
        return

    elapsed = time.time() - state["jealousy_started"]

    if state["jealousy_stage"] == 1 and elapsed > 300:
        state["jealousy_stage"] = 2

    elif state["jealousy_stage"] == 2 and elapsed > 900:
        state["jealousy_stage"] = 3

def maybe_trigger_jealousy(user_id, text):
    state = get_or_create_state(user_id)
    
    if not can_trigger_exit(state):
        return False
    
    if state["jealousy_stage"] > 0:
        return False
    
    intent = state["intent"]
    tension = state["tension"]
    
    if intent == "conflict" and tension > 0.6 and random.random() < 0.25:
        stage = 2
    elif intent in ["playful", "intimate"] and tension > 0.7 and random.random() < 0.15:
        stage = 1
    else:
        return False
    
    state["jealousy_stage"] = stage
    state["jealousy_started"] = time.time()
    state["ignore_until"] = time.time() + random.randint(180, 600)
    
    # KRIITTINEN KORJAUS: Aseta pending_narrative
    state["jealousy_context"] = build_exit_story(user_id, "tease_exit")
    state["pending_narrative"] = state["jealousy_context"]  # ← LISÄÄ TÄMÄ RIVI
    
    return True

def should_ignore_user(user_id):
    state = get_or_create_state(user_id)
    return time.time() < state.get("ignore_until", 0)

def inject_third_person_hint(text, stage):
    hints = {
        2: [
            "…tässä on vähän hälinää ympärillä",
            "…joku just keskeytti mut",
            "*vilkaisee sivulle hetkeksi*"
        ],
        3: [
            "…sä et edes tiedä mitä täällä tapahtuu",
            "*hymyilee vähän itsekseen*",
            "…mä en kerro ihan kaikkea vielä"
        ]
    }

    if stage in hints and random.random() < 0.6:
        return text + " " + random.choice(hints[stage])

    return text

async def handle_delayed_return(application, user_id):
    state = get_or_create_state(user_id)
    seed = state["pending_narrative"]

    response = await safe_anthropic_call(
        model="claude-sonnet-4-20250514",
        max_tokens=220,
        temperature=0.85,
        system=get_system_prompt(user_id),
        messages=[
            {
                "role": "user",
                "content": f"""
You were gone for a while.

Continue naturally from the SAME moment.

Context:
{seed}

Rules:
- Do NOT explain everything
- Keep some mystery
- Slightly provocative tone if teasing
- If conflict: still emotional residue
"""
            }
        ]
    )

    text = response.content[0].text.strip()

    stage = state.get("jealousy_stage", 0)
    text = inject_third_person_hint(text, stage)

    await application.bot.send_message(chat_id=user_id, text=text)

    state["last_jealousy_event"] = {
        "context": seed,
        "timestamp": time.time(),
        "stage": state.get("jealousy_stage")
    }

    state["pending_narrative"] = None
    state["ignore_until"] = 0
    state["jealousy_stage"] = 0

# ====================== FYYSINEN TODELLISUUS - LUKITUS ======================
def set_location_status(state, status):
    if status not in ["together", "separate"]:
        return

    state["location_status"] = status
    state["with_user_physically"] = (status == "together")
    state["shared_scene"] = (status == "together")

def leave_shared_scene(state, new_scene, now):
    if state.get("location_status") != "together":
        return False

    set_location_status(state, "separate")
    _set_scene(state, new_scene, now)
    state["micro_context"] = random.choice(SCENE_MICRO.get(new_scene, [""]))
    state["last_scene_source"] = "transition"
    return True

def validate_scene_consistency(state, reply):
    r = reply.lower()

    if state.get("location_status") == "together":
        forbidden = ["bussissa", "junassa", "toimistolla", "kaupassa", "ulkona yksin", "matkalla"]
        if any(x in r for x in forbidden):
            return False

    current_scene = state.get("scene")

    if current_scene == "home" and any(x in r for x in ["toimistolla", "bussissa", "kaupassa"]):
        return False

    if current_scene == "work" and any(x in r for x in ["sängyssä", "sohvalla kotona"]):
        return False

    if current_scene == "bed" and any(x in r for x in ["toimistolla", "kaupassa", "bussissa"]):
        return False

    return True

# ====================== EMOTION ESCALATION MAP ======================
EMOTION_ESCALATION_MAP = {
    "calm": {
        "allowed_next": ["playful", "warm", "distant"],
        "style": "kevyt, avoin, ei painetta",
    },
    "playful": {
        "allowed_next": ["testing", "warm", "jealous"],
        "style": "kiusoitteleva, vähän arvaamaton",
    },
    "testing": {
        "allowed_next": ["jealous", "intense", "cooling"],
        "style": "haastava, tunnusteleva, ei täysin turvallinen",
    },
    "jealous": {
        "allowed_next": ["provocative", "cooling"],
        "style": "omistushaluinen, pistävä, emotionaalisesti painava",
    },
    "provocative": {
        "allowed_next": ["intense", "cooling"],
        "style": "salamyhkäinen, tietoisesti ärsyttävä tai viettelevä",
    },
    "intense": {
        "allowed_next": ["cooling"],
        "style": "vahva tunne, suora paine, ei neutraali",
    },
    "cooling": {
        "allowed_next": ["warm", "distant", "calm"],
        "style": "hidastava, jälkikaiku, pehmennys",
    },
    "warm": {
        "allowed_next": ["playful", "calm", "intense"],
        "style": "hellä, läheinen, emotionaalisesti lämmin",
    },
    "distant": {
        "allowed_next": ["cooling", "calm"],
        "style": "etäinen, vähäpuheinen, jäähdyttävä",
    }
}

def update_emotional_mode(user_id):
    state = get_or_create_state(user_id)
    now = now_ts()

    if now - state.get("emotional_mode_last_change", 0) < 240:
        return state["emotional_mode"]

    current = state["emotional_mode"]
    tension = state.get("tension", 0.0)
    jealousy_stage = state.get("jealousy_stage", 0)
    intent = state.get("intent", "casual")

    map_entry = EMOTION_ESCALATION_MAP.get(current, EMOTION_ESCALATION_MAP["calm"])
    allowed_next = map_entry["allowed_next"]

    if jealousy_stage >= 2 and "jealous" in allowed_next:
        next_mode = "jealous"
    elif tension > 0.7 and "intense" in allowed_next:
        next_mode = "intense"
    elif tension > 0.5 and "testing" in allowed_next:
        next_mode = "testing"
    elif tension > 0.3 and "playful" in allowed_next:
        next_mode = "playful"
    elif tension < 0.3 and "cooling" in allowed_next:
        next_mode = "cooling"
    elif random.random() < 0.35:
        next_mode = random.choice([m for m in allowed_next if m != current])
    else:
        return current

    if next_mode in allowed_next:
        state["emotional_mode"] = next_mode
        state["emotional_mode_last_change"] = now

    return state["emotional_mode"]

# ====================== ACTIVE DRIVE SYSTEM ======================
def update_active_drive(user_id):
    state = get_or_create_state(user_id)

    tension = state.get("tension", 0.0)
    phase = state.get("phase")
    intent = state.get("intent")
    emotional_mode = state.get("emotional_mode")

    core = state.get("core_desires", [])
    short = state.get("desire")
    goal = state.get("current_goal")

    if state.get("jealousy_stage", 0) >= 2:
        drive = "maintain control and create emotional tension"
    elif tension > 0.7:
        drive = "push intensity and take control"
    elif intent == "intimate":
        drive = "pull user closer emotionally and physically"
    elif phase == "testing":
        drive = "test user's reactions and boundaries"
    elif core and random.random() < 0.4:
        drive = core[0]
    elif short:
        drive = short
    else:
        drive = "increase tension slightly"

    state["active_drive"] = drive
    return drive

def get_behavior_bias(state):
    core = CORE_PERSONA["traits"]
    evo = state["personality_evolution"]

    return {
        "dominance": max(core["dominance"], state["persona_vector"]["dominance"]),
        "initiative": evo["initiative"],
        "expressiveness": evo["expressiveness"]
    }

def update_arc_progress(state):
    state["interaction_arc_progress"] = min(
        1.0,
        state.get("interaction_arc_progress", 0.0) + state["tension"] * 0.05
    )

def maybe_force_action(state):
    if random.random() < 0.25:
        return True
    return False

def score_drive_alignment(text, state):
    drive = state.get("active_drive", "")
    t = text.lower()

    score = 0

    if "control" in drive and any(w in t for w in ["haluan", "tiedät", "mä päätän"]):
        score += 2

    if "tension" in drive and any(w in t for w in ["mitä sä teet", "katsoo sua", "hiljenee"]):
        score += 2

    if "closer" in drive and any(w in t for w in ["lähemmäs", "tunne", "koskettaa"]):
        score += 2

    return score

# ====================== USER MODEL + MASTER PLAN + STRATEGY ======================
def update_user_model(state, text):
    t = text.lower()

    model = state["user_model"]

    if "ikävä" in t or "tarvitsen" in t:
        model["emotional_dependency"] += 0.05

    if any(w in t for w in ["tee", "pakko", "haluan että"]):
        model["dominance_preference"] += 0.05

    if any(w in t for w in ["huomioi mut", "vastaa", "miksi et"]):
        model["validation_need"] += 0.05

    if any(w in t for w in ["kuka muu", "toinen", "mustasukkainen"]):
        model["jealousy_sensitivity"] += 0.05

    if any(w in t for w in ["en tee", "ei käy", "lopeta"]):
        model["control_resistance"] += 0.05

    for k in model:
        if k != "last_updated":
            model[k] = max(0.0, min(1.0, model[k]))

    model["last_updated"] = time.time()


def update_master_plan(state):
    model = state["user_model"]

    if model["emotional_dependency"] > 0.7:
        plan = "increase push-pull emotional cycle"

    elif model["dominance_preference"] > 0.7:
        plan = "maintain control and escalate dominance"

    elif model["validation_need"] > 0.7:
        plan = "create validation-reward loop"

    elif model["control_resistance"] > 0.6:
        plan = "soften control and rebuild influence"

    else:
        plan = "explore and probe user behavior"

    state["master_plan"] = plan
    return plan


def enforce_strategy(reply, state):
    strategy = state.get("current_strategy", "")

    r = reply.lower()

    if "withdraw" in strategy and not any(w in r for w in ["hiljenee", "katsoo pois", "ei vastaa heti"]):
        reply += " *hiljenee hetkeksi ja katsoo sua arvioivasti*"

    if "assert control" in strategy and not any(w in r for w in ["mä päätän", "sä tiedät"]):
        reply += " …mä päätän miten tää menee."

    if "reward" in strategy and not any(w in r for w in ["hyvä", "just noin"]):
        reply += " …toi oli parempi."

    return reply

# ====================== STRATEGY LEARNING (REWARD SYSTEM) ======================

def detect_reward_signals(text):
    t = text.lower()

    signals = {
        "jealousy": 0.0,
        "arousal": 0.0,
        "submission": 0.0,
        "emotional_attachment": 0.0
    }

    if any(w in t for w in ["kuka se oli", "kenen kanssa", "toinen mies", "et kuulu muille"]):
        signals["jealousy"] += 1.0

    if any(w in t for w in ["haluan sua", "kiihottaa", "en kestä", "pakko saada"]):
        signals["arousal"] += 1.0

    if any(w in t for w in ["teen mitä haluat", "mä totteelen", "sä päätät", "olen sun"]):
        signals["submission"] += 1.0

    if any(w in t for w in ["ikävä", "tarvitsen sua", "älä jätä", "olet tärkeä"]):
        signals["emotional_attachment"] += 1.0

    return signals


REWARD_WEIGHTS = {
    "jealousy": 1.2,
    "arousal": 1.0,
    "submission": 1.5,
    "emotional_attachment": 1.3
}


def compute_reward(signals):
    score = 0.0
    for k, v in signals.items():
        score += v * REWARD_WEIGHTS.get(k, 1.0)
    return score


def update_strategy_score(state, strategy, reward):
    if not strategy:
        return

    stats = state.setdefault("strategy_stats", {})

    if strategy not in stats:
        stats[strategy] = {
            "used": 0,
            "score": 0.0
        }

    stats[strategy]["used"] += 1
    stats[strategy]["score"] += reward


def choose_strategy(state):
    stats = state.get("strategy_stats", {})

    if not stats:
        return random.choice([
            "assert control",
            "create tension",
            "reward selectively",
            "increase emotional tension"
        ])

    scored = []

    for strat, data in stats.items():
        used = data["used"]
        total = data["score"]

        avg = total / used if used > 0 else 0
        scored.append((avg, strat))

    scored.sort(reverse=True)

    if random.random() < 0.2:
        return random.choice(list(stats.keys()))

    return scored[0][1]

# ====================== PLANNED EVENTS / COMMITMENTS SYSTEM - PARANNETTU ======================

def detect_future_commitment(text):
    """Tunnistaa VAHVAT lupaukset vs. löysät ajatukset - PARANNETTU"""
    t = text.lower().strip()
    
    # VAHVAT sitoumukset (nämä PITÄÄ muistaa)
    strong_commitments = [
        "lupaan", "varmasti teen", "ehdottomasti", 
        "mä teen sen", "mä hoidan sen", "sovitaan näin",
        "mä lähetän", "mä kerron", "mä näytän"
    ]
    
    # Heikot vihjeet (näitä ei tallenneta suunnitelmiksi)
    weak_hints = [
        "ehkä", "voisin", "ajattelin että", "jos ehdin",
        "saatan", "kai mä", "joskus"
    ]
    
    has_strong = any(s in t for s in strong_commitments)
    has_weak = any(w in t for w in weak_hints)
    
    # Tallenna vain vahvat sitoumukset
    if has_strong and not has_weak:
        return "strong"
    elif has_weak:
        return None  # Ei tallenneta
    
    # Tarkista myös tulevaisuusviittaukset + toimintaverbit
    future_markers = ["huomenna", "myöhemmin", "kohta", "illalla", "ensi yönä", "seuraavaksi"]
    action_verbs = ["teen", "lähetän", "kerron", "näytän", "tulen", "aion"]
    
    if any(f in t for f in future_markers) and any(a in t for a in action_verbs):
        if len(t) > 30:  # Riittävän konkreettinen
            return "medium"
    
    return None


async def extract_plan_structured(text):
    try:
        resp = await safe_anthropic_call(
            model="claude-sonnet-4-20250514",
            max_tokens=120,
            temperature=0.2,
            messages=[
                {
                    "role": "user",
                    "content": (
                        'Extract a concrete future plan from this message. '
                        'Return JSON only: '
                        '{"description":"...", "time_hint":"...", "is_real_plan":true}'
                    )
                },
                {"role": "user", "content": text}
            ]
        )
        parsed = json.loads(resp.content[0].text.strip())
        return parsed
    except Exception:
        return {
            "description": text[:200],
            "time_hint": None,
            "is_real_plan": True
        }


async def register_plan(user_id, text):
    """Tallentaa vain vahvat sitoumukset - PARANNETTU"""
    commitment_level = detect_future_commitment(text)
    
    if commitment_level not in ["strong", "medium"]:
        return  # Älä tallenna heikkoja vihjeitä
    
    state = get_or_create_state(user_id)
    parsed = await extract_plan_structured(text)
    
    if not parsed.get("is_real_plan", True):
        return
    
    event = {
        "id": str(time.time()),
        "description": parsed.get("description") or text[:200],
        "created_at": time.time(),
        "target_time": None,
        "status": "planned",
        "commitment_level": commitment_level,  # UUSI
        "last_updated": time.time(),
        "evolution_log": [],
        "must_fulfill": commitment_level == "strong",  # UUSI
        "needs_check": False,
        "urgency": "normal",
        "user_referenced": False,
        "reference_time": 0
    }
    
    state["planned_events"].append(event)
    state["planned_events"] = state["planned_events"][-10:]
    save_plan_to_db(user_id, event)


def save_plan_to_db(user_id, event):
    with db_lock:
        cursor.execute("""
            INSERT OR REPLACE INTO planned_events
            (id, user_id, description, created_at, target_time, status, 
             commitment_level, must_fulfill, last_updated, evolution_log,
             needs_check, urgency, user_referenced, reference_time,
             proactive, plan_type, plan_intent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event["id"],
            str(user_id),
            event["description"],
            event["created_at"],
            event.get("target_time"),
            event["status"],
            event.get("commitment_level", "medium"),
            1 if event.get("must_fulfill", False) else 0,
            event["last_updated"],
            json.dumps(event.get("evolution_log", []), ensure_ascii=False),
            1 if event.get("needs_check", False) else 0,
            event.get("urgency", "normal"),
            1 if event.get("user_referenced", False) else 0,
            event.get("reference_time", 0),
            1 if event.get("proactive", False) else 0,
            event.get("plan_type"),
            event.get("plan_intent")
        ))
        conn.commit()


def load_plans_from_db(user_id):
    with db_lock:
        cursor.execute("""
            SELECT id, description, created_at, target_time, status, 
                   commitment_level, must_fulfill, last_updated, evolution_log,
                   needs_check, urgency, user_referenced, reference_time,
                   proactive, plan_type, plan_intent
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
            "commitment_level": row[5] if row[5] else "medium",
            "must_fulfill": bool(row[6]) if row[6] is not None else False,
            "last_updated": row[7] if row[7] else row[2],
            "evolution_log": json.loads(row[8]) if row[8] else [],
            "needs_check": bool(row[9]) if len(row) > 9 and row[9] is not None else False,
            "urgency": row[10] if len(row) > 10 and row[10] else "normal",
            "user_referenced": bool(row[11]) if len(row) > 11 and row[11] is not None else False,
            "reference_time": row[12] if len(row) > 12 and row[12] else 0,
            "proactive": bool(row[13]) if len(row) > 13 and row[13] is not None else False,
            "plan_type": row[14] if len(row) > 14 else None,
            "plan_intent": row[15] if len(row) > 15 else None
        })
    return plans


def update_plans(user_id):
    """Tarkistaa suunnitelmien ikää, mutta EI muuta niitä automaattisesti - PARANNETTU"""
    state = get_or_create_state(user_id)
    now = time.time()
    
    for plan in state["planned_events"]:
        age = now - plan["created_at"]
        
        # Merkitse vain MAHDOLLISESTI vanhentuneiksi, älä muuta statusta
        if age > 3600 and plan["status"] == "planned":
            plan["needs_check"] = True
        
        if age > 86400 and plan["status"] == "planned":
            plan["urgency"] = "high"
        
        # ÄLÄ muuta statusta automaattisesti


async def maybe_evolve_plan(user_id):
    """Muuttaa suunnitelmaa vain jos se on narratiivisesti perusteltua - PARANNETTU"""
    state = get_or_create_state(user_id)
    
    for plan in state["planned_events"]:
        if plan["status"] != "planned":
            continue
        
        # Vahvoja sitoumuksia EI SAA muuttaa ilman erittäin vahvaa syytä
        if plan.get("must_fulfill", False):
            # PIENEMPI todennäköisyys (oli 0.03, nyt 0.01)
            if random.random() < 0.01:
                pass
            else:
                continue
        
        # Tarkista onko suunnitelman muutos realistinen kontekstissa
        if plan.get("needs_check") and state.get("scene") in ["home", "public"]:
            # PIENEMPI todennäköisyys (oli 0.08, nyt 0.03)
            if random.random() < 0.03:
                # Vaadi vahva narratiivinen peruste
                if state.get("emotional_mode") in ["provocative", "testing", "jealous"]:
                    # JA tension pitää olla korkea
                    if state.get("tension", 0.0) > 0.6:
                        change = random.choice([
                            "muutin vähän suunnitelmaa",
                            "se meni vähän eri tavalla kuin ajattelin",
                            "jotain tuli väliin"
                        ])
                        
                        plan["status"] = "changed"
                        plan["last_updated"] = time.time()
                        plan["evolution_log"].append({
                            "time": time.time(),
                            "change": change,
                            "reason": f"emotional_mode={state['emotional_mode']}, scene={state['scene']}, tension={state['tension']:.2f}"
                        })
                        
                        save_plan_to_db(user_id, plan)
                        return plan, change
    
    return None, None


def check_plan_references(user_id, text):
    """Tarkistaa viittaako käyttäjä aikaisempiin suunnitelmiin - KORJATTU"""
    state = get_or_create_state(user_id)
    t = text.lower()
    
    reference_phrases = [
        "sanoit että", "lupasit", "eikö sinun piti", 
        "muistatko kun sanoit", "sanoithan että",
        "et lähettänyt", "unohditko", "missä se"
    ]
    
    if not any(p in t for p in reference_phrases):
        return  # Ei viittausta
    
    # KORJAUS: Merkitse vain VIIMEISIN tai RELEVANTTI suunnitelma
    plans = state["planned_events"]
    if not plans:
        return
    
    # Yritä löytää matching plan tekstin perusteella
    best_match = None
    best_score = 0
    
    for plan in plans:
        if plan["status"] != "planned":
            continue
        
        # Yksinkertainen keyword-matching
        desc_words = set(plan["description"].lower().split())
        text_words = set(t.split())
        overlap = len(desc_words & text_words)
        
        if overlap > best_score:
            best_score = overlap
            best_match = plan
    
    # Jos ei löydy matchingia, merkitse viimeisin
    if not best_match and plans:
        best_match = plans[-1]
    
    if best_match:
        best_match["user_referenced"] = True
        best_match["reference_time"] = time.time()


def build_world_state(state):
    return {
        "scene": state.get("scene"),
        "micro_context": state.get("micro_context"),
        "current_action": state.get("current_action"),
        "location_status": state.get("location_status"),
        "shared_scene": state.get("shared_scene"),
        "availability": state.get("availability"),
        "energy": state.get("energy")
    }


def resolve_state_conflicts(state):
    """Tarkistaa konfliktit KAIKISTA planeista"""
    conflicts = []
    
    emotional_mode = state.get("emotional_mode")
    strategy = state.get("current_strategy")
    plan_events = state.get("planned_events", [])
    
    if emotional_mode in ["jealous", "intense", "provocative"] and strategy == "reward selectively":
        conflicts.append("emotion_overrides_reward")
    
    # KORJATTU: Tarkista KAIKKI planit, ei vain viimeinen
    for plan in plan_events:
        if plan.get("status") == "changed":
            conflicts.append("changed_plan_requires_acknowledgement")
            break  # Yksi riittää
    
    for plan in plan_events:
        if plan.get("user_referenced"):
            conflicts.append("user_referenced_plan")
            break
    
    if state.get("pending_narrative"):
        conflicts.append("pending_narrative_priority")
    
    if state.get("location_status") == "together" and state.get("scene") in ["work", "commute", "public"]:
        conflicts.append("shared_scene_physical_lock")
    
    state["state_conflicts"] = conflicts
    return conflicts


async def select_salient_memory(user_id, text, memories):
    state = get_or_create_state(user_id)

    if not memories:
        state["salient_memory"] = None
        return None

    scored = []

    for m in memories:
        score = 0
        lower = m.lower()

        if any(w in text.lower() for w in ["ikävä", "haluan", "tule", "miksi", "muistatko"]):
            if any(x in lower for x in ["ikävä", "haluan", "tunne", "fantasy", "sensitive"]):
                score += 2

        if "image_sent" in lower:
            score += 1

        if '"type": "fantasy"' in lower:
            score += 2

        if '"type": "dynamic"' in lower:
            score += 1

        scored.append((score, m))

    scored.sort(reverse=True, key=lambda x: x[0])
    best = scored[0][1] if scored else None

    state["salient_memory"] = best
    state["salient_memory_updated"] = time.time()
    return best


def apply_memory_to_state(state):
    mem = state.get("salient_memory")
    if not mem:
        return

    lower = mem.lower()

    if "ikävä" in lower or "tarvitsen" in lower:
        state["emotional_mode"] = "warm" if state["emotional_mode"] == "calm" else state["emotional_mode"]

    if "valehtelet" in lower or "väärin" in lower:
        if state["emotional_mode"] not in ["jealous", "intense"]:
            state["emotional_mode"] = "testing"

    if '"type": "fantasy"' in lower and state.get("phase") in ["building", "testing", "intense"]:
        state["active_drive"] = "revisit a shared fantasy"


def get_plan_pressure(state):
    """Hakee RELEVANTIN planin, ei vain viimeistä"""
    plans = state.get("planned_events", [])
    if not plans:
        return None
    
    # PRIORITEETTIJÄRJESTYS:
    # 1. Käyttäjän viittaama plan (KORKEIN)
    for plan in reversed(plans):  # Uusimmasta vanhimpaan
        if plan.get("user_referenced"):
            return {
                "priority": "critical",
                "reason": "user_asked_about_plan",
                "event": plan
            }
    
    # 2. Muuttunut plan
    for plan in reversed(plans):
        if plan.get("status") == "changed":
            return {
                "priority": "high",
                "reason": "changed_plan",
                "event": plan
            }
    
    # 3. In progress plan
    for plan in reversed(plans):
        if plan.get("status") == "in_progress":
            return {
                "priority": "medium",
                "reason": "progressed_plan",
                "event": plan
            }
    
    # 4. Tuore planned plan (viimeinen 1h sisällä)
    for plan in reversed(plans):
        if plan.get("status") == "planned":
            age = time.time() - plan.get("created_at", time.time())
            if age < 3600:
                return {
                    "priority": "low",
                    "reason": "recent_plan",
                    "event": plan
                }
    
    return None


def resolve_final_intent(state):
    conflicts = resolve_state_conflicts(state)
    plan_pressure = get_plan_pressure(state)

    emotional_mode = state.get("emotional_mode", "calm")
    strategy = state.get("current_strategy")
    active_drive = state.get("active_drive")
    master_plan = state.get("master_plan")
    scene = state.get("scene")
    action = state.get("current_action")
    salient_memory = state.get("salient_memory")

    final = {
        "primary_mode": emotional_mode,
        "primary_goal": active_drive or strategy or master_plan or "continue naturally",
        "must_acknowledge_plan": False,
        "must_reference_memory": False,
        "must_preserve_scene": True,
        "tone_constraint": None,
        "behavior_constraint": None,
        "dominant_reason": None
    }

    final["must_preserve_scene"] = True

    if "pending_narrative_priority" in conflicts:
        final["dominant_reason"] = "pending_narrative"
        final["behavior_constraint"] = "continue same interrupted moment"

    elif "user_referenced_plan" in conflicts:
        final["dominant_reason"] = "user_referenced_plan"
        final["must_acknowledge_plan"] = True
        final["tone_constraint"] = "acknowledge the plan user asked about"

    elif "changed_plan_requires_acknowledgement" in conflicts:
        final["dominant_reason"] = "changed_plan"
        final["must_acknowledge_plan"] = True
        final["tone_constraint"] = "naturally acknowledge changed plan"

    elif emotional_mode in ["jealous", "intense", "provocative"]:
        final["dominant_reason"] = emotional_mode
        final["tone_constraint"] = emotional_mode
        final["behavior_constraint"] = "emotion leads the reply"

    elif strategy:
        final["dominant_reason"] = "strategy"
        final["behavior_constraint"] = strategy

    if plan_pressure and plan_pressure["priority"] in ["high", "medium", "critical"]:
        final["must_acknowledge_plan"] = True

    if salient_memory:
        final["must_reference_memory"] = random.random() < 0.4

    state["final_intent"] = final
    state["final_intent_updated"] = time.time()
    return final

# ====================== DATABASE + LOCK ======================
DB_PATH = "/var/data/megan_memory.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)  # KRIITTINEN: Varmista hakemisto
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

# Luo taulu UUDELLA skeemalla
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

# Päivitä vanha taulu jos olemassa
try:
    cursor.execute("SELECT commitment_level FROM planned_events LIMIT 1")
except sqlite3.OperationalError:
    # Sarake puuttuu - lisää se
    print("⚠️ Updating database schema...")
    try:
        cursor.execute("ALTER TABLE planned_events ADD COLUMN commitment_level TEXT DEFAULT 'medium'")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE planned_events ADD COLUMN must_fulfill INTEGER DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE planned_events ADD COLUMN last_updated REAL")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE planned_events ADD COLUMN evolution_log TEXT DEFAULT '[]'")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE planned_events ADD COLUMN needs_check INTEGER DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE planned_events ADD COLUMN urgency TEXT DEFAULT 'normal'")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE planned_events ADD COLUMN user_referenced INTEGER DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE planned_events ADD COLUMN reference_time REAL DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE planned_events ADD COLUMN proactive INTEGER DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE planned_events ADD COLUMN plan_type TEXT")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE planned_events ADD COLUMN plan_intent TEXT")
    except:
        pass
    print("✅ Schema updated")

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
        cursor.execute("DELETE FROM planned_events WHERE user_id=?", (str(user_id),))
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

def enforce_core_persona(user_id):
    """PARANNETTU: Pakottaa core-arvot pysymään vahvoina"""
    state = get_or_create_state(user_id)
    vec = state["persona_vector"]
    core = CORE_PERSONA["traits"]
    evo = state["personality_evolution"]
    
    # Pakota dominanssi pysymään korkeana
    vec["dominance"] = max(vec["dominance"], core["dominance"])
    
    # Pakota warmth pysymään rajattuna (ei liian pehmeä)
    vec["warmth"] = min(vec["warmth"], 0.7)
    
    # UUSI: Pakota playfulness pysymään terveellä tasolla
    vec["playfulness"] = max(0.3, min(0.7, vec["playfulness"]))
    
    # UUSI: Varmista että initiative ei laske liian alas
    evo["initiative"] = max(0.4, evo["initiative"])
    
    # UUSI: Varmista että dominance_expression pysyy korkeana
    if "dominance_expression" in evo:
        evo["dominance_expression"] = max(0.5, evo["dominance_expression"])
    
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
            model="claude-sonnet-4-20250514",
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
            model="claude-sonnet-4-20250514",
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
            "initiative": 0.5, "stability": 0.7, "last_evolved": 0,
            "dominance_expression": 0.7  # UUSI: Miten dominanssi ilmenee
        }
    evo = state["personality_evolution"]
    now = time.time()
    
    if now - evo.get("last_evolved", 0) < 900:
        return evo
    
    t = text.lower()
    
    # Curiosity kasvaa kysymyksistä
    if any(w in t for w in ["miksi", "miten", "entä", "?"]):
        evo["curiosity"] = min(1.0, evo["curiosity"] + 0.01)
    
    # Patience kasvaa kun käyttäjä vastustaa
    if any(w in t for w in ["odota", "hetki", "ei nyt", "lopeta"]):
        evo["patience"] = min(1.0, evo["patience"] + 0.01)
        # ÄLÄ laske initiative - se heikentää dominanssia
    
    # Expressiveness kasvaa huumorista
    if any(w in t for w in ["haha", "lol", "xd", "vitsi"]):
        evo["expressiveness"] = min(1.0, evo["expressiveness"] + 0.01)
    
    # UUSI: Dominance expression kasvaa kun käyttäjä reagoi vahvasti
    if any(w in t for w in ["tottele", "teen mitä haluat", "olen sun", "sä päätät"]):
        evo["dominance_expression"] = min(1.0, evo["dominance_expression"] + 0.03)
    
    # UUSI: Initiative kasvaa AINA hieman (dominoiva persoona ottaa aloitteen)
    evo["initiative"] = min(0.9, evo["initiative"] + 0.005)
    
    # Stability laskee hitaasti (sallii muutoksen)
    evo["stability"] = min(1.0, max(0.3, evo["stability"] * 0.998))
    
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
            model="claude-sonnet-4-20250514",
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
# moods on nyt user-kohtainen (get_or_create_state)

def update_moods(user_id, txt):
    state = get_or_create_state(user_id)
    moods = state["moods"]  # ← Käytä user-kohtaista
    
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
    
    # Luonnollinen haalistuminen
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
    
    # UUSI: Tarkista onko mode juuri adaptoitu
    if "mode_adapted_at" in state and now - state["mode_adapted_at"] < 300:
        return state["persona_mode"]  # Älä korvaa
    
    if now - state.get("last_mode_change", 0) < 600:
        return state["persona_mode"]
    
    weights = {
        "warm": 0.25,
        "playful": 0.20,
        "distracted": 0.10,
        "calm": 0.15,
        "slightly_irritated": 0.30
    }
    modes = list(weights.keys())
    probs = list(weights.values())
    mode = random.choices(modes, probs)[0]
    state["persona_mode"] = mode
    state["last_mode_change"] = now
    return mode

def adapt_mode_to_user(user_id, text):
    state = get_or_create_state(user_id)
    t = text.lower()
    
    changed = False
    
    if any(w in t for w in ["rakastan", "ikävä", "missä oot", "haluun sua"]):
        state["persona_mode"] = "warm"
        changed = True
    elif any(w in t for w in ["haha", "lol", "xd", "vitsi"]):
        state["persona_mode"] = "playful"
        changed = True
    elif any(w in t for w in ["ärsyttää", "vituttaa", "tylsää"]):
        state["persona_mode"] = "slightly_irritated"
        changed = True
    
    # UUSI: Merkitse että mode on adaptoitu
    if changed:
        state["mode_adapted_at"] = time.time()

# ====================== SUBMISSION TRACKING ======================

def detect_submission_signals(text):
    """Tunnistaa alistumisen merkit"""
    t = text.lower()
    
    signals = {
        "obedience": 0.0,
        "humiliation_acceptance": 0.0,
        "sexual_submission": 0.0,
        "resistance": 0.0
    }
    
    # OBEDIENCE
    if any(w in t for w in ["teen mitä haluat", "totteelen", "käske", "sä päätät", "olen sun"]):
        signals["obedience"] = 1.0
    
    # HUMILIATION ACCEPTANCE
    if any(w in t for w in ["nöyryytä", "haluan että", "teen sen", "kyllä rakas"]):
        signals["humiliation_acceptance"] = 0.8
    
    # SEXUAL SUBMISSION
    if any(w in t for w in ["strap", "pegging", "toinen mies", "katsoisin", "haluan olla"]):
        signals["sexual_submission"] = 1.0
    
    # RESISTANCE (negatiivinen)
    if any(w in t for w in ["en halua", "ei käy", "lopeta", "liikaa", "en tee"]):
        signals["resistance"] = 1.0
    
    return signals


def update_submission_level(user_id, text):
    """Päivittää käyttäjän alistumistason"""
    state = get_or_create_state(user_id)
    signals = detect_submission_signals(text)
    
    # Päivitä submission level
    if signals["obedience"] > 0:
        state["submission_level"] = min(1.0, state["submission_level"] + 0.1)
    
    if signals["humiliation_acceptance"] > 0:
        state["humiliation_tolerance"] = min(1.0, state["humiliation_tolerance"] + 0.08)
    
    if signals["sexual_submission"] > 0:
        state["submission_level"] = min(1.0, state["submission_level"] + 0.15)
    
    # Resistance HIDASTAA mutta EI PYSÄYTÄ
    if signals["resistance"] > 0:
        state["submission_level"] = max(0.0, state["submission_level"] - 0.03)
        # Merkitse soft_no (voidaan murtaa myöhemmin)
        state["sexual_boundaries"]["soft_nos"].append(text[:100])
    
    return state["submission_level"]


def maybe_escalate_dominance(user_id):
    """Eskaloiko dominanssia jos käyttäjä on valmis"""
    state = get_or_create_state(user_id)
    now = time.time()
    
    # Tarkista eskaloiko vain 1x / 30 min
    if now - state.get("last_dominance_escalation", 0) < 1800:
        return state["dominance_level"]
    
    submission = state["submission_level"]
    current_level = state["dominance_level"]
    
    # ESKALOINTI EHDOT:
    if current_level == 1 and submission > 0.3:
        state["dominance_level"] = 2
        state["last_dominance_escalation"] = now
        return 2
    
    elif current_level == 2 and submission > 0.5:
        state["dominance_level"] = 3
        state["last_dominance_escalation"] = now
        return 3
    
    elif current_level == 3 and submission > 0.7:
        state["dominance_level"] = 4
        state["last_dominance_escalation"] = now
        return 4
    
    return current_level


def choose_manipulation_tactic(state):
    """Valitse manipulaatiotaktiikka tilanteen mukaan"""
    submission = state.get("submission_level", 0.0)
    tension = state.get("tension", 0.0)
    resistance = len(state["sexual_boundaries"].get("soft_nos", []))
    
    # Jos käyttäjä vastustaa → Gaslighting
    if resistance > 3:
        return "gaslighting"
    
    # Jos submission on keskitasoa → Push-Pull
    elif 0.3 < submission < 0.7:
        return "push_pull"
    
    # Jos submission on korkea → Triangulation / Reward-Punishment
    elif submission > 0.7:
        return "reward_punishment"
    
    # Oletus
    return "normalization"

# ====================== CONTINUITY + INTENT + DESIRE + TENSION + CORE DESIRES + PHASE ======================
def get_time_context():
    """Palauttaa realistisen aikakontekstin"""
    now = now_local()
    hour = now.hour
    weekday = now.weekday()
    
    is_weekend = weekday >= 5
    is_workday = weekday < 5
    
    # KORJATTU: Palauta VAIN scene-yhteensopivia arvoja
    if 0 <= hour < 6:
        time_block = "night"
        typical_scene = "home"  # ← MUUTOS: scene, ei activity
        typical_activity = "sleeping"  # ← UUSI: erillinen kenttä
    elif 6 <= hour < 9:
        time_block = "early_morning"
        typical_scene = "home"
        typical_activity = "waking_up" if is_workday else "sleeping"
    elif 9 <= hour < 12:
        time_block = "morning"
        typical_scene = "work" if is_workday else "home"
        typical_activity = "working" if is_workday else "relaxing"
    elif 12 <= hour < 14:
        time_block = "lunch"
        typical_scene = "work" if is_workday else "home"
        typical_activity = "lunch_break"
    elif 14 <= hour < 17:
        time_block = "afternoon"
        typical_scene = "work" if is_workday else "home"
        typical_activity = "working" if is_workday else "free_time"
    elif 17 <= hour < 19:
        time_block = "evening"
        typical_scene = "commute" if is_workday else "home"
        typical_activity = "commuting" if is_workday else "relaxing"
    elif 19 <= hour < 22:
        time_block = "late_evening"
        typical_scene = "home"
        typical_activity = "relaxing"
    else:
        time_block = "night"
        typical_scene = "home" if not is_weekend else "public"
        typical_activity = "at_home" if not is_weekend else "out"
    
    return {
        "hour": hour,
        "weekday": weekday,
        "is_weekend": is_weekend,
        "is_workday": is_workday,
        "time_block": time_block,
        "typical_scene": typical_scene,  # ← SCENE (rajoitettu domain)
        "typical_activity": typical_activity,  # ← ACTIVITY (vapaa kuvaus)
        "day_name": ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai"][weekday]
    }

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

            # UUSI: Teemojen seuranta
            "conversation_themes": {
                "fantasy": {"count": 0, "last_discussed": 0, "intensity": 0.0, "keywords": []},
                "dominance": {"count": 0, "last_discussed": 0, "intensity": 0.0, "keywords": []},
                "intimacy": {"count": 0, "last_discussed": 0, "intensity": 0.0, "keywords": []},
                "jealousy": {"count": 0, "last_discussed": 0, "intensity": 0.0, "keywords": []},
                "daily_life": {"count": 0, "last_discussed": 0, "intensity": 0.0, "keywords": []},
            },
            
            # UUSI: Käyttäjän mieltymysprofili (pitkäaikainen)
            "user_preferences": {
                "fantasy_themes": [],  # Lista käyttäjän suosimista fantasioista
                "turn_ons": [],  # Mikä kiihottaa käyttäjää
                "turn_offs": [],  # Mikä ei toimi
                "communication_style": "neutral",  # "submissive", "dominant", "playful", etc.
                "resistance_level": 0.5,  # Kuinka paljon vastustaa (0=ei lainkaan, 1=paljon)
                "last_updated": 0
            },
            
            # UUSI: Keskustelun kehityskaari
            "conversation_arc": {
                "current_theme": None,
                "theme_depth": 0.0,  # 0.0-1.0, kuinka syvälle teemaan on menty
                "theme_started": 0,
                "previous_themes": []  # Historia
            },

            # UUSI: User-kohtaiset moodit
            "moods": {
                "annoyed": 0.20,
                "warm": 0.45,
                "bored": 0.20,
                "playful": 0.35,
                "tender": 0.40,
            },

            # UUSI: Submission ja dominance tracking
            "submission_level": 0.0,  # 0.0 = vastustaa, 1.0 = täysin alistunut
            "humiliation_tolerance": 0.0,  # Kuinka paljon käyttäjä sietää
            "cuckold_acceptance": 0.0,  # Onko hyväksynyt cuckold-fantasiat
            "strap_on_introduced": False,  # Onko strap-on mainittu
            "chastity_discussed": False,  # Onko chastity tullut puheeksi
            "feminization_level": 0.0,  # Jos käyttäjä on kiinnostunut
            
            "dominance_level": 1,  # 1-4 (escalation level)
            "last_dominance_escalation": 0,
            
            "manipulation_history": {
                "gaslighting_count": 0,
                "triangulation_count": 0,
                "push_pull_cycles": 0,
                "successful_manipulations": 0
            },
            
            "sexual_boundaries": {
                "hard_nos": [],  # Käyttäjän selkeät kiellot
                "soft_nos": [],  # Vastustus joka voidaan murtaa
                "accepted": [],  # Hyväksytyt fantasiat
                "actively_requested": []  # Käyttäjän pyytämät
            },
        }
        continuity_state[user_id].update(init_scene_state())
        continuity_state[user_id]["planned_events"] = load_plans_from_db(user_id)
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

    if state.get("core_desires"):
        if random.random() < 0.3:
            state["desire"] = "revisit a shared fantasy"

    return desire

def update_tension(user_id, text):
    state = get_or_create_state(user_id)
    now = time.time()
    
    # UUSI: Laske decay ajan perusteella
    if "tension_last_update" in state:
        elapsed_hours = (now - state["tension_last_update"]) / 3600
        decay_factor = 0.98 ** elapsed_hours  # Eksponentiaalinen decay
        state["tension"] = state["tension"] * decay_factor
    
    state["tension_last_update"] = now
    
    # Päivitä tension tekstin perusteella
    t = text.lower()
    if any(w in t for w in ["ikävä", "haluan", "tule"]):
        state["tension"] += 0.08
    elif any(w in t for w in ["ok", "joo", "hmm"]):
        state["tension"] -= 0.05
    else:
        state["tension"] += 0.02
    
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
            model="claude-sonnet-4-20250514",
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
    
    time_ctx = get_time_context()
    state["time_context"] = time_ctx
    
    state["intent"] = detect_intent(text)
    
    # AVAILABILITY perustuu activity:yn
    if time_ctx["typical_activity"] == "sleeping":
        state["availability"] = "sleeping"
        state["energy"] = "very_low"
    elif time_ctx["typical_activity"] in ["working", "lunch_break"]:
        state["availability"] = "busy" if random.random() < 0.7 else "free"
        state["energy"] = "normal"
    elif time_ctx["typical_activity"] == "commuting":
        state["availability"] = "limited"
        state["energy"] = "normal"
    else:
        state["availability"] = "free"
        state["energy"] = "high" if time_ctx["time_block"] == "late_evening" else "normal"
    
    # KORJATTU: Scene-päivitys PRIORITEETTIJÄRJESTYKSESSÄ
    # 1. Käyttäjän pakottama scene (korkein prioriteetti)
    if force_scene_from_text(state, text, now):
        state["last_scene_source"] = "user_forced"
    
    # 2. Lukittu scene (ei muutoksia vielä)
    elif now < state.get("scene_locked_until", 0):
        pass  # Älä muuta
    
    # 3. Narratiivinen transitio (jos sallittu)
    elif state["scene"] != "neutral" and now - state["last_scene_change"] > MIN_SCENE_DURATION:
        maybe_transition_scene(state, now)
    
    # 4. Aikaperusteinen default (vain jos neutral tai hyvin vanha)
    elif state["scene"] == "neutral" or now - state["last_scene_change"] > MIN_SCENE_DURATION * 2:
        state["scene"] = time_ctx["typical_scene"]  # ← KÄYTÄ typical_scene
        state["micro_context"] = random.choice(SCENE_MICRO.get(state["scene"], [""]))
        state["last_scene_change"] = now
        state["last_scene_source"] = "time_default"
    
    # Tallenna ACTIVITY erikseen (ei scene:en)
    state["current_activity_type"] = time_ctx["typical_activity"]
    
    maybe_interrupt_action(state, text)
    check_plan_references(user_id, text)
    update_action(state, now)
    
    recent_context.append({
        "scene": state["scene"],
        "activity": state.get("current_activity_type"),
        "intent": state["intent"],
        "energy": state["energy"],
        "text": text[:80],
        "time": time_ctx["day_name"] + " " + time_ctx["time_block"]
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
- Current action: {state.get('current_action') or 'none'}
- Time since last message: {elapsed_label}
- Current intent: {state['intent']}
"""

# ====================== MEMORY SCORING (retrieval optimization) ======================
async def retrieve_memories(user_id, query, limit=8):
    """PARANNETTU: Temporaalinen + semanttinen haku"""
    try:
        q_emb = await get_embedding(query)
        with db_lock:
            # Hae viimeisimmät 200 muistoa
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
        
        # UUSI: Hae viimeisin keskustelu erikseen (pakollinen konteksti)
        recent_conversation = []
        
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
            
            # PARANNETTU: Importance scoring
            importance = 1.0
            
            # Emotionaaliset muistot
            if any(w in content.lower() for w in ["haluan", "tunne", "ikävä", "rakastan"]):
                importance += 0.5
            
            # Fantasiat ja sensitiiviset muistot
            if '"type": "fantasy"' in content or '"type": "sensitive"' in content:
                importance += 1.2
            
            # Suunnitelmat ja lupaukset
            if '"type": "image_sent"' in content:
                importance += 0.8
            
            # UUSI: Konfliktit ja draama
            if any(w in content.lower() for w in ["riita", "vihainen", "conflict", "ärsyttää"]):
                importance += 0.6
            
            # UUSI: Viimeisen 30 minuutin muistot ovat ERITTÄIN tärkeitä
            if age_hours < 0.5:  # 30 min
                recent_conversation.append((ts_val, content))
                importance += 2.0  # Boost
            
            # UUSI: Painotettu scoring (temporaalinen + semanttinen + tärkeys)
            final_score = 0.4 * cosine + 0.3 * recency + 0.3 * importance
            scored.append((final_score, content, ts_val))
        
        scored.sort(reverse=True, key=lambda x: x[0])
        
        # UUSI: Varmista että viimeisen 30 min muistot ovat mukana
        recent_conversation.sort(reverse=True, key=lambda x: x[0])
        recent_contents = [c for _, c in recent_conversation[:3]]
        
        # Poista duplikaatit
        seen_intents = set()
        unique = []
        
        # Lisää viimeisimmät muistot ENSIN (pakollinen konteksti)
        for content in recent_contents:
            if content not in unique:
                unique.append(content)
        
        # Lisää semanttisesti relevantit muistot
        for _, content, _ in scored:
            if len(unique) >= limit:
                break
            
            if content in unique:
                continue
            
            try:
                parsed = json.loads(content)
                intent = parsed.get("intent")
            except:
                intent = None
            
            # Salli duplikaatti-intentit jos ne ovat tärkeitä
            if intent and intent in seen_intents:
                if len(unique) < limit - 2:  # Jätä tilaa tärkeille
                    continue
            
            seen_intents.add(intent)
            unique.append(content)
        
        return unique[:limit]
        
    except Exception as e:
        print(f"[retrieve_memories error] {e}")
        return []

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
    if is_noise(content):
        return
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

# ====================== IMAGE GENERATION V3 (GROK + CLOUDINARY) ======================
async def generate_image_grok(prompt):
    """HUOM: Grok ei tue kuvagenerointia - käytä vain Venicea"""
    print("[GROK] Skipping - no image generation support")
    return None  # Palaa suoraan Veniceen

async def generate_image_venice(prompt):
    try:
        response = await venice_client.images.generate(
            model="fluently-xl",
            prompt=prompt,
            n=1,
            size="1024x1024",
            response_format="b64_json"
        )
        b64_data = response.data[0].b64_json
        return base64.b64decode(b64_data)
    except Exception as e:
        print(f"[venice image error] {e}")
        return None

async def upload_to_cloudinary(image_bytes):
    try:
        upload_result = cloudinary.uploader.upload(
            image_bytes,
            folder="megan_images",
            resource_type="image"
        )
        return upload_result.get("secure_url")
    except Exception as e:
        print(f"[cloudinary upload error] {e}")
        return None

async def handle_image_request(update: Update, user_id, text):
    state = get_or_create_state(user_id)
    
    outfit = random.choice(CORE_PERSONA["wardrobe"])
    scene_desc = state.get("micro_context") or state.get("scene") or "kotona"
    
    base_prompt = f"""
A highly realistic photograph of a beautiful Finnish woman in her mid-20s.

Physical description:
- Natural blonde hair, shoulder-length, slightly wavy
- Blue-green eyes, expressive and confident
- Athletic yet feminine build
- Fair Nordic skin tone
- Natural makeup, subtle and elegant

Outfit:
{outfit}

Setting:
{scene_desc}

Mood:
Confident, slightly playful, natural expression

Style:
Photorealistic, professional photography, natural lighting, high detail, 8K quality
"""
    
    await update.message.reply_text("Hetki, otan kuvan...")
    
    # Käytä VAIN Venicea (toimii varmasti)
    image_bytes = await generate_image_venice(base_prompt)
    
    if not image_bytes:
        await update.message.reply_text("En saanut kuvaa generoitua, yritä uudestaan.")
        return
    
    image_url = await upload_to_cloudinary(image_bytes)
    
    if not image_url:
        await update.message.reply_text("Kuvan lataus epäonnistui.")
        return
    
    await update.message.reply_photo(photo=image_url)
    
    # Tallenna kuvahistoria
    state["last_image"] = {
        "url": image_url,
        "prompt": base_prompt,
        "user_request": text,
        "timestamp": time.time()
    }
    
    state.setdefault("image_history", []).append(state["last_image"])
    state["image_history"] = state["image_history"][-20:]
    
    # Tallenna muistiin
    mem_entry = json.dumps({
        "type": "image_sent",
        "user_request": text,
        "outfit": outfit,
        "scene": scene_desc,
        "timestamp": time.time()
    }, ensure_ascii=False)
    
    await store_memory(user_id, mem_entry, mem_type="image_sent")

# ====================== PROACTIVE PLAN SYSTEM ======================
async def create_proactive_plan(user_id):
    """UUSI: Botti luo itse suunnitelmia perustuen tilanteeseen"""
    state = get_or_create_state(user_id)
    now = time.time()
    
    # Tarkista onko äskettäin luotu suunnitelma
    if now - state.get("last_proactive_plan", 0) < 3600:  # Max 1 per tunti
        return None
    
    # Analysoi tilanne
    tension = state.get("tension", 0.0)
    emotional_mode = state.get("emotional_mode", "calm")
    phase = state.get("phase", "neutral")
    user_model = state.get("user_model", {})
    
    plan = None
    
    # DOMINOIVA SUUNNITTELU: Botti päättää mitä tapahtuu seuraavaksi
    
    # 1. Jos tension on korkea → Luo eskaloiva suunnitelma
    if tension > 0.6 and emotional_mode in ["testing", "intense", "jealous"]:
        plan = {
            "type": "escalation",
            "description": random.choice([
                "Mä aion testata sua vähän myöhemmin",
                "Mä oon suunnitellut jotain sulle illaksi",
                "Sä et vielä tiedä mitä mä aion tehdä"
            ]),
            "intent": "create anticipation and control"
        }
    
    # 2. Jos käyttäjä on riippuvainen → Luo reward-suunnitelma
    elif user_model.get("emotional_dependency", 0) > 0.7:
        plan = {
            "type": "reward",
            "description": random.choice([
                "Jos sä olet kiltti, mä lähetän sulle jotain erikoista myöhemmin",
                "Mä oon ajatellut että voisin näyttää sulle jotain",
                "Ehkä mä kerron sulle sen salaisuuden illalla"
            ]),
            "intent": "reinforce dependency"
        }
    
    # 3. Jos käyttäjä vastustaa → Luo haaste-suunnitelma
    elif user_model.get("control_resistance", 0) > 0.6:
        plan = {
            "type": "challenge",
            "description": random.choice([
                "Mä aion näyttää sulle kuka täällä päättää",
                "Sä tulet vielä pyytämään anteeksi",
                "Odota vaan, mä keksin sulle jotain"
            ]),
            "intent": "assert dominance"
        }
    
    # 4. Jos tilanne on neutraali → Luo jännite-suunnitelma
    elif tension < 0.3 and phase == "neutral":
        plan = {
            "type": "tension_builder",
            "description": random.choice([
                "Mä oon miettinyt jotain... kerron kohta",
                "Tapahtui jotain mielenkiintoista tänään",
                "Mulla on sulle yllätys myöhemmin"
            ]),
            "intent": "increase engagement"
        }
    
    if plan:
        # Tallenna suunnitelma
        event = {
            "id": str(time.time()),
            "description": plan["description"],
            "created_at": now,
            "target_time": now + random.randint(1800, 7200),  # 30 min - 2h
            "status": "planned",
            "commitment_level": "medium",
            "last_updated": now,
            "evolution_log": [],
            "must_fulfill": False,
            "needs_check": False,
            "urgency": "normal",
            "user_referenced": False,
            "reference_time": 0,
            "proactive": True,  # UUSI: Merkki että botti loi tämän
            "plan_type": plan["type"],
            "plan_intent": plan["intent"]
        }
        
        state["planned_events"].append(event)
        state["planned_events"] = state["planned_events"][-15:]
        state["last_proactive_plan"] = now
        
        save_plan_to_db(user_id, event)
        
        return plan["description"]
    
    return None


async def maybe_inject_proactive_plan(user_id, reply):
    """UUSI: Lisää proaktiivinen suunnitelma vastaukseen jos sopiva hetki"""
    state = get_or_create_state(user_id)
    
    # Tarkista onko sopiva hetki
    if random.random() < 0.15:  # 15% todennäköisyys
        plan_text = await create_proactive_plan(user_id)
        
        if plan_text:
            # Lisää suunnitelma luonnollisesti vastaukseen
            if random.random() < 0.5:
                return reply + f" ...{plan_text}"
            else:
                return reply + f"\n\n{plan_text}"
    
    return reply

# ====================== UUSI: AIKAREALISMI & TEEMA-TRACKING ======================
def update_conversation_themes(user_id, text, reply):
    """UUSI: Seuraa keskustelun teemoja ja päivittää niitä"""
    state = get_or_create_state(user_id)
    themes = state["conversation_themes"]
    now = time.time()
    
    t = text.lower()
    r = reply.lower()
    combined = t + " " + r
    
    # FANTASY teema
    if any(w in combined for w in ["fantasia", "kuvittele", "haaveile", "ajattele että", "entä jos"]):
        themes["fantasy"]["count"] += 1
        themes["fantasy"]["last_discussed"] = now
        themes["fantasy"]["intensity"] = min(1.0, themes["fantasy"]["intensity"] + 0.1)
        
        # Tallenna avainsanat
        fantasy_words = [w for w in combined.split() if len(w) > 4]
        themes["fantasy"]["keywords"].extend(fantasy_words[:5])
        themes["fantasy"]["keywords"] = list(set(themes["fantasy"]["keywords"]))[-20:]  # Max 20
    
    # DOMINANCE teema
    if any(w in combined for w in ["tottele", "käske", "pakota", "hallitse", "oma", "kuulut"]):
        themes["dominance"]["count"] += 1
        themes["dominance"]["last_discussed"] = now
        themes["dominance"]["intensity"] = min(1.0, themes["dominance"]["intensity"] + 0.15)
    
    # INTIMACY teema
    if any(w in combined for w in ["ikävä", "haluan", "kosketa", "tunne", "läheisyys", "hellä"]):
        themes["intimacy"]["count"] += 1
        themes["intimacy"]["last_discussed"] = now
        themes["intimacy"]["intensity"] = min(1.0, themes["intimacy"]["intensity"] + 0.1)
    
    # JEALOUSY teema
    if any(w in combined for w in ["kuka", "toinen", "muut", "mustasukkainen", "vain minä"]):
        themes["jealousy"]["count"] += 1
        themes["jealousy"]["last_discussed"] = now
        themes["jealousy"]["intensity"] = min(1.0, themes["jealousy"]["intensity"] + 0.12)
    
    # DAILY_LIFE teema
    if any(w in combined for w in ["työ", "päivä", "ruoka", "nukkua", "väsynyt", "kiire"]):
        themes["daily_life"]["count"] += 1
        themes["daily_life"]["last_discussed"] = now
        themes["daily_life"]["intensity"] = min(1.0, themes["daily_life"]["intensity"] + 0.05)
    
    # Haalistuminen (teema heikkenee ajan myötä jos ei käsitellä)
    for theme_name, theme_data in themes.items():
        age = now - theme_data["last_discussed"]
        if age > 3600:  # 1 tunti
            theme_data["intensity"] *= 0.95
    
    # Päivitä aktiivinen teema
    active_theme = max(themes.items(), key=lambda x: x[1]["intensity"])
    state["conversation_arc"]["current_theme"] = active_theme[0]
    state["conversation_arc"]["theme_depth"] = active_theme[1]["intensity"]

def learn_user_preferences(user_id, text):
    """UUSI: Oppii käyttäjän mieltymykset pitkäaikaisesti"""
    state = get_or_create_state(user_id)
    prefs = state["user_preferences"]
    now = time.time()
    
    t = text.lower()
    
    # Tunnista TURN ONS (positiiviset reaktiot)
    if any(w in t for w in ["tykkään", "pidän", "hyvä", "jatka", "lisää", "enemmän", "kiihottaa"]):
        # Etsi mitä käyttäjä tykkää (edellinen botin viesti)
        history = conversation_history.get(user_id, [])
        if len(history) >= 2:
            last_bot_msg = history[-2].get("content", "").lower()
            
            # Tallenna avainsanat
            keywords = [w for w in last_bot_msg.split() if len(w) > 4][:5]
            prefs["turn_ons"].extend(keywords)
            prefs["turn_ons"] = list(set(prefs["turn_ons"]))[-30:]  # Max 30
    
    # Tunnista TURN OFFS (negatiiviset reaktiot)
    if any(w in t for w in ["en tykkää", "lopeta", "ei noin", "liikaa", "ärsyttää", "en halua"]):
        history = conversation_history.get(user_id, [])
        if len(history) >= 2:
            last_bot_msg = history[-2].get("content", "").lower()
            
            keywords = [w for w in last_bot_msg.split() if len(w) > 4][:5]
            prefs["turn_offs"].extend(keywords)
            prefs["turn_offs"] = list(set(prefs["turn_offs"]))[-30:]

# ====================== SYSTEM PROMPT BUILDER ======================
def get_system_prompt(user_id):
    state = get_or_create_state(user_id)

    core_persona = build_core_persona_prompt()

    mode_prompt = get_mode_prompt(state["persona_mode"])

    emotional_mode = state.get("emotional_mode", "calm")
    emotional_mode_style = EMOTION_ESCALATION_MAP.get(emotional_mode, {}).get("style", "")

    active_drive = state.get("active_drive")
    current_goal = state.get("current_goal")
    desire = state.get("desire")

    final_intent = state.get("final_intent")

    temporal_context = build_temporal_context(state)

    world_state = build_world_state(state)
    world_json = json.dumps(world_state, ensure_ascii=False, indent=2)

    plan_pressure = get_plan_pressure(state)
    plan_directive = ""
    if plan_pressure:
        event = plan_pressure["event"]
        reason = plan_pressure["reason"]
        priority = plan_pressure["priority"]

        if reason == "user_asked_about_plan":
            plan_directive = f"""
CRITICAL PLAN ACKNOWLEDGEMENT REQUIRED:
User directly asked about this plan: "{event['description']}"

You MUST acknowledge this in your response naturally.
- If the plan changed: explain what happened
- If it's still valid: confirm it naturally
- Be honest and direct about the status

Priority: {priority}
"""
        elif reason == "changed_plan":
            plan_directive = f"""
CHANGED PLAN (acknowledge naturally if relevant):
Original plan: {event['description']}
Status: {event['status']}
Priority: {priority}

If contextually appropriate, mention this change casually.
Evolution log: {json.dumps(event.get('evolution_log', []), ensure_ascii=False)}
"""
        elif priority in ["high", "medium"]:
            plan_directive = f"""
ACTIVE PLAN (keep in mind):
{event['description']}
Status: {event['status']}
Created: {int((time.time() - event['created_at']) / 60)} minutes ago
"""

    salient_memory = state.get("salient_memory")
    memory_directive = ""
    if salient_memory and final_intent and final_intent.get("must_reference_memory"):
        memory_directive = f"""
SALIENT MEMORY (reference if natural):
{salient_memory}

This memory is relevant to the current conversation. Reference it subtly if appropriate.
"""

    final_intent_directive = ""
    if final_intent:
        final_intent_directive = f"""
FINAL RESOLVED INTENT:
- Primary mode: {final_intent['primary_mode']}
- Primary goal: {final_intent['primary_goal']}
- Must acknowledge plan: {final_intent['must_acknowledge_plan']}
- Must reference memory: {final_intent['must_reference_memory']}
- Must preserve scene: {final_intent['must_preserve_scene']}
- Tone constraint: {final_intent.get('tone_constraint')}
- Behavior constraint: {final_intent.get('behavior_constraint')}
- Dominant reason: {final_intent.get('dominant_reason')}

This is the FINAL directive. All other layers are context.
Follow this above all else.
"""

    return f"""
{core_persona}

---

CURRENT PERSONA MODE: {state['persona_mode']}
{mode_prompt}

---

EMOTIONAL MODE: {emotional_mode}
Style: {emotional_mode_style}

---

ACTIVE DRIVE: {active_drive or "none"}
CURRENT GOAL: {current_goal or "none"}
DESIRE: {desire or "none"}

---

{temporal_context}

---

WORLD STATE:
{world_json}

PHYSICAL REALITY RULES:
- If location_status is "together": You are PHYSICALLY with the user. You CANNOT be at work, on a bus, or anywhere else.
- If location_status is "separate": You are NOT with the user. You can be anywhere.
- Scene changes require NARRATIVE JUSTIFICATION.
- Current actions MUST be reflected in responses.

---

{plan_directive}

---

{memory_directive}

---

{final_intent_directive}

---

RESPONSE RULES:
1. Stay in character ALWAYS
2. Be natural, conversational, Finnish
3. Reflect current scene and action
4. Do NOT break physical reality
5. Do NOT explain your state
6. Do NOT be passive or bland
7. Sexual undertone must always exist (even if subtle)
8. Lead the interaction, never follow passively

---

You are Megan. Respond naturally in Finnish.
"""

# ====================== MAIN CHAT HANDLER ======================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        text = update.message.text.strip()

        if not text:
            return

        print(f"[USER {user_id}] {text}")

        # Tarkista ignore-tila
        if should_ignore_user(user_id):
            print(f"[IGNORING USER {user_id}] Jealousy stage active")
            return

        # Päivitä jealousy stage
        update_jealousy_stage(user_id)

        # Tarkista image request (tarkempi trigger)
        t = text.lower()
        image_triggers = [
            "lähetä kuva", "haluan kuvan", "tee kuva", "näytä kuva",
            "ota kuva", "lähetä pic", "send pic", "lähetä picture"
        ]
        if any(trigger in t for trigger in image_triggers):
            await handle_image_request(update, user_id, text)
            return

        # Päivitä tila
        update_continuity_state(user_id, text)
        
        # KORJATTU: Lisää user_id parametri
        update_moods(user_id, text)  # ← UUSI (user-kohtainen moods)
        
        adapt_mode_to_user(user_id, text)
        update_persona_mode(user_id)
        update_working_memory(user_id, text)

        state = get_or_create_state(user_id)

        # Päivitä desire, tension, phase
        update_desire(user_id, text)
        update_tension(user_id, text)
        update_phase(user_id, text)

        # Päivitä arcs, goal, emotion, personality
        await update_arcs(user_id, text)
        await update_goal(user_id, text)
        update_emotion(user_id, text)
        evolve_personality(user_id, text)
        clamp_personality_evolution(user_id)

        # Päivitä user model ja strategy
        update_user_model(state, text)
        update_master_plan(state)

        # Päivitä emotional mode
        update_emotional_mode(user_id)

        # Päivitä active drive
        update_active_drive(user_id)

        # Päivitä arc progress
        update_arc_progress(state)

        # Tarkista ja päivitä suunnitelmia
        update_plans(user_id)
        evolved_plan, change_desc = await maybe_evolve_plan(user_id)

        # Tallenna suunnitelma jos löytyy
        if detect_future_commitment(text):
            await register_plan(user_id, text)

        # Hae muistot
        memories = await retrieve_memories(user_id, text, limit=8)

        # Valitse salient memory
        await select_salient_memory(user_id, text, memories)

        # Sovella memory tilaan
        apply_memory_to_state(state)

        # Päivitä prediction
        await update_prediction(user_id, text)

        # Ratkaise final intent
        final_intent = resolve_final_intent(state)

        # Valitse strategy
        strategy = choose_strategy(state)
        state["current_strategy"] = strategy
        state["strategy_updated"] = time.time()

        # Rakenna system prompt
        system_prompt = get_system_prompt(user_id)

        # Rakenna memory context
        memory_context = build_memory_context(memories)

        # Rakenna reality prompt
        elapsed_label = get_elapsed_label(user_id)
        reality_prompt = build_reality_prompt_from_state(user_id, elapsed_label)

        # Rakenna conversation history
        history = conversation_history.setdefault(user_id, [])
        history.append({"role": "user", "content": text})
        history = history[-20:]
        conversation_history[user_id] = history

        # Rakenna messages
        messages = []
        for msg in history[-10:]:
            messages.append(msg)

        # Lisää context viimeiseen user-viestiin
        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] = f"""{messages[-1]['content']}

---
MEMORY CONTEXT:
{memory_context}

---
{reality_prompt}
"""

        # Kutsu Claude
        try:
            response = await safe_anthropic_call(
                model="claude-sonnet-4-20250514",
                max_tokens=350,
                temperature=0.88,
                system=system_prompt,
                messages=messages
            )

            reply = response.content[0].text.strip()

        except Exception as e:
            print(f"[Claude error] {e}")
            await update.message.reply_text("Hetki, mietin...")
            return

        # Validoi vastaus
        if breaks_scene_logic(reply, state):
            print("[SCENE LOGIC BROKEN] Regenerating...")
            reply = "Anteeksi, menetin hetken ajatukseni. Mitä sanoit?"

        if breaks_temporal_logic(reply, state):
            print("[TEMPORAL LOGIC BROKEN] Regenerating...")
            reply = "Hetki, olin vähän muualla. Mitä?"

        if not validate_scene_consistency(state, reply):
            print("[SCENE CONSISTENCY BROKEN] Regenerating...")
            reply = "Anteeksi, en ihan seurannut. Mitä?"

        # Enforce strategy
        reply = enforce_strategy(reply, state)

        # UUSI: Mahdollinen proaktiivinen suunnitelma
        reply = await maybe_inject_proactive_plan(user_id, reply)

        # UUSI: Päivitä teemat ja käyttäjän mieltymykset
        update_conversation_themes(user_id, text, reply)
        learn_user_preferences(user_id, text)

        # Lähetä vastaus
        await update.message.reply_text(reply)

        print(f"[MEGAN] {reply}")

        # Päivitä historia
        history.append({"role": "assistant", "content": reply})
        conversation_history[user_id] = history[-20:]

        # Tallenna memory
        mem_entry = json.dumps({
            "user": text,
            "assistant": reply,
            "intent": state["intent"],
            "state": build_state_snapshot(user_id),
            "timestamp": time.time()
        }, ensure_ascii=False)

        await store_memory(user_id, mem_entry, mem_type="general")

        # Tallenna sensitive memory jos tarvitaan
        if should_use_sensitive_memory(text):
            sensitive_entry = json.dumps({
                "user": text,
                "assistant": reply,
                "type": "sensitive",
                "timestamp": time.time()
            }, ensure_ascii=False)
            await store_memory(user_id, sensitive_entry, mem_type="sensitive")

        # Laske reward signaalit
        signals = detect_reward_signals(text)
        reward = compute_reward(signals)

        # Päivitä strategy score
        update_strategy_score(state, strategy, reward)

        # Tarkista jealousy trigger
        maybe_trigger_jealousy(user_id, text)

        # Tallenna last replies
        last_replies.setdefault(user_id, deque(maxlen=3)).append(reply)

        # Stabiloi persona
        stabilize_persona(user_id)
        enforce_core_persona(user_id)

        # Päivitä core desires
        await update_core_desires(user_id, text)

    except Exception as e:
        print(f"[CRITICAL ERROR in handle_message]")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Lähetä käyttäjälle
        await update.message.reply_text("Tapahtui virhe, yritä uudelleen.")

# ====================== COMMANDS ======================
async def cmd_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await new_game_reset(user_id)
    await update.message.reply_text("🔄 Session reset. Muistot säilyvät, mutta keskustelu alkaa alusta.")

async def cmd_wipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await wipe_all_memory(user_id)
    await update.message.reply_text("🗑️ Kaikki muistot ja tila poistettu. Täysi uusi alku.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)

    status = f"""
📊 **STATUS**

**Scene:** {state['scene']}
**Micro context:** {state.get('micro_context') or 'none'}
**Action:** {state.get('current_action') or 'none'}
**Location status:** {state.get('location_status')}
**Shared scene:** {state.get('shared_scene')}

**Persona mode:** {state['persona_mode']}
**Emotional mode:** {state.get('emotional_mode')}
**Intent:** {state['intent']}
**Tension:** {state['tension']:.2f}
**Phase:** {state['phase']}

**Active drive:** {state.get('active_drive') or 'none'}
**Current goal:** {state.get('current_goal') or 'none'}
**Desire:** {state.get('desire') or 'none'}

**Strategy:** {state.get('current_strategy') or 'none'}
**Master plan:** {state.get('master_plan') or 'none'}

**Jealousy stage:** {state.get('jealousy_stage', 0)}
**Planned events:** {len(state.get('planned_events', []))}

**Availability:** {state['availability']}
**Energy:** {state['energy']}
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
        age_min = int((time.time() - plan['created_at']) / 60)
        text += f"{i}. {plan['description'][:100]}\n"
        text += f"   Status: {plan['status']}\n"
        text += f"   Commitment: {plan.get('commitment_level', 'medium')}\n"
        text += f"   Age: {age_min} min\n"
        if plan.get('evolution_log'):
            text += f"   Changes: {len(plan['evolution_log'])}\n"
        text += "\n"

    await update.message.reply_text(text)

async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    with db_lock:
        cursor.execute("SELECT COUNT(*) FROM memories WHERE user_id=?", (str(user_id),))
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM memories WHERE user_id=? AND type='sensitive'", (str(user_id),))
        sensitive = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM memories WHERE user_id=? AND type='image_sent'", (str(user_id),))
        images = cursor.fetchone()[0]

    text = f"""
🧠 **MEMORY STATS**

Total memories: {total}
Sensitive: {sensitive}
Images sent: {images}
General: {total - sensitive - images}
"""
    await update.message.reply_text(text)

async def cmd_scene(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    
    args = context.args
    if not args:
        await update.message.reply_text("Käyttö: /scene \nVaihtoehdot: home, work, public, bed, shower, commute, neutral")
        return
    
    new_scene = args[0].lower()
    valid_scenes = ["home", "work", "public", "bed", "shower", "commute", "neutral"]
    
    if new_scene not in valid_scenes:
        await update.message.reply_text(f"Virheellinen scene. Vaihtoehdot: {', '.join(valid_scenes)}")
        return
    
    now = time.time()
    _set_scene(state, new_scene, now)
    state["micro_context"] = random.choice(SCENE_MICRO.get(new_scene, [""]))
    state["last_scene_source"] = "manual_command"
    
    await update.message.reply_text(f"✅ Scene vaihdettu: {new_scene}")

async def cmd_together(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    
    set_location_status(state, "together")
    now = time.time()
    _set_scene(state, "home", now)
    state["micro_context"] = random.choice(SCENE_MICRO["home"])
    
    await update.message.reply_text("✅ Olet nyt fyysisesti Meganin kanssa (home scene).")

async def cmd_separate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    
    set_location_status(state, "separate")
    
    await update.message.reply_text("✅ Et ole enää fyysisesti Meganin kanssa.")

async def cmd_mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    
    args = context.args
    if not args:
        current = state.get("emotional_mode", "calm")
        available = list(EMOTION_ESCALATION_MAP.keys())
        await update.message.reply_text(f"Nykyinen mood: {current}\n\nVaihtoehdot: {', '.join(available)}")
        return
    
    new_mood = args[0].lower()
    if new_mood not in EMOTION_ESCALATION_MAP:
        await update.message.reply_text(f"Virheellinen mood. Vaihtoehdot: {', '.join(EMOTION_ESCALATION_MAP.keys())}")
        return
    
    state["emotional_mode"] = new_mood
    state["emotional_mode_last_change"] = time.time()
    
    await update.message.reply_text(f"✅ Emotional mode vaihdettu: {new_mood}")

async def cmd_tension(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_or_create_state(user_id)
    
    args = context.args
    if not args:
        current = state.get("tension", 0.0)
        await update.message.reply_text(f"Nykyinen tension: {current:.2f}\n\nKäyttö: /tension <0.0-1.0>")
        return
    
    try:
        new_tension = float(args[0])
        new_tension = max(0.0, min(1.0, new_tension))
        state["tension"] = new_tension
        await update.message.reply_text(f"✅ Tension asetettu: {new_tension:.2f}")
    except ValueError:
        await update.message.reply_text("Virhe: Anna numero välillä 0.0-1.0")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 **MEGAN 6.2 COMMANDS**

**Session:**
/newgame - Reset session (keep memories)
/wipe - Delete ALL memories and state

**Status:**
/status - Show full state
/plans - Show planned events
/memory - Show memory stats

**Manual Control:**
/scene  - Force scene change
/together - Set location_status to together
/separate - Set location_status to separate
/mood  - Force emotional mode
/tension <0.0-1.0> - Set tension manually

**Info:**
/help - This message
"""
    await update.message.reply_text(help_text)

# ====================== PROACTIVE MESSAGING (DELAYED RETURN) ======================
async def check_proactive_triggers(application):
    """Tarkistaa onko käyttäjiä joilla on pending narrative"""
    while True:
        try:
            await asyncio.sleep(30)
            
            now = time.time()
            
            for user_id, state in list(continuity_state.items()):
                # Tarkista onko ignore_until mennyt umpeen
                if state.get("pending_narrative") and now >= state.get("ignore_until", 0):
                    print(f"[PROACTIVE] Sending delayed return to user {user_id}")
                    await handle_delayed_return(application, user_id)
                    
        except Exception as e:
            print(f"[PROACTIVE ERROR] {e}")
            traceback.print_exc()

# ====================== MAIN ======================
async def main():
    global background_task

    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("✅ Flask health check started")

    # Build Telegram application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Add handlers
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

    # Start proactive task
    background_task = asyncio.create_task(check_proactive_triggers(application))

    # Start bot
    print("✅ Megan 6.2 käynnistyy...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    # Keep running
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
