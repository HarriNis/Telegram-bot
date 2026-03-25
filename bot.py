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

print("🚀 Megan 4.4 – LOOP-FIX v3 (Behavioral Attractor Killer)")

# ====================== DATABASE + MIGRATION ======================
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

cursor.execute("PRAGMA table_info(memories)")
columns = [info[1] for info in cursor.fetchall()]
if 'type' not in columns:
    print("🛠️ Migrating database: adding missing 'type' column...")
    cursor.execute("ALTER TABLE memories ADD COLUMN type TEXT DEFAULT 'general'")
    cursor.execute("UPDATE memories SET type = 'general' WHERE type IS NULL")
    conn.commit()
    print("✅ Migration complete")

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
        txt = text.lower()
        tag = "sensitive" if any(w in txt for w in ["pelkään", "häpeän", "nolottaa", "fantasia", "heikko", "arka", "haluan", "kokeilla", "kiusaa"]) else "general"
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
    try:
        cursor.execute(
            "SELECT content FROM memories WHERE user_id=? AND type='sensitive' ORDER BY timestamp DESC LIMIT 6",
            (str(user_id),)
        )
        return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        print("Sensitive memory error:", e)
        return []

# ====================== PROFILE ======================
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
            model="gpt-5.4",
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

# ====================== HISTORY & ANTI-REPETITION ======================
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

# ====================== ENGLISH SYSTEM PROMPT (KOSKEMATON) ======================
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

