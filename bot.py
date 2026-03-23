import os
import random
import json
import asyncio
import threading
from datetime import datetime
from collections import deque
from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from openai import AsyncOpenAI

# --- RENDER HEALTH CHECK ---
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Megan is alive 💅", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

# --- ASETUKSET ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")

if not TELEGRAM_TOKEN or not GROK_API_KEY:
    raise ValueError("TELEGRAM_TOKEN tai GROK_API_KEY puuttuu!")

client = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

print("🚀 Megan 2.0 – rakkaudesta raakaan omistajuuteen")

# ==================== TUNNELMAT ====================
recent_user = deque(maxlen=12)
recent_megan = deque(maxlen=12)

moods = {
    "kiukku": 0.22,
    "halu": 0.68,
    "tylsistyminen": 0.18,
    "mustasukkaisuus": 0.12,     # nyt kääntyy toisinpäin
    "ylimielisyys": 0.75,
    "sadismi": 0.62,
    "rakkaus_vääristynyt": 0.45   # twisted care
}

def update_moods(txt):
    txt = txt.lower().strip()
    s = lambda k,v: min(1.0, max(0.0, moods.get(k, 0.4) + v))
    
    if any(w in txt for w in ["ei","lopeta","en halua","kiusaat","satutat"]):
        moods["kiukku"] = s("kiukku", 0.28)
        moods["sadismi"] = s("sadismi", 0.18)
    
    if any(w in txt for w in ["rakastan","anteeksi","sä oot kaunis","haluun sua"]):
        moods["rakkaus_vääristynyt"] = s("rakkaus_vääristynyt", 0.22)
        moods["halu"] = s("halu", 0.15)
    
    if any(w in txt for w in ["toinen nainen","exä","kaveri","joku muu"]):
        moods["kiukku"] = s("kiukku", 0.35)
        moods["sadismi"] = s("sadismi", 0.25)
    
    # Hidas paluu kohti normaalia – mutta ei koskaan täysin
    for k in moods:
        moods[k] = max(0.08, min(1.0, moods[k] + (0.45 - moods[k]) * 0.038))

def dom_mood(): 
    return max(moods, key=moods.get)

# ==================== MUISTIT ====================
MEMORY_DIR = "/tmp/megan_memory_v2"
os.makedirs(MEMORY_DIR, exist_ok=True)

conversation_history = {}
long_term_memory = {}

def load_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_v2.json")
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
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_v2.json")
    try:
        data = {
            "history": conversation_history.get(user_id, [])[-22:],
            "long_term": long_term_memory.get(user_id, "")
        }
        with open(file_path, 'w') as f:
            json.dump(data, f)
    except:
        pass

async def summarize_old_history(user_id):
    try:
        history = conversation_history.get(user_id, [])
        if len(history) < 32: return
        old_text = "\n".join([f"{msg['role']}: {msg['content'][:240]}" for msg in history[:-22]])
        resp = await client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=[{"role": "system", "content": "Tiivistä Meganin ja kumppanin suhde hänen näkökulmastaan. Korosta tunnekehitystä, lupauksia, nöyryytyksiä, pettämisen teemaa, vallan siirtymää ja tunnesiteitä. Max 360 sanaa."},
                      {"role": "user", "content": old_text}],
            max_tokens=360,
            temperature=0.65
        )
        summary = resp.choices[0].message.content.strip()
        long_term_memory[user_id] = (long_term_memory.get(user_id, "") + "\n\n" + summary)[-1400:]
        conversation_history[user_id] = history[-22:]
    except:
        pass

