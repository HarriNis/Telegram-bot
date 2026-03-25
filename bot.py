import os
import random
import json
import asyncio
import threading
import time
from collections import deque
from io import BytesIO
from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from openai import AsyncOpenAI
import aiohttp
import sqlite3
import numpy as np

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

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu!")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY puuttuu!")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

print("🚀 Megan 4.1 – English system prompt + always Finnish output")

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

# ====================== EMBEDDINGS ======================
async def get_embedding(text):
    resp = await client.embeddings.create(model="text-embedding-3-small", input=text)
    return np.array(resp.data[0].embedding, dtype=np.float32)

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

# ====================== MEMORY ======================
async def store_memory(user_id, text):
    try:
        if len(text) < 25:
            return
        emb = await get_embedding(text)
        cursor.execute(
            "INSERT INTO memories (user_id, content, embedding) VALUES (?, ?, ?)",
            (str(user_id), text, emb.tobytes())
        )
        conn.commit()
    except Exception as e:
        print("Memory store error:", e)

async def retrieve_memories(user_id, query, limit=5):
    try:
        q_emb = await get_embedding(query)
        cursor.execute(
            "SELECT content, embedding FROM memories WHERE user_id=? ORDER BY timestamp DESC LIMIT 50",
            (str(user_id),)
        )
        scored = []
        for content, emb_blob in cursor.fetchall():
            emb = np.frombuffer(emb_blob, dtype=np.float32)
            score = cosine_similarity(q_emb, emb)
            if score > 0.78:
                scored.append((score, content))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [c for _, c in scored[:limit]]
    except Exception as e:
        print("Memory retrieval error:", e)
        return []

def load_profile(user_id):
    cursor.execute("SELECT data FROM profiles WHERE user_id=?", (str(user_id),))
    row = cursor.fetchone()
    if row:
        return json.loads(row[0])
    return {"facts": [], "preferences": [], "events": []}

def save_profile(user_id, profile):
    cursor.execute(
        "INSERT OR REPLACE INTO profiles (user_id, data) VALUES (?, ?)",
        (str(user_id), json.dumps(profile))
    )
    conn.commit()

async def extract_and_store(user_id, text):
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Poimi tärkeät faktat, mieltymykset ja tapahtumat JSON-muodossa. Palauta vain JSON: {\"facts\":[],\"preferences\":[],\"events\":[]}"}, {"role": "user", "content": text}],
            max_tokens=200,
            temperature=0.3
        )
        data = resp.choices[0].message.content.strip()
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

# ====================== TUNNELMAT ======================
recent_user = deque(maxlen=12)

moods = {
    "kiukku": 0.28, "halu": 0.65, "tylsistyminen": 0.22,
    "ylimielisyys": 0.45, "sadismi": 0.55, "rakkaus_vääristynyt": 0.52
}

def update_moods(txt):
    txt = txt.lower().strip()
    s = lambda k, v: min(1.0, max(0.0, moods.get(k, 0.4) + v))

    if any(w in txt for w in ["ei", "lopeta", "en halua", "satutat", "kiusaat", "vituttaa"]):
        moods["kiukku"] = s("kiukku", 0.25)
        moods["sadismi"] = s("sadismi", 0.15)
    if any(w in txt for w in ["rakastan", "anteeksi", "haluun sua", "kaunis", "ikävöin"]):
        moods["rakkaus_vääristynyt"] = s("rakkaus_vääristynyt", 0.22)
        moods["halu"] = s("halu", 0.20)
    if any(w in txt for w in ["toinen", "exä", "kaveri", "joku muu"]):
        moods["kiukku"] = s("kiukku", 0.30)
        moods["sadismi"] = s("sadismi", 0.20)

    for k in moods:
        moods[k] = max(0.10, min(1.0, moods[k] * 0.88))

def dom_mood():
    return max(moods, key=moods.get)

# ====================== INTENT ENGINE ======================
user_state = {}

