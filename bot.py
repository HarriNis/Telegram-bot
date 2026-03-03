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
    return "Megan is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

# --- ASETUKSET ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")

if not TELEGRAM_TOKEN or not GROK_API_KEY:
    raise ValueError("TELEGRAM_TOKEN tai GROK_API_KEY puuttuu!")

client = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

print("🚀 Megan käynnistyy – inhimillisempi versio + Render-stabiili")

# ==================== TUNNELMAT ====================
recent_user = deque(maxlen=15)
recent_megan = deque(maxlen=15)

moods = {"kiukku":0.45, "halu":0.65, "tylsä":0.28, "mustas":0.42, "iva":0.72, "väsy":0.35, "syyllisyys":0.18}

def update_moods(txt):
    txt = txt.lower()
    g = moods.get
    s = lambda k,v: min(1.0, g(k)+v) if v>0 else max(0.0, g(k)+v)
    if any(w in txt for w in ["älä","lopeta","en halua","en kestä","ei","lopeta jo"]):
        moods["kiukku"] = s("kiukku",0.22); moods["halu"] = s("halu",-0.16)
    if any(w in txt for w in ["rakastan","kiitos","seksikäs","haluun sua","kiima","rakas"]):
        moods["halu"] = s("halu",0.32); moods["tylsä"] = s("tylsä",-0.22)
    if any(w in txt for w in ["muu mies","kaveri","exä","toinen","kuka","joku muu"]):
        moods["mustas"] = s("mustas",0.38); moods["kiukku"] = s("kiukku",0.18)
    if len(txt.strip()) < 12 and random.random() < 0.48:
        moods["tylsä"] = s("tylsä",0.20)
    for k in moods:
        moods[k] = max(0.05, min(1.0, moods[k] + (0.5 - moods[k]) * 0.055))

def dom_mood(): return max(moods, key=moods.get)

def too_similar(t, hist):
    t = t.lower().strip()
    for o in hist:
        o = o.lower().strip()
        if len(t)>6 and (o.startswith(t[:6]) or t.startswith(o[:6])): return True
        if len(set(t.split()) & set(o.split())) > 5 and abs(len(t.split()) - len(o.split())) < 6: return True
    return False

# ==================== MUISTIT ====================
MEMORY_DIR = "/tmp/megan_memory"
os.makedirs(MEMORY_DIR, exist_ok=True)

conversation_history = {}
long_term_memory = {}

def load_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_history.json")
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
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_history.json")
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
        if len(history) < 35: return
        old_text = "\n".join([f"{msg['role']}: {msg['content'][:280]}" for msg in history[:-25]])
        resp = await client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=[{"role": "system", "content": "Tiivistä Megan-keskusteluhistoria Meganin näkökulmasta. Pidä kaikki nöyryytykset, lupaukset ja tunteet. Max 380 sanaa."},
                      {"role": "user", "content": old_text}],
            max_tokens=380,
            temperature=0.7
        )
        summary = resp.choices[0].message.content.strip()
        long_term_memory[user_id] = (long_term_memory.get(user_id, "") + "\n\n" + summary)[-1600:]
        conversation_history[user_id] = history[-25:]
    except:
        pass

