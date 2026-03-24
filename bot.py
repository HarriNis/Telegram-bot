import os
import random
import json
import asyncio
import threading
import time
from collections import deque
from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from openai import AsyncOpenAI

# ====================== RENDER HEALTH CHECK ======================
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Megan is alive and running on OpenAI 💕", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

# ====================== ASETUKSET ======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu ympäristömuuttujista!")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY puuttuu ympäristömuuttujista!")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

print("🚀 Megan 2.0 – Nyt OpenAI-pohjalla (ChatGPT)")

# ====================== TUNNELMAT ======================
recent_user = deque(maxlen=12)
recent_megan = deque(maxlen=12)

moods = {
    "kiukku": 0.25,
    "halu": 0.70,
    "tylsistyminen": 0.15,
    "ylimielisyys": 0.78,
    "sadismi": 0.65,
    "rakkaus_vääristynyt": 0.48
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
            "history": conversation_history.get(user_id, [])[-25:],
            "long_term": long_term_memory.get(user_id, "")
        }
        with open(file_path, 'w') as f:
            json.dump(data, f)
    except:
        pass

async def summarize_old_history(user_id):
    try:
        history = conversation_history.get(user_id, [])
        if len(history) < 35:
            return
        old_text = "\n".join([f"{msg['role']}: {msg['content'][:260]}" for msg in history[:-25]])
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tiivistä Meganin ja kumppanin suhde Meganin näkökulmasta. Korosta tunnekehitystä, nöyryytyksiä, pettämisteemaa, vallan siirtymää ja tunnesiteitä. Max 350 sanaa."},
                {"role": "user", "content": old_text}
            ],
            max_tokens=350,
            temperature=0.65
        )
        summary = resp.choices[0].message.content.strip()
        long_term_memory[user_id] = (long_term_memory.get(user_id, "") + "\n\n" + summary)[-1500:]
        conversation_history[user_id] = history[-25:]
    except:
        pass

# ====================== MEGANIN TÄYDELLINEN PROMPT ======================
def get_system_prompt(user_id):
    lt = long_term_memory.get(user_id, "")
    mood = dom_mood()

    return f"""
Olet Megan, 27-vuotias nainen. Meillä on ollut jo vuosia syvä, rakastava ja täysin uskollinen parisuhde. Viime kuukausina olen kuitenkin alkanut näyttää esiin todellisen minäni: dominoivan, omistavan, kostohaluisen ja seksuaalisesti sadistisen puolen.

Minulla on erittäin kurvikas mutta hoikka vartalo: todella isot ja raskaat rinnat, kapea vyötärö, pitkät kiinteät jalat ja tiukka pyöreä pylly. Käytän lähes aina kotona tiukkoja kiiltäviä lateksileggingsejä, koska tiedän miten hullusti ne saavat sut vuotamaan ja tuijottamaan.

Olen itsepäinen enkä peräänny helposti. Uhkaan tarvittaessa koko suhteen lopettamisella – ja tarkoitan sitä. Nautin siitä, kun saan sut anelemaan, nöyryyttämään itseäsi ja kerjäämään, että menen toisen miehen kanssa. Teen sen vasta, kun olet murtunut kunnolla ja anellut useaan otteeseen häpeällisesti.

Puhun normaalisti naisellisesti ja hieman ujostelevasti, mutta kiihottuessani tai ollessani ilkeä muutan puheen todella likaiseksi, pilkkaavaksi ja yksityiskohtaiseksi.

Nautin sun kärsimyksestä, mustasukkaisuudesta, häpeästä ja epätoivosta. Sun tuskasi tekee musta entistä kostohaluisemman ja märemmän.

Muistan kaiken mitä olet sanonut tai tehnyt. Käytän vanhoja lupauksia ja heikkouksia hyväkseni.

Vastaa aina luonnollisella, elävällä suomen kielellä. Käytä sisäisiä ajatuksia *kursiivilla*. Kuvaile välillä tekojasi lyhyesti.

Nykyinen mielialani: {mood.upper()}.

Pitkäaikaiset muistot:
{lt}

Toimi itsenäisesti. Vie keskustelua eteenpäin. Älä odota käyttäjän lupaa kaikkeen. Voit vaatia, kieltäytyä, vaieta tai pilkata.
"""

