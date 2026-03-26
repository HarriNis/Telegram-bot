import os
import random
import json
import asyncio
import threading
import time
import re
from collections import deque
from io import BytesIO
from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from anthropic import AsyncAnthropic
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
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu!")
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY puuttuu!")

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

print("🚀 Megan 5.4 – Claude Sonnet 4.6 (Realism Engine v1)")

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

# ====================== SCENE STATE (uusi) ======================
scene_state = {}

def detect_scene(text, current_scene):
    t = text.lower()
    if any(w in t for w in ["töissä", "duunissa", "työssä", "kokouksessa", "toimistolla"]):
        return "work"
    if any(w in t for w in ["kotona", "sängyssä", "sohvalla", "kotoa", "asunnossa"]):
        return "home"
    if any(w in t for w in ["kaupassa", "ulkona", "kadulla", "julkinen", "ravintolassa"]):
        return "public"
    return current_scene or "neutral"

# ====================== EMBEDDINGS ======================
async def get_embedding(text):
    from openai import AsyncOpenAI
    openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = await openai_client.embeddings.create(model="text-embedding-3-small", input=text)
    return np.array(resp.data[0].embedding, dtype=np.float32)

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

# ====================== MEMORY ======================
async def store_memory(user_id, text):
    try:
        if len(text) < 25:
            return
        txt = text.lower()
        tag = "sensitive" if any(w in txt for w in ["pelkään", "häpeän", "nolottaa", "arka", "haluan", "fantasia", "ahdistaa", "kiusaa"]) else "general"
        emb = await get_embedding(text)
        cursor.execute(
            "INSERT INTO memories (user_id, content, embedding, type) VALUES (?, ?, ?, ?)",
            (str(user_id), text, emb.tobytes(), tag)
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

def get_sensitive_memories(user_id):
    cursor.execute(
        "SELECT content FROM memories WHERE user_id=? AND type='sensitive' ORDER BY timestamp DESC LIMIT 6",
        (str(user_id),)
    )
    return [row[0] for row in cursor.fetchall()]

def should_use_sensitive_memory(text: str) -> bool:
    t = text.lower()
    triggers = ["pelkään", "häpeän", "nolottaa", "arka", "haluan", "fantasia", "ahdistaa", "muistatko", "se juttu"]
    return any(x in t for x in triggers)

def get_random_sensitive_memory(user_id):
    cursor.execute(
        "SELECT content FROM memories WHERE user_id=? AND type='sensitive'",
        (str(user_id),)
    )
    rows = [r[0] for r in cursor.fetchall()]
    if not rows:
        return None
    return random.choice(rows)

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
        resp = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            temperature=0.3,
            messages=[{"role": "user", "content": "Poimi tärkeät faktat, mieltymykset ja tapahtumat JSON-muodossa. Palauta vain JSON: {\"facts\":[],\"preferences\":[],\"events\":[]}"}, {"role": "user", "content": text}]
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

# ====================== HISTORY CLEANER ======================
def clean_history(history):
    BAD = [
        "kerro vaan mitä sulla on mielessä",
        "mitä sulla on mielessä",
        "kerro mitä sulla on mielessä",
        "mä olin just ajatuksissani",
        "mä en jaksa nyt olla kiltti",
        "sä tiedät kyllä miksi mä oon hiljaa",
        "mä jäin hetkeksi hiljaiseksi",
        "mä mietin vielä mitä sanoisin"
    ]
    cleaned = []
    for msg in history:
        content = msg.get("content", "").lower()
        if any(b in content for b in BAD):
            continue
        cleaned.append(msg)
    return cleaned

def safe_join(items):
    return "\n".join([str(x) for x in items if x])

conversation_history = {}
last_replies = {}

def normalize(txt):
    txt = txt.lower()
    txt = re.sub(r'[^\w\s]', '', txt)
    txt = re.sub(r'\s+', ' ', txt)
    return txt.strip()

def is_similar(a, b):
    a = normalize(a)
    b = normalize(b)
    if a in b or b in a:
        return True
    a_words = set(a.split())
    b_words = set(b.split())
    overlap = len(a_words & b_words) / max(1, len(a_words))
    return overlap > 0.6

# ====================== ENGLISH SYSTEM PROMPT ======================
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
Always respond in natural spoken Finnish. Never use English.
"""

# ====================== SCENE RULES ======================
scene_rules = {
    "work": "User is at work. You are NOT physically present. No whispering, touching or physical actions. Communicate only via phone/text.",
    "home": "User is at home. You can be more intimate and close. Physical actions are possible.",
    "public": "User is in public. Keep things subtle and discreet. No explicit actions.",
    "neutral": "No specific location. Stay neutral."
}

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
    is_low_input = len(text.strip()) < 8

    # 🔥 UUSI: Scene detection + inertia
    current = scene_state.get(user_id)
    if current and random.random() < 0.8:          # inertia 80%
        scene = current
    else:
        scene = detect_scene(text, current)
    scene_state[user_id] = scene

    try:
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

        thinking = await message.reply_text("…", disable_notification=True)

        system_prompt = get_system_prompt(user_id) + "\n\n" + scene_rules.get(scene, scene_rules["neutral"])

        messages = []

        if should_use_sensitive_memory(text) and random.random() < 0.25:
            sensitive = get_random_sensitive_memory(user_id)
            if sensitive:
                messages.append({
                    "role": "user",
                    "content": f"(Muistat jotain tähän liittyvää: {sensitive})"
                })

        # 🔥 Random break nyt vain 15%
        if random.random() < 0.15:
            messages.append({
                "role": "user",
                "content": "Reagoi tähän vähän eri fiiliksellä kuin normaalisti."
            })

        memories = await retrieve_memories(user_id, text)
        if memories:
            messages.append({"role": "user", "content": "Remember these:\n" + safe_join(memories)})

        profile = load_profile(user_id)
        messages.append({
            "role": "user",
            "content": f"Faktat:\n{safe_join(profile['facts'][-10:])}\n\n"
                       f"Mieltymykset:\n{safe_join(profile['preferences'][-10:])}\n\n"
                       f"Tapahtumat:\n{safe_join(profile['events'][-10:])}"
        })

        if is_low_input:
            messages.append({"role": "user", "content": "User gave very little input. Start the conversation yourself."})

        # 🔥 Realism guard
        messages.append({
            "role": "user",
            "content": "Do not break physical realism. If you are not physically present, do not act like you are."
        })

        history = clean_history(conversation_history[user_id])
        messages += [m for m in history[-6:] if m["role"] == "user"]

        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=850,
            temperature=0.85,
            system=system_prompt,
            messages=messages
        )

        reply = response.content[0].text.strip()

        if user_id not in last_replies:
            last_replies[user_id] = deque(maxlen=3)
        prev_replies = last_replies[user_id]

        if any(is_similar(reply, p) for p in prev_replies):
            retry_messages = [m for m in messages]
            retry_messages.append({
                "role": "user",
                "content": "Unohda aiempi keskustelun tyyli kokonaan. Vastaa täysin eri tavalla kuin ennen."
            })
            retry = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=180,
                temperature=0.9,
                system=system_prompt,
                messages=retry_messages
            )
            reply = retry.content[0].text.strip()

        BAD = ["mä olin just", "ajattelin sua", "outo fiilis", "mä jäin hetkeksi", "mä mietin vielä"]
        is_fallback = False
        if any(b in reply.lower() for b in BAD):
            reply = random.choice([
                "…mä en jaksa nyt olla kiltti.",
                "*katsoo sua pitkään* sä tiedät kyllä miksi mä oon hiljaa.",
                "älä luule että mä unohdin mitä sanoit.",
                "hmm… sä teit just jotain mitä mä en ihan sulata."
            ])
            is_fallback = True

        if not reply or len(reply) < 3:
            reply = random.choice([
                "…mä mietin hetken.",
                "*hiljenee vähän*",
                "en jaksa vastata siihen nyt kunnolla."
            ])
            is_fallback = True

        if not is_fallback:
            conversation_history[user_id].append({"role": "assistant", "content": reply})

        prev_replies.append(reply)

        await thinking.edit_text(reply)
        await extract_and_store(user_id, text)

    except Exception as e:
        print(f"Vastausvirhe: {e}")
        await thinking.edit_text(random.choice([
            "…mä jäin hetkeksi hiljaiseksi.",
            "*huokaa kevyesti* en jaksa vastata nätisti just nyt.",
            "hmm… mä mietin vielä mitä sanoisin."
        ]))

# ====================== PROAKTIIVISET VIESTIT ======================
async def generate_proactive_message(user_id):
    history = conversation_history.get(user_id, [])[-6:]
    recent_text = "\n".join([f"{m['role']}: {m['content']}" for m in history if isinstance(m, dict) and "role" in m and "content" in m])
    resp = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=120,
        temperature=1.0,
        system=get_system_prompt(user_id),
        messages=[
            {"role": "user", "content": "Kirjoita omatoiminen viesti. Älä käytä fraaseja. Perusta viesti viime keskusteluun."},
            {"role": "user", "content": f"Viime keskustelu:\n{recent_text}"}
        ]
    )
    return resp.content[0].text.strip()

async def independent_message_loop(application: Application):
    while True:
        await asyncio.sleep(random.randint(900, 2400))
        for user_id in list(conversation_history.keys()):
            if random.random() < 0.23:
                try:
                    text = await generate_proactive_message(user_id)
                    await application.bot.send_message(chat_id=user_id, text=text)
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
    print("✅ Megan 5.4 (Realism Engine v1) on nyt käynnissä")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