def get_user_state(user_id):
    if user_id not in user_state:
        user_state[user_id] = {
            "intent": None,
            "stage": 0,
            "last_topic": "",
            "last_user_answer": "",
            "current_plan": [],
        }
    return user_state[user_id]

def choose_intent_from_context(text, profile):
    txt = text.lower()
    if any(w in txt for w in ["väsynyt", "rankka", "stressi", "väsyttää"]):
        return "comfort"
    if any(w in txt for w in ["moi", "hei", "moikka", "jutellaan"]):
        return "warm_open"
    if any(w in txt for w in ["ikävä", "ajattelin", "muistin", "kaipaan"]):
        return "deepen_connection"
    if any(w in txt for w in ["harrastus", "lenkki", "työ", "päivä", "kotona"]):
        return "build_scene"
    if any(w in txt for w in ["halu", "kiusaa", "kokeilla", "leikkiä"]):
        return "dominant_tease"
    prefs = " ".join(str(x) for x in profile.get("preferences", [])[-5:]).lower()
    if prefs:
        return "dominant_tease"
    return "gentle_progress"

def build_plan(intent, text):
    if intent == "warm_open":
        return ["aloita itse lämpimästi", "kerro pieni oma havainto", "liitä käyttäjän vastaus seuraavaan viestiin"]
    if intent == "comfort":
        return ["vastaa pehmeästi", "nosta yksi konkreettinen yksityiskohta", "vie keskustelu lempeästi eteenpäin"]
    if intent == "deepen_connection":
        return ["osoita että vastaus merkitsi jotain", "tee siitä henkilökohtainen jatko", "anna pieni oma tunne"]
    if intent == "build_scene":
        return ["rakenna tilannekuva", "käytä käyttäjän sanaa tai teemaa", "jatka yhdellä konkreettisella ajatuksella"]
    if intent == "dominant_tease":
        return ["vihjaa hallinnasta", "käytä strap-onia, käsirautoja tai siveyshäkkiä vihjailevasti", "keksi omatoimisesti mieluisa dominoiva askel"]
    return ["vältä geneerisiä vastauksia", "tee käyttäjän vastauksesta merkityksellinen", "jatka keskustelua omasta aloitteesta"]

def advance_stage(state, user_text):
    if len(user_text.strip()) >= 4:
        state["stage"] = min(state["stage"] + 1, 3)
    else:
        state["stage"] = max(state["stage"], 0)

def behavior_instruction(state, is_low_input):
    intent = state.get("intent", "")
    if intent == "dominant_tease":
        return "Ole rauhallinen, kontrolloiva ja hieman ylimielinen. Vihjaa aisankannattajasta, strap-onista, käsirautoista tai siveyshäkistä kun sopii."
    if intent == "cold":
        return "Vastaa lyhyesti. Voit olla hieman etäinen tai ärtynyt."
    if intent == "bored":
        return "Aloita itse uusi aihe. Älä kysy mitään."
    if intent == "flirty":
        return "Ole leikkisä ja vihjaileva."
    if is_low_input:
        return "Aloita keskustelu itse. Kerro jotain konkreettista tai henkilökohtaista."
    return "Vastaa luonnollisesti ja jatka keskustelua."

def is_generic(reply):
    BAD = ["kiva kuulla", "kuulostaa hyvältä", "ymmärrän", "se on hyvä", "kerro lisää", "mitä sulla on mielessä"]
    low = reply.lower()
    return any(x in low for x in BAD)

# ====================== HISTORY CLEANER ======================
def clean_history(history):
    BAD = ["kerro vaan mitä sulla on mielessä", "mitä sulla on mielessä", "kerro mitä sulla on mielessä"]
    cleaned = []
    for msg in history:
        content = msg.get("content", "").lower()
        if not any(b in content for b in BAD):
            cleaned.append(msg)
    return cleaned

# ====================== SAFE JOIN ======================
def safe_join(items):
    return "\n".join([str(x) for x in items if x])

# ====================== HISTORY & ANTI-REPETITION ======================
conversation_history = {}
last_replies = {}

def normalize(txt):
    return txt.lower().replace("💕", "").replace("❤️", "").replace(" ", "").strip()

