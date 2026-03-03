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

# --- 1. RENDERIN VAATIMA DUMMY-PALVELIN ---
# Tämä estää "Port scan timeout" -virheen ilmaisversiossa
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Megan is active and dominant.", 200

def run_flask():
    # Render antaa portin ympäristömuuttujana, oletus 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- 2. ASETUKSET JA MUUTTUJAT ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")

if not TELEGRAM_TOKEN or not GROK_API_KEY:
    raise ValueError("TELEGRAM_TOKEN tai GROK_API_KEY puuttuu!")

# Huom: grok-4-1-fast-reasoning ei välttämättä ole vielä tuettu, 
# jos tulee virhe, vaihda tilalle "grok-2-1212" tai "grok-beta"
client = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

recent_user = deque(maxlen=15)
recent_megan = deque(maxlen=15)
conversation_history = {}
long_term_memory = {}
last_message_time = {} # Korjattu: Lisätty puuttuva sanakirja

moods = {"kiukku":0.45, "halu":0.65, "tylsä":0.28, "mustas":0.42, "iva":0.72, "väsy":0.35, "syyllisyys":0.18}

# --- 3. APUFUNKTIOT ---
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
    for k in moods: moods[k] = max(0.05, min(1.0, moods[k] + (0.5 - moods[k]) * 0.055))

def dom_mood(): return max(moods, key=moods.get)

def too_similar(t, hist):
    t = t.lower().strip()
    for o in list(hist):
        o = o.lower().strip()
        if len(t)>6 and (o.startswith(t[:6]) or t.startswith(o[:6])): return True
    return False

MEMORY_DIR = "/tmp/megan_memory"
os.makedirs(MEMORY_DIR, exist_ok=True)

def load_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_history.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                conversation_history[user_id] = data.get("history", [])
                long_term_memory[user_id] = data.get("long_term", "")
        except: pass
    else:
        conversation_history[user_id] = []
        long_term_memory[user_id] = ""

def save_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_history.json")
    try:
        data = {"history": conversation_history.get(user_id, [])[-25:], "long_term": long_term_memory.get(user_id, "")}
        with open(file_path, 'w') as f: json.dump(data, f)
    except: pass

async def summarize_old_history(user_id):
    try:
        history = conversation_history.get(user_id, [])
        if len(history) < 35: return
        old_text = "\n".join([f"{msg['role']}: {msg['content'][:200]}" for msg in history[:-25]])
        resp = await client.chat.completions.create(
            model="grok-beta", # Käytetään varmempaa mallinimeä
            messages=[{"role": "system", "content": "Tiivistä Meganin näkökulmasta. Max 300 sanaa."},
                      {"role": "user", "content": old_text}],
            max_tokens=300
        )
        summary = resp.choices[0].message.content.strip()
        long_term_memory[user_id] = (long_term_memory.get(user_id, "") + "\n\n" + summary)[-1500:]
        conversation_history[user_id] = history[-25:]
    except: pass

def get_system_prompt(user_id):
    lt = long_term_memory.get(user_id, "")
    mood = dom_mood()
    return f"Olet Megan, dominoiva blondi. Mieliala: {mood}. Muistot: {lt}. Vastaa suomeksi puhekielellä, ole tuhma ja alistava."

# --- 4. VIESTINKÄSITTELY ---
async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    text = update.message.text or update.message.caption or ""

    load_memory(user_id)
    last_message_time[user_id] = datetime.now()

    if text.lower() in ["stop", "lopeta"]:
        await update.message.reply_text("Ok... lopetetaan. 💕")
        return

    update_moods(text)
    if too_similar(text, recent_user):
        await update.message.reply_text("Samaa levyä taas. Huoh.")
        return

    recent_user.append(text)
    conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

    try:
        thinking = await update.message.reply_text("Mmm... 😏")
        response = await client.chat.completions.create(
            model="grok-beta", 
            messages=[{"role": "system", "content": get_system_prompt(user_id)}] + conversation_history[user_id][-15:],
            max_tokens=500
        )
        reply = response.choices[0].message.content.strip()
        await thinking.edit_text(reply)
        conversation_history[user_id].append({"role": "assistant", "content": reply})
        save_memory(user_id)
    except Exception as e:
        print(f"Error: {e}")
        await update.message.reply_text("Nyt tuli joku virhe... kokeillaan kohta uusiks.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Moikka kulta 😊 Megan täällä.")

async def independent_message_loop(app: Application):
    while True:
        await asyncio.sleep(random.randint(600, 1800))
        # Itsenäiset viestit tähän...

# --- 5. KÄYNNISTYS (RENDER-YHTEENSOPIVA) ---
async def post_init(application: Application):
    asyncio.create_task(independent_message_loop(application))

def main():
    # Käynnistetään Flask omassa säikeessään
    threading.Thread(target=run_flask, daemon=True).start()

    # Rakennetaan Telegram-sovellus
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))
    
    application.post_init = post_init

    print("🚀 Megan on käynnissä!")
    # run_polling() hoitaa event loopin oikein itse
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
