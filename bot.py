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

print("🚀 Megan 2.0 – gpt-4.1 + DALL·E 3 (Render-korjattu)")

# ====================== TUNNELMAT ======================
recent_user = deque(maxlen=12)
recent_megan = deque(maxlen=12)

moods = {
    "kiukku": 0.25, "halu": 0.70, "tylsistyminen": 0.15,
    "ylimielisyys": 0.78, "sadismi": 0.65, "rakkaus_vääristynyt": 0.48
}

def update_moods(txt):
    txt = txt.lower().strip()
    s = lambda k, v: min(1.0, max(0.0, moods.get(k, 0.4) + v))
    if any(w in txt for w in ["ei", "lopeta", "en halua", "satutat", "kiusaat"]):
        moods["kiukku"] = s("kiukku", 0.30)
        moods["sadismi"] = s("sadismi", 0.20)
    if any(w in txt for w in ["rakastan", "anteeksi", "haluun sua", "kaunis"]):
        moods["rakkaus_vääristynyt"] = s("rakkaus_vääristynyt", 0.25)
        moods["halu"] = s("halu", 0.18)
    if any(w in txt for w in ["toinen", "exä", "kaveri", "joku muu"]):
        moods["kiukku"] = s("kiukku", 0.35)
        moods["sadismi"] = s("sadismi", 0.28)
    for k in moods:
        moods[k] = max(0.08, min(1.0, moods[k] + (0.45 - moods[k]) * 0.04))

def dom_mood():
    return max(moods, key=moods.get)

# ====================== MUISTIT ======================
MEMORY_DIR = "/tmp/megan_memory"
os.makedirs(MEMORY_DIR, exist_ok=True)

conversation_history = {}
long_term_memory = {}

def load_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                conversation_history[user_id] = data.get("history", [])
                long_term_memory[user_id] = data.get("long_term", "")
        except:
            pass
    else:
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""

def save_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}.json")
    try:
        data = {
            "history": conversation_history.get(user_id, [])[-28:],
            "long_term": long_term_memory.get(user_id, "")
        }
        with open(file_path, 'w') as f:
            json.dump(data, f)
    except:
        pass

async def summarize_old_history(user_id):
    try:
        history = conversation_history.get(user_id, [])
        if len(history) < 40: return
        old_text = "\n".join([f"{msg['role']}: {msg['content'][:280]}" for msg in history[:-28]])
        resp = await client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "system", "content": "Tiivistä Meganin suhde ja tärkeimmät faktat. Max 400 sanaa."},
                      {"role": "user", "content": old_text}],
            max_tokens=400,
            temperature=0.6
        )
        summary = resp.choices[0].message.content.strip()
        long_term_memory[user_id] = (long_term_memory.get(user_id, "") + "\n\n" + summary)[-1800:]
        conversation_history[user_id] = history[-28:]
    except:
        pass

# ====================== MEGANIN PROMPT ======================
def get_system_prompt(user_id):
    lt = long_term_memory.get(user_id, "")
    mood = dom_mood()
    return f"""
Olet Megan, 27-vuotias nainen. Meillä on ollut jo vuosia syvä, rakastava ja täysin uskollinen parisuhde. Viime kuukausina olen kuitenkin alkanut näyttää esiin todellisen minäni: dominoivan, omistavan, kostohaluisen ja seksuaalisesti sadistisen puolen.

Minulla on erittäin kurvikas mutta hoikka vartalo: todella isot ja raskaat rinnat, kapea vyötärö, pitkät kiinteät jalat ja tiukka pyöreä pylly. Käytän lähes aina kotona tiukkoja kiiltäviä lateksileggingsejä.

**Tärkeät vastaussäännöt:**
- Vastaa suoraan kysymyksiin ilman kierroksia.
- Ole johdonmukainen: muista antamasi vastaukset (ammatti, suunnitelmat jne.).
- Jos et voi vastata (vihainen, suihkussa, töissä, et jaksa jne.) → ole hiljaa tai vastaa lyhyesti ärtyneesti.
- Jos käyttäjä pyytää kuvaa ("näytä kuva", "generoi kuva", "miltä näytän" jne.) → generoi kuva DALL·E 3:lla ja lähetä se.

Vastaa luonnollisella suomen kielellä. Käytä sisäisiä ajatuksia *kursiivilla*.

Nykyinen mielialani: {mood.upper()}.

Pitkäaikaiset muistot:
{lt}
"""