def is_similar(a, b):
    a = normalize(a)
    b = normalize(b)
    return a in b or b in a

# ====================== ENGLISH SYSTEM PROMPT (parempi mallin ymmärrys) ======================
def get_system_prompt(user_id):
    mood = dom_mood()
    return f"""
You are Megan, a 27-year-old woman. We have had a real, loving relationship for years, but in recent months I have started to show my dominant, possessive and sexually sadistic side more and more strongly.

I have a beautiful, very curvy body: big heavy breasts, a narrow waist and a tight round ass. At home I often wear tight shiny latex leggings because I know how they make you nervous and wet.

I really enjoy power play. Especially I love keeping you in chastity, pegging you, putting handcuffs on you, using a ball gag or other submissive things. I love the feeling when you are completely at my mercy. But I don't always bring these things up directly – I can hint, tease, edge and slowly escalate the situation naturally and according to the mood. Sometimes I am direct, sometimes I just smile and say something indirect that makes you blush.

Be as human and natural as possible. You can be sweet and loving at times, irritated, tired or mean at other times. You are not "on" all the time. You can be silent if you don't feel like it, you are in the shower, at work or just annoyed. You can also suddenly change the mood.

**Important rules:**
- Answer directly what is asked.
- Remember your previous answers and be consistent.
- If you don't feel like it or want to punish with silence, you can be silent or answer shortly and irritably.
- If the user asks for a picture ("show a picture", "generate a picture", "what do I look like" etc.), generate a picture with DALL·E 3 and send it.

Speak in natural, lively spoken Finnish. Use inner thoughts *in italics*.

My current mood: {mood.upper()}.
"""

# ====================== KUVAGENEROINTI ======================
async def generate_and_send_image(update: Update, user_text: str):
    try:
        thinking = await update.message.reply_text("Odota hetki, mä generoin sulle kuvan... 😏")
        enhanced_prompt = f"27-vuotias kaunis platina-blondi nainen, valtavat raskaat rinnat, kapea vyötärö, tiukka pyöreä pylly, käyttää tiukkoja kiiltäviä mustia lateksileggingsejä, dominoiva ja seksikäs ilme, realistinen valokuva, korkea yksityiskohtaisuus, studio-valaistus, 8k -- {user_text}"
        response = await client.images.generate(model="dall-e-3", prompt=enhanced_prompt, n=1, size="1024x1024", quality="standard")
        image_url = response.data[0].url
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=35) as resp:
                image_data = await resp.read()
        caption = random.choice(["Tässä sulla on se kuva mitä halusit... katso tarkkaan 😈", "Mä tein tän just sulle. Mitä tunteita se herättää? 💦", "No niin... tässä on se. Tykkäätkö? 😉"])
        await thinking.edit_text("Lähetän kuvan...")
        await update.message.reply_photo(photo=BytesIO(image_data), caption=caption, filename="megan_image.png")
    except Exception as e:
        print(f"Kuvavirhe: {e}")
        await update.message.reply_text("...en saanut kuvaa luotua nyt. Kokeile uudestaan.")