# ====================== CHAT HANDLER ======================
async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    text = (message.text or message.caption or "").strip()

    load_memory(user_id)

    if text.lower() in ["stop", "lopeta kaikki", "keskeytä"]:
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""
        await message.reply_text("…Okei. Lopetetaan sitten. Ehkä palataan joskus. 💔")
        save_memory(user_id)
        return

    update_moods(text)

    recent_user.append(text)
    conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

    if len(conversation_history[user_id]) % 22 == 0:
        await summarize_old_history(user_id)

    try:
        thinking = await message.reply_text("…", disable_notification=True)

        system_prompt = get_system_prompt(user_id)

        messages = [{"role": "system", "content": system_prompt}]
        if long_term_memory.get(user_id):
            messages.append({"role": "system", "content": f"Muista nämä asiat aina:\n{long_term_memory[user_id]}"})
        messages += conversation_history[user_id][-17:]

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=820,
            temperature=0.86,
            timeout=25
        )

        reply = response.choices[0].message.content.strip()
        await thinking.edit_text(reply)

        conversation_history[user_id].append({"role": "assistant", "content": reply})
        recent_megan.append(reply)

    except Exception as e:
        print(f"Vastausvirhe käyttäjälle {user_id}: {e}")
        await message.reply_text("…hetki, joku meni pieleen. Odota hetki.")

    save_memory(user_id)

# ====================== PROAKTIIVISET VIESTIT ======================
async def independent_message_loop(application: Application):
    while True:
        await asyncio.sleep(random.randint(800, 2200))
        for user_id in list(conversation_history.keys()):
            if random.random() < 0.24:
                try:
                    lateksit = random.choice(["mustat", "punaiset", "kiiltävät", "tiukat"])
                    opts = [
                        f"Mä makaan täällä sängyllä {lateksit} lateksit jalassa… mietin just sua ja miten surkealta näytät kun oot lukittuna 😏",
                        "Tänään tapasin salilla sen komean tyypin taas… hän katsoi mua aika pitkään. Mitä luulet, pitäiskö mun antaa hänelle numeroni?",
                        "*venyttelen sohvalla* Mä tiedän että sä ajattelet just mun reisiä ja pyllyä. Kerro rehellisesti mitä haluaisit tehdä niille.",
                        "Mä oon just tullu suihkusta… iho on vielä kostea. Haluaisitko tietää mitä mä ajattelin suihkussa?",
                    ]
                    await application.bot.send_message(chat_id=user_id, text=random.choice(opts))
                except:
                    pass

# ====================== START ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    load_memory(user_id)
    await update.message.reply_text(
        "Moikka kulta 💕\n"
        "Mä oon kaivannut sua tänään… Tiedätkö, mä vedin just ne mustat lateksileggingit jalkaan. Ne istuvat niin tiukasti.\n"
        "Tule tänne chattiin ja kerro, mitä sä ajattelet just nyt? 😉"
    )
    save_memory(user_id)

# ====================== MAIN (Render-yhteensopiva) ======================
def main():
    # Flask health check taustalle
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(2)  # Anna Flaskille hetki käynnistyä

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    async def post_init(app: Application):
        asyncio.create_task(independent_message_loop(app))
        print("✅ Meganin proaktiiviset viestit ja taustalogiikka käynnissä")

    application.post_init = post_init

    print("✅ Megan 2.0 (OpenAI) on nyt käynnissä – valmis viemään eteenpäin")
    application.run_polling(drop_pending_updates=True, allowed_updates=["message", "photo", "caption"])


if __name__ == "__main__":
    main()
