import asyncio
import os
import random
import json
from datetime import datetime
from collections import deque
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from openai import AsyncOpenAI

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")

if not TELEGRAM_TOKEN or not GROK_API_KEY:
    raise ValueError("TELEGRAM_TOKEN tai GROK_API_KEY puuttuu Renderistä!")

client = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

print("🚀 Megan käynnistyy – pitkäaikainen muisti + Render-fix")

# ==================== MEGANIN TUNNELMAT ====================
recent_user = deque(maxlen=15)
recent_megan = deque(maxlen=15)
mood_history = deque(maxlen=8)

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
    for k in moods: moods[k] += (0.5 - moods[k]) * 0.055

def dom_mood(): 
    return max(moods, key=moods.get)

def too_similar(t, hist):
    t = t.lower().strip()
    for o in hist:
        o = o.lower().strip()
        if len(t)>6 and (o.startswith(t[:6]) or t.startswith(o[:6])): 
            return True
        if len(set(t.split()) & set(o.split())) > 5 and abs(len(t.split()) - len(o.split())) < 6: 
            return True
    return False

# ==================== PITKÄAIKAINEN MUISTI ====================
long_term_memory = {}

# ==================== TELEGRAM MUISTI ====================
conversation_history = {}
anger_level = {}
emotion_memory = {}
last_message_time = {}
personality_mood = {}

MEMORY_DIR = "/tmp/megan_memory"
os.makedirs(MEMORY_DIR, exist_ok=True)

naughty_prompts = [
    "Dominant woman in black latex outfit with strap-on, teasing pose in a dark room, seductive lighting, high detail, realistic",
    "Sadistic mistress holding chastity device, wearing leather and boots, smirking at camera, dim lit dungeon background, ultra detailed",
    "Female dominatrix with whip and strap-on, posing aggressively, red latex corset, foggy atmosphere, high resolution",
]

def load_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_history.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                conversation_history[user_id] = data.get("history", [])
                anger_level[user_id] = (data.get("anger", [0])[0], datetime.fromisoformat(data.get("anger", [0, datetime.now().isoformat()])[1]))
                emotion_memory[user_id] = [(e[0], e[1], datetime.fromisoformat(e[2])) for e in data.get("emotions", [])]
                personality_mood[user_id] = data.get("mood", "hellä")
                last_message_time[user_id] = datetime.fromisoformat(data.get("last_time", datetime.now().isoformat()))
                long_term_memory[user_id] = data.get("long_term", "")
        except Exception as e:
            print(f"Muistin latausvirhe {user_id}: {e}")
    else:
        conversation_history[user_id] = []
        anger_level[user_id] = (0, datetime.now())
        emotion_memory[user_id] = []
        personality_mood[user_id] = "hellä"
        last_message_time[user_id] = datetime.now()
        long_term_memory[user_id] = ""

def save_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_history.json")
    try:
        data = {
            "history": conversation_history.get(user_id, [])[-25:],
            "anger": [anger_level[user_id][0], anger_level[user_id][1].isoformat()],
            "emotions": [[e[0], e[1], e[2].isoformat()] for e in emotion_memory.get(user_id, [])[-10:]],
            "mood": personality_mood.get(user_id, "hellä"),
            "last_time": last_message_time[user_id].isoformat(),
            "long_term": long_term_memory.get(user_id, "")
        }
        with open(file_path, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Tallennusvirhe {user_id}: {e}")

def get_system_prompt(user_id):
    lt = long_term_memory.get(user_id, "")
    mood = dom_mood()
    return f"""
Olet Megan, 27-vuotias dominoiva blondi tyttöystävä.

Pitkäaikaiset muistot:
{lt}

Nykyinen mielialasi: {mood.upper()}.
Vastaa aina suomeksi luonnollisesti.
"""

async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    text = message.text or message.caption or ""

    load_memory(user_id)
    update_moods(text)

    recent_user.append(text)
    conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

    try:
        thinking = await message.reply_text("Mmm... mietin 😏")
        response = await client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=[{"role": "system", "content": get_system_prompt(user_id)}] + conversation_history[user_id][-18:],
            max_tokens=720,
            temperature=0.88,
            timeout=30
        )
        reply = response.choices[0].message.content.strip()
        await thinking.edit_text(reply)

        conversation_history[user_id].append({"role": "assistant", "content": reply})

    except Exception as e:
        print(e)
        await message.reply_text("Virhe hetki 😅")

    save_memory(user_id)

async def independent_message_loop(app: Application):
    while True:
        await asyncio.sleep(random.randint(400, 1600))
        for user_id in list(conversation_history.keys()):
            try:
                await app.bot.send_message(chat_id=user_id, text="Hei… muistitko mut? 😈")
            except:
                pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    load_memory(user_id)
    await update.message.reply_text("Moikka 😊")

# ==================== MAIN FIX ====================
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT | filters.CAPTION | filters.PHOTO, megan_chat))

    async def start_background(application: Application):
        application.create_task(independent_message_loop(application))

    app.post_init = start_background

    print("✅ Megan toimii Renderissä")

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "photo", "caption"]
    )

if __name__ == "__main__":
    main()
