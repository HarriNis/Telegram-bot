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

print("🚀 Megan 2.1 – production memory version (täysi alkuperäinen prompt)")

# ====================== DATABASE ======================
# Renderissä pysyvä muisti: lisää Disk mount /var/data
DB_PATH = "/var/data/megan_memory.db"   # uusi, pysyy ikuisesti
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
    resp = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return np.array(resp.data[0].embedding, dtype=np.float32)

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

# ====================== MEMORY STORE ======================
async def store_memory(user_id, text):
    try:
        if len(text) < 25:          # suodatus: ei turhaa roskaa
            return
        emb = await get_embedding(text)
        cursor.execute(
            "INSERT INTO memories (user_id, content, embedding) VALUES (?, ?, ?)",
            (str(user_id), text, emb.tobytes())
        )
        conn.commit()
    except Exception as e:
        print("Memory store error:", e)

# ====================== MEMORY RETRIEVAL ======================
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
            if score > 0.78:        # relevanssikynnys
                scored.append((score, content))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [c for _, c in scored[:limit]]
    except Exception as e:
        print("Memory retrieval error:", e)
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

# ====================== PROFILE EXTRACTION ======================
async def extract_and_store(user_id, text):
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content":
                 "Poimi tärkeät faktat, mieltymykset ja tapahtumat JSON-muodossa. "
                 "Palauta vain JSON: {\"facts\":[],\"preferences\":[],\"events\":[]}"},
                {"role": "user", "content": text}
            ],
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
                    profile[k] = profile[k][-20:]   # cap
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
    "ylimielisyys": 0.45, "sadismi": 0.55, "rakkaus_vääristynyt": 0.52   # ylimielisyys laskettu inhimillisemmäksi
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
        moods[k] = max(0.10, min(1.0, moods[k] + (0.45 - moods[k]) * 0.045))

def dom_mood():
    return max(moods, key=moods.get)

# ====================== HISTORY & ANTI-LOOP ======================
conversation_history = {}
last_replies = {}          # <-- uusi: estää toistuvan saman vastauksen

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

        enhanced_prompt = (
            f"27-vuotias kaunis platina-blondi nainen, valtavat raskaat rinnat, kapea vyötärö, "
            f"tiukka pyöreä pylly, käyttää tiukkoja kiiltäviä mustia lateksileggingsejä, dominoiva ja seksikäs ilme, "
            f"realistinen valokuva, korkea yksityiskohtaisuus, studio-valaistus, 8k -- {user_text}"
        )

        response = await client.images.generate(
            model="dall-e-3",
            prompt=enhanced_prompt,
            n=1,
            size="1024x1024",
            quality="standard"
        )

        image_url = response.data[0].url

        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=35) as resp:
                if resp.status != 200:
                    raise Exception(f"Download failed")
                image_data = await resp.read()

        caption = random.choice([
            "Tässä sulla on se kuva mitä halusit... katso tarkkaan 😈",
            "Mä tein tän just sulle. Mitä tunteita se herättää? 💦",
            "No niin... tässä on se. Tykkäätkö? 😉"
        ])

        await thinking.edit_text("Lähetän kuvan...")
        await update.message.reply_photo(
            photo=BytesIO(image_data),
            caption=caption,
            filename="megan_image.png"
        )

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

    # Kuvapyyntö
    image_keywords = ["näytä kuva", "generoi kuva", "tee kuva", "miltä näytän", "kuva jossa", "kuva mulle", "lähetä kuva", "näytä itsesi", "kuva itsestäsi"]
    if any(kw in text.lower() for kw in image_keywords):
        await generate_and_send_image(update, text)
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})
        await extract_and_store(user_id, text)
        return

    # Normaali keskustelu
    update_moods(text)
    recent_user.append(text)
    conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

    try:
        thinking = await message.reply_text("…", disable_notification=True)

        system_prompt = get_system_prompt(user_id)
        messages = [{"role": "system", "content": system_prompt}]

        # === PITKÄAIKAINEN MUISTI (production-parannukset) ===
        memories = await retrieve_memories(user_id, text)
        if memories:
            messages.append({
                "role": "system",
                "content": "Muista nämä:\n" + "\n".join(memories)
            })

        profile = load_profile(user_id)
        messages.append({
            "role": "system",
            "content": f"""
Faktat:
{chr(10).join(profile['facts'][-10:])}

Mieltymykset:
{chr(10).join(profile['preferences'][-10:])}

Tapahtumat:
{chr(10).join(profile['events'][-10:])}
"""
        })

        messages += conversation_history[user_id][-20:]

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.83,
            max_tokens=850,
            timeout=40
        )

        reply = response.choices[0].message.content.strip()

        # ===== ANTI-LOOP FIX =====
        prev = last_replies.get(user_id)
        if prev and reply.lower() == prev.lower():
            # pakotetaan erilainen vastaus
            retry = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages + [{
                    "role": "system",
                    "content": "Älä toista samaa vastausta. Vastaa eri tavalla tai avaa tunnetta lyhyesti."
                }],
                temperature=0.9,
                max_tokens=120
            )
            reply = retry.choices[0].message.content.strip()

        last_replies[user_id] = reply

        # ===== INHIMILLINEN KIUKKU/VÄSYNYT SIIRTYMÄ =====
        # (ei koske promptia – lisätään vastauksen jälkeen inhimillinen varoitus/syy)
        current_mood = dom_mood()
        if current_mood in ["kiukku", "tylsistyminen"] and any(neg in reply.lower() for neg in ["en jaksa", "loppu", "väsynyt", "vituttaa"]):
            # varoitetaan ensin ja kerrotaan syy
            transition_phrases = [
                f"*sigh* Mä oon vaan tosi väsynyt just nyt… {random.choice(['viimeiset viestit vähän ärsytti', 'töissä oli rankka päivä', 'tarviin pienen hetken itselleni'])}.",
                f"Mä alan olla ihan loppu… anna hetki, mä selitän kohta miksi.",
                f"*huokaus* Mä en jaksa keskustella just nyt. Syynä on se että {random.choice(['mä oon ihan poikki', 'sä sait mut vähän ärtyneeksi', 'mulla on paljon mielessä'])}."
            ]
            reply = random.choice(transition_phrases) + "\n\n" + reply

        # jos vastauksessa on "en jaksa nyt", korvataan inhimillisemmällä
        if reply.lower().count("en jaksa nyt") > 0:
            reply = random.choice([
                "…mä oon vaan ihan loppu nyt. Puhutaan myöhemmin.",
                "Ei nyt jaksa oikeesti. Anna hetki.",
                "Mulla ei oo energiaa tähän just nyt…",
                "Voidaanko palata tähän myöhemmin?"
            ])

        await thinking.edit_text(reply)

        conversation_history[user_id].append({"role": "assistant", "content": reply})

        # Tallennetaan automaattisesti
        await extract_and_store(user_id, text)

    except Exception as e:
        print(f"Vastausvirhe: {e}")
        await thinking.edit_text("…en jaksa nyt.")

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
        asyncio.create_task(independent_message_loop(app))
        print("✅ Taustaviestit käynnissä")

    application.post_init = post_init

    print("✅ Megan 2.1 (production-muisti + anti-loop + inhimillinen kiukku-siirtymä) on nyt käynnissä")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(application.run_polling(drop_pending_updates=True))
    finally:
        loop.close()

if __name__ == "__main__":
    main()