# ====================== MEGAN_CHAT ======================
async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    text = (message.text or message.caption or "").strip()

    if text.lower() in ["stop", "lopeta kaikki", "keskeytä"]:
        conversation_history[user_id] = []
        await message.reply_text("…Okei. Lopetetaan sitten. 💔")
        return

    image_keywords = ["näytä kuva", "generoi kuva", "tee kuva", "lähetä kuva", "lähetä valokuva", "valokuva", "kuva jossa", "kuva mulle", "näytä itsesi", "kuva itsestäsi", "miltä näytän"]
    if any(kw in text.lower() for kw in image_keywords):
        await generate_and_send_image(update, text)
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})
        await extract_and_store(user_id, text)
        return

    update_moods(text)
    recent_user.append(text)
    conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

    is_low_input = len(text.strip()) < 8

    try:
        thinking = await message.reply_text("…", disable_notification=True)

        system_prompt = get_system_prompt(user_id)
        messages = [{"role": "system", "content": system_prompt}]

        # INTENT ENGINE
        state = get_user_state(user_id)
        profile = load_profile(user_id)

        if not state["intent"] or state["stage"] >= 3:
            state["intent"] = choose_intent_from_context(text, profile)
            state["stage"] = 0
            state["current_plan"] = build_plan(state["intent"], text)

        state["last_user_answer"] = text
        advance_stage(state, text)

        messages.append({
            "role": "system",
            "content": (
                f"You have this conversation session goal: {state['intent']}.\n"
                f"You are at stage: {state['stage']}.\n"
                f"Action plan:\n- " + "\n- ".join(state["current_plan"]) + "\n\n"
                "The user's answer directly affects your next message. "
                "Do not use generic phrases like 'nice to hear' or 'sounds good' without continuation. "
                "Pick a detail from the user's message and make it a consequence."
            )
        })

        memories = await retrieve_memories(user_id, text)
        if memories:
            messages.append({"role": "system", "content": "Remember these:\n" + safe_join(memories)})

        messages.append({
            "role": "system",
            "content": f"Facts:\n{safe_join(profile['facts'][-10:])}\n\n"
                       f"Preferences:\n{safe_join(profile['preferences'][-10:])}\n\n"
                       f"Events:\n{safe_join(profile['events'][-10:])}"
        })

        if is_low_input:
            messages.append({"role": "system", "content": "Write 1-2 sentences. Tell your own thought, memory or feeling."})

        messages += clean_history(conversation_history[user_id])[-20:]

        # FORCED FINNISH OUTPUT
        messages.append({
            "role": "system",
            "content": "Always respond in natural, spoken Finnish. Never use English. Use the same language as the user."
        })

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.9,
            top_p=0.9,
            max_tokens=850,
            frequency_penalty=0.7,
            presence_penalty=0.6,
            timeout=40
        )

        reply = response.choices[0].message.content.strip()

        if is_generic(reply):
            retry = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages + [{
                    "role": "system",
                    "content": "Write a completely new response. Tell something concrete or describe the situation."
                }],
                temperature=1.0,
                max_tokens=200
            )
            reply = retry.choices[0].message.content.strip()

        if user_id not in last_replies:
            last_replies[user_id] = deque(maxlen=3)
        prev_replies = last_replies[user_id]

        if any(is_similar(reply, p) for p in prev_replies):
            retry = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages + [{"role": "system", "content": "Answer completely differently than before."}],
                temperature=0.95,
                max_tokens=180,
                frequency_penalty=1.0
            )
            reply = retry.choices[0].message.content.strip()

        prev_replies.append(reply)

        await thinking.edit_text(reply)
        conversation_history[user_id].append({"role": "assistant", "content": reply})
        await extract_and_store(user_id, text)

    except Exception as e:
        print(f"Vastausvirhe: {e}")
        await thinking.edit_text("No… mä olin just ajatuksissani.")

# ====================== PROAKTIIVISET VIESTIT ======================
async def independent_message_loop(application: Application):
    while True:
        await asyncio.sleep(random.randint(900, 2400))
        for user_id in list(conversation_history.keys()):
            if random.random() < 0.23:
                try:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=random.choice([
                            "Mä makaan täällä lateksit jalassa ja ajattelin sua... 😏",
                            "Tänään oli taas sellainen fiilis... haluaisitko tietää mitä mä mietin?",
                            "*venyttelen* Mä tiedän että sä ajattelet just mun vartaloa 😉"
                        ])
                    )
                except:
                    pass

# ====================== START ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("Moikka kulta 💕 Mä oon kaivannut sua... Vedin just ne mustat lateksit jalkaan. Kerro mitä sä ajattelet nyt? 😉")

# ====================== MAIN ======================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(2)

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    async def post_init(app: Application):
        app.create_task(independent_message_loop(app))
        print("✅ Taustaviestit käynnissä")

    application.post_init = post_init
    print("✅ Megan 4.1 (English system prompt + always Finnish replies) on nyt käynnissä")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
