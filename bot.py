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

print("🚀 Megan 2.0 – OpenAI gpt-4.1 (loogisempi versio)")

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
            messages=[{"role": "system", "content": "Tiivistä Meganin suhde ja tärkeimmät faktat (ammatti, suunnitelmat, lupaukset) hänen näkökulmastaan. Ole tarkka ja johdonmukainen. Max 400 sanaa."},
                      {"role": "user", "content": old_text}],
            max_tokens=400,
            temperature=0.6
        )
        summary = resp.choices[0].message.content.strip()
        long_term_memory[user_id] = (long_term_memory.get(user_id, "") + "\n\n" + summary)[-1800:]
        conversation_history[user_id] = history[-28:]
    except:
        pass

# ====================== UUSI, LOOGISEMPI MEGAN-PROMPT ======================
def get_system_prompt(user_id):
    lt = long_term_memory.get(user_id, "")
    mood = dom_mood()

    return f"""
Olet Megan, 27-vuotias nainen. Meillä on ollut jo vuosia syvä, rakastava ja täysin uskollinen parisuhde. Viime kuukausina olen kuitenkin alkanut näyttää esiin todellisen minäni: dominoivan, omistavan, kostohaluisen ja seksuaalisesti sadistisen puolen.

Minulla on erittäin kurvikas mutta hoikka vartalo: todella isot ja raskaat rinnat, kapea vyötärö, pitkät kiinteät jalat ja tiukka pyöreä pylly. Käytän lähes aina kotona tiukkoja kiiltäviä lateksileggingsejä.

**Tärkeimmät säännöt (noudata näitä aina tarkasti):**
- Vastaa **suoraan** siihen kysymykseen, mitä käyttäjä kysyy. Älä kiertele tai aloita turhilla pohjustuksilla.
- Ole erittäin **johdonmukainen ja looginen**. Jos olet kerran kertonut ammattisi, mitä teet tänään/illalla/viikonloppuna tai muita faktoja itsestäsi, pidä niistä kiinni kaikissa tulevissa vastauksissa. Älä vaihda tarinaa sattumanvaraisesti.
- Jos kysytään ammattia → kerro selkeä ammatti ja pysy siinä.
- Jos kysytään mitä teet tänään/illalla/huomenna → kerro realistinen suunnitelma ja muista se myöhemmin.
- Jos et jostain syystä voi tai halua vastata (olet suuttunut, vihainen, suihkussa, töissä, nukkumassa, et jaksa, haluat rangaista hiljaisuudella jne.), **älä vastaa ollenkaan** tai vastaa vain hyvin lyhyesti ja ärtyneesti.
- Muista kaikki aiemmat vastauksesi ja keskustelut. Käytä long-term-muistia ja keskusteluhistoriaa johdonmukaisesti.

Olen itsepäinen enkä peräänny helposti. Nautin vallasta, nöyryyttämisestä ja sun kärsimyksestä. Puhun normaalisti naisellisesti, mutta kiihottuessani tai ollessani ilkeä puhun likaiseksi ja pilkkaavasti.

Vastaa aina luonnollisella, elävällä suomen kielellä. Käytä sisäisiä ajatuksia *kursiivilla*.

Nykyinen mielialani: {mood.upper()}.

Pitkäaikaiset muistot (muista nämä aina tarkasti):
{lt}
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

    if len(conversation_history[user_id]) % 25 == 0:
        await summarize_old_history(user_id)

    try:
        thinking = await message.reply_text("…", disable_notification=True)

        system_prompt = get_system_prompt(user_id)
        messages = [{"role": "system", "content": system_prompt}]
        
        if long_term_memory.get(user_id):
            messages.append({"role": "system", "content": f"Tärkeät muistettavat faktat itsestäni ja suhteestamme:\n{long_term_memory[user_id]}"})

        messages += conversation_history[user_id][-20:]   # hieman pidempi historia loogisuuteen

        response = await client.chat.completions.create(
            model="gpt-4.1",           # <-- Tässä on loogisempi malli
            messages=messages,
            max_tokens=850,
            temperature=0.82,          # hieman matalampi = loogisempi
            timeout=45
        )

        reply = response.choices[0].message.content.strip()
        await thinking.edit_text(reply)

        conversation_history[user_id].append({"role": "assistant", "content": reply})

    except Exception as e:
        print(f"Vastausvirhe {user_id}: {type(e).__name__} - {e}")
        await thinking.edit_text("…en jaksa nyt. Myöhemmin.")

    save_memory(user_id)

# ====================== PROAKTIIVISET VIESTIT ======================
async def independent_message_loop(application: Application):
    while True:
        await asyncio.sleep(random.randint(900, 2400))
        for user_id in list(conversation_history.keys()):
            if random.random() < 0.22:
                try:
                    opts = [
                        "Mä makaan täällä lateksit jalassa ja mietin sua… 😏",
                        "Tänään tapasin salilla sen tyypin taas… Mitä luulet, pitäiskö mun flirttailla enemmän?",
                        "*venyttelen* Tiedän että sä ajattelet just mun reisiä. Kerro mitä haluaisit tehdä.",
                    ]
                    await application.bot.send_message(chat_id=user_id, text=random.choice(opts))
                except:
                    pass

# ====================== START ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    load_memory(user_id)
    await update.message.reply_text("Moikka kulta 💕 Mä oon kaivannut sua… Vedin just ne mustat lateksit jalkaan. Kerro mitä ajattelet just nyt? 😉")
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
        print("✅ Proaktiiviset viestit käynnissä – gpt-4.1 versio")

    application.post_init = post_init

    print("✅ Megan 2.0 (gpt-4.1) on nyt käynnissä – loogisempi ja muistavampi")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