# ====================== MEGAN_CHAT (4.4 – Behavioral Attractor Killer) ======================
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

    try:
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

        if len(conversation_history[user_id]) > 30:
            conversation_history[user_id] = conversation_history[user_id][-30:]

        thinking = await message.reply_text("…", disable_notification=True)

        # Base system + persona variation (rikkoo attractorin)
        base_system = get_system_prompt(user_id)
        persona_variation = random.choice([
            "Olet tänään rauhallisempi ja vähemmän dominoiva.",
            "Olet tänään ärtynyt ja lyhytsanainen.",
            "Olet tänään leikkisä etkä ota tilannetta vakavasti.",
            "Olet tänään epävarma ja hieman pehmeämpi.",
            "Olet tänään täysin välinpitämätön."
        ])
        base_system += f"\n\nTemporary personality shift: {persona_variation}"
        messages = [{"role": "system", "content": base_system}]

        # Sensitive-muistot (pidetään, koska ei poistettu pysyvästi)
        sensitive = get_sensitive_memories(user_id)
        if sensitive:
            if dom_mood() == "kiukku":
                messages.append({"role": "system", "content": "You know the user's deepest fantasies, shame points and vulnerabilities. Sometimes you may use them in a sharp or teasing way, but vary your tone.\n\nKnown sensitive points:\n" + "\n".join(sensitive)})
            else:
                messages.append({"role": "system", "content": "You know the user's emotional weak points and private desires. You may sometimes reference them subtly in a teasing, controlling or dominant way. Do NOT be cruel or harmful. Keep it playful, psychological, and controlled.\n\nKnown sensitive points:\n" + "\n".join(sensitive)})

        # Muistit + profiili → nyt USER-viestinä (poistettu system-layer)
        memories = await retrieve_memories(user_id, text)
        profile = load_profile(user_id)
        context_info = "Muista nämä asiat käyttäjästä:\n"
        if memories:
            context_info += "Viimeaikaiset muistot:\n" + "\n".join(memories) + "\n\n"
        context_info += f"Faktat:\n" + "\n".join(profile['facts'][-12:]) + "\n\nMieltymykset:\n" + "\n".join(profile['preferences'][-12:]) + "\n\nTapahtumat:\n" + "\n".join(profile['events'][-12:])
        messages.append({"role": "user", "content": context_info})

        # Vain user-viestit historiasta
        history = conversation_history[user_id][-12:]
        seen = set()
        clean_history = []
        for msg in history:
            content = msg.get("content", "")
            norm = normalize(content)
            if norm not in seen:
                seen.add(norm)
                clean_history.append(msg)
        messages += [m for m in clean_history if m["role"] == "user"]

        # 🔥 Style-break nyt USER-viestinä (tärkein muutos)
        style_break = random.choice([
            "Puhu lyhyesti ja töksähtäen, melkein ärtyneesti.",
            "Puhu hitaasti, pehmeästi ja viettelevästi.",
            "Ole täysin välinpitämätön ja kylmä.",
            "Ole leikkisä, kevyt ja nauraen.",
            "Ole outo, arvaamaton ja hiukan hullu.",
            "Älä johda, vaan reagoi vain siihen mitä käyttäjä sanoi.",
            "Ole rakastava mutta samalla hallitseva.",
            "Ole ärtynyt ja väsynyt."
        ])
        messages.append({"role": "user", "content": f"[INTERNAL NOTE: {style_break} Älä käytä samaa rytmiä tai aloitusta kuin koskaan ennen.]"})

        # Anti-pattern breaker
        messages.append({"role": "system", "content": "Vältä erityisesti seuraavia: hidas viettely, vihjaileva kontrolli, samanlainen rytmi kuin ennen. Vaihda rakennetta radikaalisti."})

        # Kutsu GPT
        response = await client.chat.completions.create(
            model="gpt-5.4",
            messages=messages,
            temperature=0.68,
            top_p=0.80,
            max_tokens=850,
            frequency_penalty=1.25,
            presence_penalty=0.70,
            timeout=45
        )

        reply = response.choices[0].message.content.strip()

        # Anti-repetition + HARD reset retry
        if user_id not in last_replies:
            last_replies[user_id] = deque(maxlen=5)
        prev_replies = last_replies[user_id]

        if any(is_similar(reply, p) for p in prev_replies):
            print(f"🔄 Anti-loop trigger: similarity detected → HARD reset retry")
            retry_messages = [
                {"role": "system", "content": get_system_prompt(user_id)},
                {"role": "user", "content": text},
                {"role": "system", "content": "Vastaa täysin eri tavalla kuin koskaan aiemmin. Älä käytä samaa tyyliä, rytmiä tai fraaseja. Riko kaikki aiemmat patternit."}
            ]
            retry = await client.chat.completions.create(
                model="gpt-5.4",
                messages=retry_messages,
                temperature=0.85,
                top_p=0.88,
                max_tokens=400,
                frequency_penalty=1.5,
                presence_penalty=0.95
            )
            reply = retry.choices[0].message.content.strip()

        conversation_history[user_id].append({"role": "assistant", "content": reply})
        prev_replies.append(reply)

        await thinking.edit_text(reply)
        await extract_and_store(user_id, text)

    except Exception as e:
        print(f"Vastausvirhe: {e}")
        await thinking.edit_text(random.choice([
            "…mä jäin hetkeksi hiljaiseksi.",
            "*huokaa kevyesti*",
            "hmm… mä mietin vielä."
        ]))

# ====================== PROAKTIIVINEN VIESTI ======================
async def generate_proactive_message(user_id):
    history = conversation_history.get(user_id, [])[-10:]
    recent_text = "\n".join([f"{m['role']}: {m['content']}" for m in history if isinstance(m, dict) and "content" in m])
    resp = await client.chat.completions.create(
        model="gpt-5.4",
        messages=[
            {"role": "system", "content": get_system_prompt(user_id)},
            {"role": "system", "content": "Kirjoita lyhyt, luonnollinen omatoiminen viesti. Vaihda aina sävyä radikaalisti. Älä käytä vanhoja fraaseja."},
            {"role": "system", "content": f"Viime keskustelu:\n{recent_text}"}
        ],
        temperature=1.12,
        max_tokens=140
    )
    return resp.choices[0].message.content.strip()

# ====================== PROAKTIIVISET VIESTIT ======================
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
    print("✅ Megan 4.4 (LOOP-FIX v3 – Attractor Killer) on nyt käynnissä")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
