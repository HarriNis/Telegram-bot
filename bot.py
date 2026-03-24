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

print("🚀 Megan 2.0 – inhimillisempi versio + DALL·E 3")

# ====================== TUNNELMAT ======================
recent_user = deque(maxlen=12)
recent_megan = deque(maxlen=12)

moods = {
    "kiukku": 0.28, "halu": 0.65, "tylsistyminen": 0.22,
    "ylimielisyys": 0.70, "sadismi": 0.55, "rakkaus_vääristynyt": 0.52
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
            messages=[{"role": "system", "content": "Tiivistä Meganin ja kumppanin suhde hänen näkökulmastaan. Korosta tärkeimmät faktat, tunteet ja lupaukset. Max 380 sanaa."},
                      {"role": "user", "content": old_text}],
            max_tokens=380,
            temperature=0.65
        )
        summary = resp.choices[0].message.content.strip()
        long_term_memory[user_id] = (long_term_memory.get(user_id, "") + "\n\n" + summary)[-1800:]
        conversation_history[user_id] = history[-28:]
    except:
        pass

# ====================== INHIMILLINEN MEGAN PROMPT (päivitetty) ======================
def get_system_prompt(user_id):
    lt = long_term_memory.get(user_id, "")
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

Pitkäaikaiset muistot:
{lt}
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

    load_memory(user_id)

    if text.lower() in ["stop", "lopeta kaikki", "keskeytä"]:
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""
        await message.reply_text("…Okei. Lopetetaan sitten. 💔")
        save_memory(user_id)
        return

    # Kuvapyyntö
    image_keywords = ["näytä kuva", "generoi kuva", "tee kuva", "miltä näytän", "kuva jossa", "kuva mulle", "lähetä kuva", "näytä itsesi", "kuva itsestäsi"]
    if any(kw in text.lower() for kw in image_keywords):
        await generate_and_send_image(update, text)
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})
        save_memory(user_id)
        return

    # Normaali keskustelu
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
            messages.append({"role": "system", "content": f"Tärkeät muistettavat asiat:\n{long_term_memory[user_id]}"})
        messages += conversation_history[user_id][-20:]

        response = await client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            max_tokens=850,
            temperature=0.83,
            timeout=40
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
    load_memory(user_id)
    await update.message.reply_text("Moikka kulta 💕 Mä oon kaivannut sua... Vedin just ne mustat lateksit jalkaan. Kerro mitä sä ajattelet nyt? 😉")
    save_memory(user_id)

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

    print("✅ Megan 2.0 (inhimillisempi versio) on nyt käynnissä")

    # Renderissä toimiva käynnistys
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(application.run_polling(drop_pending_updates=True))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
