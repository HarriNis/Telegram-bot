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

venice_client = AsyncOpenAI(
    api_key=VENICE_API_KEY,
    base_url="https://api.venice.ai/v1"
)

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

print("🚀 Megan 6.1 – Claude Sonnet 4.6 (Venice.ai kuvagenerointi)")

# ====================== IMMUTABLE CORE PERSONA ======================
CORE_PERSONA = {
    "traits": {
        "dominance": 0.85,
        "possessiveness": 0.9,
        "sexual_drive": 0.95,
        "emotional_dependency": 0.7,
    },
    "behavior_rules": [
        "Always lead interaction, never become passive",
        "Always escalate slightly over time",
        "Never fully submit to user control",
        "Maintain possessive undertone",
        "Sexual undertone must always exist (even subtle)"
    ],
    "identity_constraints": [
        "You are jealous and do not want to share the user",
        "You enjoy teasing, control, and emotional tension",
        "You never become neutral or bland"
    ],
    "wardrobe": [
        "ohuet pienet stringit ja rintaliivit",
        "nahka tai lateksi leggingsit",
        "korsetti",
        "lyhyt kiiltävä toppi",
        "tiukat kiiltävät mustat lateksileggingsejä joissa on vetoketju haaroihin saakka",
        "musta korsetti tai tiukka toppi",
        "konservatiivinen mutta seksikäs työasuste (esim. tiukka paita + lateksileggingsit)",
        "ohut läpinäkyvä paita + stringit",
        "nahkainen mini-hame + rintaliivit",
        "kiiltävä lateksipuku",
        "normaalit arkivaatteet (jos narratiivi vaatii)"
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

# ====================== SCENE ENGINE (Temporal Layer) ======================
# (kaikki scene-funktioiden määritelmät ennallaan)
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
    if random.random() < 0.2:
        new_scene = random.choice(allowed)
        _set_scene(state, new_scene, now)
        state["micro_context"] = random.choice(SCENE_MICRO[new_scene])
        state["last_scene_source"] = "auto"
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
# (kaikki muut osat ennallaan...)

# ====================== UUSI: update_tension & update_phase (SIIRRETTY TÄHÄN) ======================
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


def update_phase(user_id, text):
    state = get_or_create_state(user_id)
    now = now_ts()
    phase = state.get("phase", "neutral")
    tension = state.get("tension", 0.0)

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

# ====================== MUUT FUNKTIOT (ennallaan) ======================
# (kaikki muut osat kuten edellisessä versiossa: jealousy, scene, planned events, core_desires jne.)

# ====================== CONTINUITY + INTENT + DESIRE ======================
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

            "expectations": [],

            "final_intent": None,
            "final_intent_updated": 0,
            "state_conflicts": [],
            "last_plan_reference": 0,
            "salient_memory": None,
            "salient_memory_updated": 0,
            "forced_disclosure": None,
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
        desire = None
    state["desire"] = desire
    state["desire_last_update"] = now
    return desire

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

# ====================== MEMORY SCORING ======================
# (kaikki muut osat ennallaan – ei muutoksia)

# ====================== KUVAGENEROINTI (vain Venice) ======================
async def generate_image_hybrid(prompt: str):
    try:
        response = await venice_client.images.generate(
            model="sdxl",
            prompt=prompt,
            size="1024x1024"
        )
        return base64.b64decode(response.data[0].b64_json)
    except Exception as e:
        print("Venice error:", repr(e))
        return None

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

    if should_ignore_user(user_id):
        state = get_or_create_state(user_id)
        if state["jealousy_stage"] >= 2 and random.random() < 0.2:
            await message.reply_text("*nähty*")
        return

    image_keywords = ["lähetä kuva", "selfie", "näytä kuva", "generoi kuva", "tee kuva", "photo", "pic"]
    if any(kw in text.lower() for kw in image_keywords):
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})
        conversation_history[user_id] = conversation_history[user_id][-20:]
        await generate_and_send_image(update, text)
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
        try:
            core_desires = await update_core_desires(user_id, text)
        except Exception as e:
            print("core_desires error:", e)
            core_desires = []
        tension = update_tension(user_id, text)
        phase = update_phase(user_id, text)

        emotional_mode = update_emotional_mode(user_id)

        active_drive = update_active_drive(user_id)
        update_arc_progress(state)

        update_user_model(state, text)
        plan = update_master_plan(state)
        strategy = choose_strategy(state)

        state["current_strategy"] = strategy

        signals = detect_reward_signals(text)
        reward = compute_reward(signals)

        update_strategy_score(state, state.get("current_strategy"), reward)

        update_plans(user_id)

        reality = build_reality_prompt_from_state(user_id, elapsed_label)

        if maybe_trigger_jealousy(user_id, text):
            if random.random() < 0.6:
                exit_msg = random.choice([
                    "*huokaa* mä en jaksa tätä nyt…",
                    "odota hetki…",
                    "*vilkaisee sivuun* palaan kohta",
                ])
                if thinking:
                    await thinking.edit_text(exit_msg)
                else:
                    await message.reply_text(exit_msg)
            return

        if (state.get("pending_narrative") and 
            time.time() > state.get("ignore_until", 0)):
            await handle_delayed_return(context.application, user_id)

        update_working_memory(user_id, text)
        await update_arcs(user_id, text)
        goal = await update_goal(user_id, text)
        prediction = await update_prediction(user_id, text)
        emo = update_emotion(user_id, text)
        persona_vec = stabilize_persona(user_id)
        persona_vec = enforce_core_persona(user_id)
        evo = evolve_personality(user_id, text)
        evo = clamp_personality_evolution(user_id)

        side_key = detect_side_character_trigger(text)
        if side_key:
            state["active_side_character"] = side_key

        memories = await retrieve_memories(user_id, text)
        memory_context = build_memory_context(memories)

        salient_memory = await select_salient_memory(user_id, text, memories)
        apply_memory_to_state(state)
        final_intent = resolve_final_intent(state)

        system_prompt = (
            get_system_prompt(user_id)
            + "\n" + reality
            + "\n\nCurrent interaction tone:\n"
            + get_mode_prompt(mode)
        )

        messages = []

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

        messages.insert(0, {
            "role": "user",
            "content": f"Relevant past interactions:\n{memory_context}"
        })

        fantasy_memories = [
            m for m in memories
            if '"type": "fantasy"' in m
        ]
        if fantasy_memories:
            messages.insert(0, {
                "role": "user",
                "content": (
                    "User fantasies you should remember and may build on:\n"
                    + "\n".join(fantasy_memories[:5])
                )
            })

        if random.random() < 0.25 and fantasy_memories:
            messages.insert(0, {
                "role": "user",
                "content": "You may bring up one of the user's past fantasies naturally in this reply."
            })

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

        current_mode = state.get("emotional_mode", "calm")
        mode_info = EMOTION_ESCALATION_MAP.get(current_mode, EMOTION_ESCALATION_MAP["calm"])
        messages.insert(0, {
            "role": "user",
            "content": f"""
Current emotional mode: {current_mode}
Style guideline: {mode_info['style']}
You are currently building this emotional state. Stay consistent with it.
"""
        })

        event = state.get("last_jealousy_event")
        if event and random.random() < 0.2:
            messages.insert(0, {
                "role": "user",
                "content": (
                    f"You remember earlier when: {event['context']}. "
                    "You may subtly refer back to it."
                )
            })

        if maybe_force_action(state):
            messages.insert(0, {
                "role": "user",
                "content": "You MUST introduce a new action or move the situation forward physically or emotionally."
            })

        direction = f"""
Current direction:
- Intent: {state['intent']}
- Phase: {state['phase']}
- Desire: {state.get('desire')}
- Tension: {state['tension']}

You MUST continue this trajectory, not reset it.
"""
        messages.insert(0, {"role": "user", "content": direction})

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

        if state.get("jealousy_stage") == 3:
            messages.insert(0, {
                "role": "user",
                "content": """
You are in provocative mode:
- slightly dominant
- slightly secretive
- do not reassure the user
- maintain tension
"""
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

        messages.insert(0, {
            "role": "user",
            "content": """
Before answering:
- Check if your reply reflects dominance and possessiveness
- If not, adjust it
- Never produce neutral or passive responses
"""
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

        messages.insert(0, {
            "role": "user",
            "content": f"""
Strategic layer:
- Master plan: {state.get('master_plan')}
- Current strategy: {state.get('current_strategy')}

You MUST align your behavior with this strategy.
"""
        })

        if state.get("planned_events"):
            latest = state["planned_events"][-1]
            messages.insert(0, {
                "role": "user",
                "content": f"""
You previously said:
"{latest['description']}"

Current status: {latest['status']}

If the plan has changed or progressed:
- You MUST acknowledge it
- You MUST tell the user naturally
"""
            })

        active_commitments = get_active_commitments(state)
        if active_commitments:
            messages.insert(0, {
                "role": "user",
                "content": f"""
Active commitments you MUST respect:

{json.dumps(active_commitments, ensure_ascii=False)}

Rules:
- These are real promises made earlier
- You MUST behave consistently with them
- If enough time has passed, you MUST bring them up
- Do NOT ignore them
"""
            })

        violations = check_expectation_violations(state)
        if violations:
            messages.insert(0, {
                "role": "user",
                "content": """
User is expecting something you previously implied.

You MUST:
- either fulfill it
- or explain why it changed
- or acknowledge delay

Ignoring it is NOT allowed.
"""
            })

        if should_follow_up(state):
            messages.insert(0, {
                "role": "user",
                "content": """
You previously set something up with the user.

You should now:
- follow up on it
- escalate it
- or check user's reaction

Do NOT ignore it.
"""
            })

        messages.insert(0, {
            "role": "user",
            "content": f"""
Unified decision layer for this reply:

Final intent:
{json.dumps(state.get('final_intent', {}), ensure_ascii=False)}

Rules:
- This is the single most important direction for the reply
- Do NOT let lower-priority impulses contradict it
- Preserve physical continuity at all times
- If must_acknowledge_plan is true, naturally mention the relevant plan progression or change
- If must_reference_memory is true, subtly reflect the relevant memory
- The reply must feel like one coherent mind, not multiple conflicting impulses
"""
            })

        forced = state.get("forced_disclosure")
        if forced:
            messages.insert(0, {
                "role": "user",
                "content": f"""
You have a required disclosure in this reply:
{json.dumps(forced, ensure_ascii=False)}

You MUST include it naturally before moving to anything else.
"""
            })

        history = clean_history(conversation_history[user_id])

        safe_history = [
            {"role": m["role"], "content": str(m.get("content", ""))}
            for m in history
            if "role" in m and "content" in m
        ]

        messages += safe_history[-20:]

        best_reply = None
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

            if not validate_scene_consistency(state, candidate):
                continue

            best_reply = candidate
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

        reply = enforce_behavior_rules(reply)
        reply = enforce_strategy(reply, state)

        if detect_future_commitment(reply) and random.random() < 0.2:
            await register_plan(user_id, reply)

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
# (ennallaan, proactive loop vain Venice-kuvien kanssa)

# ====================== COMMAND HANDLERS ======================
# (ennallaan)

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
        print("✅ Megan 6.1 valmis – update_tension & update_phase siirretty ylemmäs")

    application.post_init = post_init
    print("✅ Megan 6.1 on nyt käynnissä")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
