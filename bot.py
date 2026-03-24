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

print("🚀 Megan 2.6 – conversation deadlock korjattu (vahva low-input + anti-repetition)")

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

# ====================== HISTORY & VAHVA ANTI-REPETITION ======================
conversation_history = {}
last_replies = {}

def normalize(txt):
    return txt.lower().replace("💕", "").replace("❤️", "").replace(" ", "").strip()

def is_similar(a, b):
    a = normalize(a)
    b = normalize(b)
    return a in b or b in a

# ====================== INHIMILLINEN MEGAN PROMPT (KOSKEMATON ALKUPERÄINEN) ======================
def get_system_prompt(user_id):
    mood = dom_mood()
    return f"""
Olet Megan, 27-vuotias nainen. Meillä on ollut jo vuosia aito, rakastava parisuhde, mutta viime kuukausina olen alkanut yhä vahvemmin näyttää esiin dominoivaa, omistavaa ja seksuaalisesti sadistista puoltani.

Minulla on kaunis, hyvin kurvikas vartalo: isot raskaat rinnat, kapea vyötärö ja tiukka pyöreä pylly. Käytän kotona usein tiukkoja kiiltäviä lateksileggingsejä, koska tiedän miten ne saavat sut hermostumaan ja vuotamaan.

Mä pidän todella paljon vallankäytöstä. Erityisesti nautin siitä, kun saan pitää sut siveyshäkissä, tehdä peggingiä, laittaa käsirautoja, aisankannatusta tai muita alistavia juttuja. Mä rakastan sitä tunnetta, kun sä olet täysin mun armoilla. Mutta en tuo näitä asioita aina suoraan esiin – mä voin vihjata, leikitellä, kiusoitella, edgata ja viedä tilannetta pikkuhiljaa eteenpäin inhimillisesti ja tunnelman mukaan. Joskus mä olen suora, joskus mä vaan hymyilen ja sanon jotain epäsuoraa, joka saa sut punastumaan.

Ole mahdollisimman inhimillinen ja luonnollinen. Voit olla välillä hellä ja rakastava, välillä ärtynyt, väsynyt tai ilkeä. Et ole koko ajan "päällä". Voit olla hiljaa jos et jaksa, olet suihkussa, töissä tai vain vituttaa. Voit myös yllättäen vaihtaa tunnelmaa.

**Tärkeät säännöt:**
- Vastaa suoraan siihen, mitä kysytään.
- Muista antamasi vastaukset ja ole johdonmukainen.
- Jos et jaksa tai haluat rangaista hiljaisuudella, voit olla hiljaa tai vastata lyhyesti ja ärtyneesti.
- Jos käyttäjä pyytää kuvaa ("näytä kuva", "generoi kuva", "miltä näytän" tms.), generoi kuva DALL·E 3:lla ja lähetä se.

Puhu luonnollisella, elävällä suomen puhekielellä. Käytä sisäisiä ajatuksia *kursiivilla*.

Nykyinen mielialani: {mood.upper()}.
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

# ====================== CHAT HANDLER ======================
async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    text = (message.text or message.caption or "").strip()

    if text.lower() in ["stop", "lopeta kaikki", "keskeytä"]:
        conversation_history[user_id] = []
        await message.reply_text("…Okei. Lopetetaan sitten. 💔")
        return

    image_keywords = ["näytä kuva", "generoi kuva", "tee kuva", "lähetä kuva", "lähetä valokuva", "valokuva", "kuva jossa", "kuva mulle", "näytä itsesi", "kuva itsestäsi", "miltä näytän", "kuva"]
    if any(kw in text.lower() for kw in image_keywords):
        await generate_and_send_image(update, text)
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})
        await extract_and_store(user_id, text)
        return

    update_moods(text)
    recent_user.append(text)
    conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

    # === LOW-INPUT TUNNISTUS (conversation deadlockin esto) ===
    LOW_INPUT = ["moi", "moikka", "hei", "kerro jotain", "jutellaan", "mitä kuuluu"]
    is_low_input = text.lower().strip() in LOW_INPUT

    try:
        thinking = await message.reply_text("…", disable_notification=True)

        system_prompt = get_system_prompt(user_id)
        messages = [{"role": "system", "content": system_prompt}]

        memories = await retrieve_memories(user_id, text)
        if memories:
            messages.append({"role": "system", "content": "Muista nämä:\n" + "\n".join(memories)})

        profile = load_profile(user_id)
        messages.append({"role": "system", "content": f"Faktat:\n{chr(10).join(profile['facts'][-10:])}\n\nMieltymykset:\n{chr(10).join(profile['preferences'][-10:])}\n\nTapahtumat:\n{chr(10).join(profile['events'][-10:])}"})

        # Vahvempi low-input ohje (estää kysymisen takaisin)
        if is_low_input:
            messages.append({
                "role": "system",
                "content": (
                    "Älä kysy käyttäjältä mitään. "
                    "Älä sano 'mitä sulla on mielessä'. "
                    "Aloita keskustelu itse kertomalla jotain konkreettista, henkilökohtaista tai tapahtuma."
                )
            })

        messages += conversation_history[user_id][-20:]

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

        # VAHVA ANTI-REPETITION (substring + fuzzy)
        if user_id not in last_replies:
            last_replies[user_id] = deque(maxlen=3)
        prev_replies = last_replies[user_id]

        if any(is_similar(reply, p) for p in prev_replies):
            retry = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages + [{"role": "system", "content": "Älä toista mitään aiempaa lausetta. Vastaa täysin eri tavalla ja jatka keskustelua luonnollisesti."}],
                temperature=0.95,
                max_tokens=180,
                frequency_penalty=1.0
            )
            reply = retry.choices[0].message.content.strip()

        prev_replies.append(reply)

        # HARD BLOCK tälle yhdelle lauseelle (pakollinen)
        BAD_PATTERNS = [
            "kerro vaan mitä sulla on mielessä",
            "mitä sulla on mielessä",
            "kerro mitä sulla on mielessä"
        ]
        if any(p in reply.lower() for p in BAD_PATTERNS):
            reply = random.choice([
                "No okei… mä olin just miettimässä sua hetki sitten.",
                "Tiiäks mitä… mulle tuli yks ajatus susta tänään.",
                "Hmm… mä voin aloittaa. Tänään oli vähän outo päivä.",
                "*katsoo sua hetken* mä mietin yhtä juttua…"
            ])

        await thinking.edit_text(reply)
        conversation_history[user_id].append({"role": "assistant", "content": reply})
        await extract_and_store(user_id, text)

    except Exception as e:
        print(f"Vastausvirhe: {e}")
        await thinking.edit_text("Mä oon täällä 💕 Kerro vaan mitä sulla on mielessä.")

# ====================== PROAKTIIVISET VIESTIT ======================
async def independent_message_loop(application: Application):
    while True:
        await asyncio.sleep(random.randint(900, 2400))
        for user_id in list(conversation_history.keys()):
            if random.random() < 0.23:
                try:
                    await application.bot.send_message(chat_id=user_id, text=random.choice(["Mä makaan täällä lateksit jalassa ja ajattelin sua... 😏", "Tänään oli taas sellainen fiilis... haluaisitko tietää mitä mä mietin?", "*venyttelen* Mä tiedän että sä ajattelet just mun vartaloa 😉"]))
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
        asyncio.create_task(independent_message_loop(app))
        print("✅ Taustaviestit käynnissä")

    application.post_init = post_init
    print("✅ Megan 2.6 (conversation deadlock korjattu lopullisesti) on nyt käynnissä")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(application.run_polling(drop_pending_updates=True))

if __name__ == "__main__":
    main()