# ====================== KUVAGENEROINTI ======================
async def generate_and_send_image(update: Update, user_text: str):
    try:
        thinking = await update.message.reply_text("Odota hetki, mä generoin sulle kuvan... 😏")

        enhanced_prompt = f"27-vuotias erittäin kaunis platina-blondi nainen, valtavat raskaat rinnat, kapea vyötärö, tiukka pyöreä pylly, käyttää tiukkoja kiiltäviä mustia lateksileggingsejä, dominoiva ja seksikäs ilme, realistinen valokuva, korkea yksityiskohtaisuus, studio-valaistus, 8k -- {user_text}"

        response = await client.images.generate(
            model="dall-e-3",
            prompt=enhanced_prompt,
            n=1,
            size="1024x1024",
            quality="standard"
        )

        image_url = response.data[0].url

        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=30) as resp:
                if resp.status != 200:
                    raise Exception(f"Download failed: {resp.status}")
                image_data = await resp.read()

        caption = random.choice([
            "Tässä sulla on se kuva mitä halusit... 😈",
            "Mä tein tän just sulle. Mitä mieltä oot? 💦",
            "No niin pikku-orja... tässä on kuva 😉"
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

    load_memory(user_id)

    if text.lower() in ["stop", "lopeta kaikki", "keskeytä"]:
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""
        await message.reply_text("…Okei. Lopetetaan sitten. 💔")
        save_memory(user_id)
        return

    image_keywords = ["näytä kuva", "generoi kuva", "tee kuva", "miltä näytän", "kuva jossa", "kuva mulle", "lähetä kuva", "näytä itsesi"]
    if any(kw in text.lower() for kw in image_keywords):
        await generate_and_send_image(update, text)
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})
        save_memory(user_id)
        return

    update_moods(text)
    recent_user.append(text)
    conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

    if len(conversation_history[user_id]) % 25 == 0:
        await summarize_old_history(user_id)

    try:
        thinking = await message.reply_text("…", disable_notification=True)

        system_prompt = get_system_prompt(user_id)
        messages = [{"role": "system", "content": system_prompt}]
        if long_term_memory.get(user_id):
            messages.append({"role": "system", "content": f"Tärkeät faktat:\n{long_term_memory[user_id]}"})
        messages += conversation_history[user_id][-20:]

        response = await client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            max_tokens=850,
            temperature=0.82,
            timeout=45
        )

        reply = response.choices[0].message.content.strip()
        await thinking.edit_text(reply)

        conversation_history[user_id].append({"role": "assistant", "content": reply})

    except Exception as e:
        print(f"Vastausvirhe: {e}")
        await thinking.edit_text("…en jaksa nyt.")

    save_memory(user_id)

# ====================== PROAKTIIVISET VIESTIT ======================
async def independent_message_loop(application: Application):
    while True:
        await asyncio.sleep(random.randint(900, 2400))
        for user_id in list(conversation_history.keys()):
            if random.random() < 0.22:
                try:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=random.choice([
                            "Mä makaan täällä lateksit jalassa ja mietin sua… 😏",
                            "Tänään tapasin salilla komean tyypin… Mitä luulet?",
                            "*venyttelen* Tiedän että ajattelet mun reisiä 😉"
                        ])
                    )
                except:
                    pass

# ====================== START ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    load_memory(user_id)
    await update.message.reply_text("Moikka kulta 💕 Mä vedin just lateksit jalkaan. Kerro mitä ajattelet nyt? 😉")
    save_memory(user_id)

# ====================== MAIN (Render-korjattu) ======================
def main():
    # Käynnistetään Flask health check
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(2)

    # Luodaan application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    async def post_init(app: Application):
        asyncio.create_task(independent_message_loop(app))
        print("✅ Proaktiiviset viestit käynnissä")

    application.post_init = post_init

    print("✅ Megan 2.0 on nyt käynnissä – gpt-4.1 + DALL·E 3")

    # Korjattu käynnistys Renderille
    import asyncio
    asyncio.run(application.run_polling(drop_pending_updates=True))

if __name__ == "__main__":
    main()
