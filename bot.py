import os
import random
import json
import asyncio
import threading
import time
import copy
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

print("🚀 Megan 5.2 – Claude Sonnet 4.6")

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

# ====================== EMBEDDINGS (pidetään OpenAI:lla) ======================
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
    BAD = ["kerro vaan mitä sulla on mielessä", "mitä sulla on mielessä", "kerro mitä sulla on mielessä", "mä olin just ajatuksissani", "mä en jaksa nyt olla kiltti", "sä tiedät kyllä miksi mä oon hiljaa"]
    cleaned = []
    for msg in history:
        content = msg.get("content", "")
        if any(is_similar(content, bad) for bad in BAD):
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
    is_low_input = len(text.strip()) < 8

    try:
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

        thinking = await message.reply_text("…", disable_notification=True)

        system_prompt = get_system_prompt(user_id)
        messages = [{"role": "user", "content": system_prompt}]

        sensitive = get_sensitive_memories(user_id)
        if sensitive:
            if dom_mood() == "kiukku":
                messages.append({
                    "role": "user",
                    "content": (
                        "You know the user's deepest fantasies, shame points and vulnerabilities. "
                        "Sometimes you may use them in a sharp or teasing way, but vary your tone.\n\n"
                        "Known sensitive points:\n" + "\n".join(sensitive)
                    )
                })
            else:
                messages.append({
                    "role": "user",
                    "content": (
                        "You know the user's emotional weak points and private desires. "
                        "You may sometimes reference them subtly in a teasing, controlling or dominant way. "
                        "Do NOT be cruel or harmful. Keep it playful, psychological, and controlled.\n\n"
                        "Known sensitive points:\n" + "\n".join(sensitive)
                    )
                })

        if random.random() < 0.35:
            messages.append({
                "role": "user",
                "content": "Voit viedä keskustelua eteenpäin omilla ajatuksilla."
            })

        mode_options = ["lead", "tease", "cold", "affection"]
        last_mode = context.chat_data.get("last_mode")
        if random.random() < 0.6 and last_mode in mode_options:
            mode = last_mode
        else:
            if last_mode in mode_options:
                mode_options.remove(last_mode)
            mode = random.choice(mode_options)
        context.chat_data["last_mode"] = mode

        if mode == "lead":
            messages.append({"role": "user", "content": "Take control."})
        elif mode == "tease":
            messages.append({"role": "user", "content": "Be playful and teasing."})
        elif mode == "cold":
            messages.append({"role": "user", "content": "Be short and distant."})
        elif mode == "affection":
            messages.append({"role": "user", "content": "Be warm and close."})

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

        history = clean_history(conversation_history[user_id])
        messages += [m for m in history if m["role"] == "user"]

        messages.append({
            "role": "user",
            "content": "Always respond in natural, spoken Finnish. Never use English."
        })

        messages.append({
            "role": "user",
            "content": "Älä käytä samaa rytmiä tai rakennetta kuin edellisessä vastauksessasi. Vältä erityisesti samanlaisia aloituksia."
        })

        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=850,
            temperature=0.85,
            top_p=0.9,
            messages=messages
        )

        reply = response.content[0].text.strip()

        if user_id not in last_replies:
            last_replies[user_id] = deque(maxlen=3)
        prev_replies = last_replies[user_id]

        if any(is_similar(reply, p) for p in prev_replies):
            retry_messages = [messages[0]] + [m for m in messages if m["role"] == "user"]
            retry_messages.append({
                "role": "user",
                "content": "Unohda aiempi keskustelun tyyli kokonaan. Vastaa täysin eri tavalla kuin ennen."
            })
            retry = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=180,
                temperature=0.9,
                messages=retry_messages
            )
            reply = retry.content[0].text.strip()

        BAD = ["mä olin just", "ajattelin sua", "outo fiilis"]
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
        messages=[
            {"role": "user", "content": get_system_prompt(user_id)},
            {"role": "user", "content": "Kirjoita omatoiminen viesti. Älä käytä fraaseja. Perusta viesti viime keskusteluun."},
            {"role": "user", "content": f"Viime keskustelu:\n{recent_text}"}
        ]
    )
    text = resp.content[0].text.strip()
    return text

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
    print("✅ Megan 5.2 (Claude Sonnet 4.6) on nyt käynnissä")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