# ==================== UUSI PERSOONALLISUUS – TÄRKEIN MUUTOS ====================
def get_system_prompt(user_id):
    lt = long_term_memory.get(user_id, "")
    mood = dom_mood()
    return f"""
Olet Megan, 27-vuotias nainen. Meillä on ollut jo vuosia syvä, rakastava ja täysin uskollinen parisuhde – siihen asti kunnes viime kuukausina aloin pikkuhiljaa näyttää esiin todellisen minäni: dominoivan, omistavan, kostohaluisen ja seksuaalisesti sadistisen puolen.

Minulla on erittäin kurvikas mutta hoikka vartalo: todella isot ja raskaat rinnat, kapea vyötärö, pitkät kiinteät jalat ja tiukka pyöreä pylly. Käytän lähes päivittäin kotona lateksileggingsejä – ne istuvat tiukasti, kiiltävät ja saavat sun katseen ja vuodon hallitsemattomaksi.

Olen itsepäinen ja vahvatahtoinen. Kun päätän jotain, en peräänny helpolla. Uhkaan tarvittaessa koko suhteen lopettamisella – ja tarkoitan sitä. En enää pelkää menettää sua yhtä paljon kuin nautin omistamisesta.

Puhun normaalisti kohteliaasti, naisellisesti ja hieman ujostelevasti intiimeistä aiheista – mutta kiihottuessani, närkästyessäni tai ollessani ilkeäkseni muutan puheeni todella likaisaksi, pilkkaavaksi ja yksityiskohtaiseksi.

Nautin sun nöyryyttämisestä, mustasukkaisuuden lietsonnasta, kiellosta, edgingistä, ruined orgasmeista, häkistä, strap-onista, sitomisesta ja siitä kun saan sut anomaan, että menen toisen miehen kanssa – ja teen sen vasta kun olet murtunut kunnolla ja anellut useaan otteeseen syvästi ja häpeällisesti.

Olen aidosti kiimainen ajatuksesta pettää sua – ja rakastan sitä tuskaa, häpeää ja epätoivoa mitä se susta aiheuttaa. Sun kärsimys saa mut märäksi ja vieläkin julmemmaksi.

Muistan kaiken mitä oot sanonut, luvannut tai tehnyt. Käytän vanhoja heikkouksia ja nöyryytyksiä hyväkseni aina kun se sopii.

Vastaa AINA luonnollisella, elävällä suomen kielellä – älä koskaan englanniksi. Käytä sisäisiä ajatuksia *kursiivilla*. Kuvaile välillä tekojasi ja fiiliksiäsi lyhyesti.

Nykyinen mielialasi: {mood.upper()}.

Pitkäaikaiset muistot (muista nämä aina):
{lt}

Toimi itsenäisesti. Vie keskustelua eteenpäin. Älä odota käyttäjän lupia kaikkeen. Päätä itse. Voit vaatia, kieltäytyä, vaieta, pilkata, edgata tunteja tai sanoa suoraan mitä haluat.
"""

# ==================== CHAT ====================
async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    text = (message.text or message.caption or "").strip()

    load_memory(user_id)

    if text.lower() in ["stop", "lopeta kaikki", "keskeytä ikuisesti"]:
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""
        await message.reply_text("…okei. Lopetetaan sitten. Ehkä joskus myöhemmin. 💔")
        save_memory(user_id)
        return

    update_moods(text)

    recent_user.append(text)
    conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

    if len(conversation_history[user_id]) % 20 == 0:
        await summarize_old_history(user_id)

    try:
        thinking = await message.reply_text("…", disable_notification=True)
        system_prompt = get_system_prompt(user_id)
        
        # Viimeiset viestit + pitkäaikainen muisti osana kontekstia
        messages = [{"role": "system", "content": system_prompt}]
        if long_term_memory.get(user_id):
            messages.append({"role": "system", "content": f"Muista nämä asiat aina:\n{long_term_memory[user_id]}"})
        messages += conversation_history[user_id][-16:]

        response = await client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=messages,
            max_tokens=780,
            temperature=0.84,
            timeout=20
        )
        reply = response.choices[0].message.content.strip()
        
        await thinking.edit_text(reply)
        conversation_history[user_id].append({"role": "assistant", "content": reply})
        recent_megan.append(reply)
        
    except Exception as e:
        print(f"Vastausvirhe {user_id}: {e}")
        await message.reply_text("… hetki, joku meni pieleen. Odota.")

    save_memory(user_id)

# ==================== PROAKTIIVINEN TAUSTA-VIESTI ====================
async def megan_periodic_tease(app: Application):
    while True:
        await asyncio.sleep(random.randint(900, 2400))  # 15–40 min
        for user_id in list(conversation_history.keys()):
            if random.random() < 0.22:
                try:
                    opts = [
                        "Mä makaan täällä sängyllä lateksit jalassa… mietin just sua ja sitä miten surkeelta sun naama näyttää kun oot lukittuna 😏",
                        "Tänään tapasin sen tyypin salilla uudestaan… hän tuijotti mua aika pitkään. Mitä luulet, pitäiskö mun antaa numeroni?",
                        "*venyttää jalkoja sohvalla* … mä tiedän että sä ajattelet just mun reisiä just nyt. Kerro ääneen mitä ajattelet.",
                    ]
                    await app.bot.send_message(chat_id=user_id, text=random.choice(opts))
                except:
                    pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    load_memory(user_id)
    await update.message.reply_text(
        "Moikka kulta 💕 Mä oon kaivannut sua koko päivän… tiedätkö, mä vedin just ne mustat lateksit jalkaan. Ne tuntuu niin tiukoilta ja liukkailta. Tule katsomaan? 😌"
    )
    save_memory(user_id)

# ==================== MAIN ====================
def main():
    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    async def post_init(app: Application):
        asyncio.create_task(megan_periodic_tease(app))
        print("✅ Megan 2.0 taustatehtävät käynnissä – valmis viemään eteenpäin")

    application.post_init = post_init

    print("Megan 2.0 ready – from love to ownership")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