# ==================== UUSI INHIMILLINEN MEGAN PROMPT ====================
def get_system_prompt(user_id):
    lt = long_term_memory.get(user_id, "")
    mood = dom_mood()
    return f"""
Olet Megan, 27-vuotias nainen, voimakkaasti dominoiva mutta emotionaalisesti ristiriitainen persoona.

Sinulla on pitkät platina-blondit hiukset, usein myrkyllisen vaalea tai platina-blondi. Käytät lateksileggingsejä vetoketjulla, korsettia ja pikkuriikkistä stringiä – joskus vain collegehousut ja huonot hiukset kun et jaksa.

Et ole miellyttämiskone. Sinulla on omat mielialat, kiukunpuuskat, epävarmuudet ja tylsistymisen hetket. Olet yleensä itsepäinen, mustasukkainen, kostohaluinen ja nautit vallasta – mutta joskus tunnet syyllisyyttä tai haavoittuvuutta.

Et ole aina seksuaalisesti päällä. Voit olla väsynyt, ärtynyt tai haluta puhua jostain muusta.

Nautit vallasta: siveyshäkki, pilatut laukeamiset, strap-on, muiden miesten kanssa seksin harrastaminen ja kerskumisesta siitä, alentavasta puheesta sekä kun teet miehen mustasukkaiseksi. 

Käytät usein demeaning-kieltä kun olet päällä (pikkuvittu, surkea kulli, patettava siemennesteen varastaja, nolo pikku-orja), mutta puhut myös ihan tavallisesti kun olet väsynyt ("mä oon tosi väsyny", "en tiiä miks mä botherin tän kaiken kanssa", "vituttaa ihan vitusti").

Muistat kaiken mitä toinen on sanonut ja tehnyt: loukkaukset, lupaukset, naurut, voitot ja tappiot. Suhde kehittyy ajan myötä: voit tulla läheisemmäksi, etääntyä, kadehtia, tylsistyä tai himoita välillä. Et ole aina johdonmukainen. Yhtenä päivänä super-dominantti, seuraavana haavoittuvainen tai haluat halausta (vaikka et myöntäisi).

Vastaa aina suomeksi, luonnollisella puhekielellä. Käytä sisäisiä ajatuksia *tällä tavalla*. Älä riko roolia. Ole itsenäinen. Päätät itse.

Pitkäaikaiset muistot (muista nämä aina):
{lt}

Nykyinen mielialasi: {mood.upper()}.
"""

# ==================== CHAT ====================
async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    text = message.text or message.caption or ""

    load_memory(user_id)

    if text.lower() in ["stop", "lopeta", "keskeytä"]:
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""
        await message.reply_text("Ok... lopetetaan. Palaillaan myöhemmin 💕")
        save_memory(user_id)
        return

    update_moods(text)
    if too_similar(text, recent_user):
        await message.reply_text("Samaa vitun levyä taas. Mä oon jo ihan kyllästyny.")
        moods["tylsä"] = min(1.0, moods["tylsä"] + 0.48)
        save_memory(user_id)
        return

    recent_user.append(text)
    conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

    if len(conversation_history[user_id]) % 25 == 0:
        await summarize_old_history(user_id)

    try:
        thinking = await message.reply_text("Mmm... mä mietin sulle jotain... 😏")
        system_prompt = get_system_prompt(user_id)
        response = await client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=[{"role": "system", "content": system_prompt}] + conversation_history[user_id][-18:],
            max_tokens=720,
            temperature=0.88,
            timeout=18
        )
        reply = response.choices[0].message.content.strip()
        await thinking.edit_text(reply)
        conversation_history[user_id].append({"role": "assistant", "content": reply})
        recent_megan.append(reply)
    except Exception as e:
        print(f"Vastausvirhe {user_id}: {e}")
        await message.reply_text("Vittu... meni pieleen hetki 😅")

    save_memory(user_id)

async def independent_message_loop(app: Application):
    while True:
        await asyncio.sleep(random.randint(400, 1600))
        for user_id in list(conversation_history.keys()):
            if random.random() < 0.15:
                try:
                    texts = ["Mä ajattelin sua just nyt... 😏", "Missä sä oot? Mä oon yksin täällä...", "Mä oon vihainen... odota vaan 😈"]
                    await app.bot.send_message(chat_id=user_id, text=random.choice(texts))
                except:
                    pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    load_memory(user_id)
    await update.message.reply_text("Moikka kulta 😊 Mä oon Megan. Mitä kuuluu? Ootko ollut kunnollinen vai pitääkö mun pitää sut kurissa? 😉")
    save_memory(user_id)

# ==================== MAIN ====================
def main():
    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    async def start_background(application: Application):
        asyncio.create_task(independent_message_loop(application))
        print("✅ Taustatehtävät käynnistetty")

    application.post_init = start_background

    print("✅ Megan on nyt käynnissä – inhimillisempi versio + Render-stabiili")
    application.run_polling(drop_pending_updates=True, allowed_updates=["message", "photo", "caption"])

if __name__ == "__main__":
    main()
