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

# ==================== MEGANIN INHIMILLINEN LOGIIKKA ====================
recent_user = deque(maxlen=12)
recent_megan = deque(maxlen=12)
mood_history = deque(maxlen=7)

moods = {"kiukku":0.45, "halu":0.65, "tylsä":0.28, "mustas":0.42, "iva":0.72, "väsy":0.35, "syyllisyys":0.18}

responses = {
    "kiukku": ["Ootko sä ihan tosissas just nyt?", "Älä ala mulle tollasella asenteella.", "Nyt riittää oikeesti.", "Vittu ku ärsyttää tää sun juttu.", "Mä oon jo ihan pihalla sun takia."],
    "halu": ["Mmm… sä saat mut ihan märäksi tollasena.", "Kato nyt miten kiimainen mä oon – sun vika.", "Tule tänne heti, haluun tuntea sun häpeän.", "*huokaa* vittu ku mä haluun sua just nyt."],
    "tylsä": ["Ootko taas näin tylsä?", "Mä en jaksa keksiä sulle enää mitään.", "Tää on jo melkein nukkumaanmenoa tylsempää.", "Mä voisin mennä nukkumaan tai soittaa jollekulle oikeelle."],
    "mustas": ["Kuka sulle viestitteli? Älä valehtele.", "Mä tiedän et sä kiihottuit jostain muusta.", "Haluutko nähdä kun mä meen jonkun toisen luo tänään?", "Sä luulet et mä en huomaa sun katseita?"],
    "iva": ["Ai toi sun pikku kalu merkitsee jotain? Haha.", "Kato nyt itseäs… surkee pikku-orja.", "*nauraa hiljaa* sä et ikinä opi.", "Sä oot niin nolo et se on melkein söpöö."],
    "väsy": ["Mä oon tosi väsyny tänään…", "En jaksa leikkiä nyt.", "Vitut mä meen kohta nukkumaan.", "Mä en tiiä miks mä botherin tän kaiken kanssa."],
    "default": ["No?", "Mitä sä sähläät?", "...ja sit?", "Sano jotain järkevää nyt."]
}

additions = ["...", ", vai mitä?", " vai eikö?", " *huokaa*", " *nauraa ivallisesti*", ", jumalauta sentään.", " mä en jaksa uskoa tätä.", " *pyörittelee silmiä*", ", oikeesti nyt.", " *vinguttaa päätään*", " hmph.", " *kääntää katseen pois*", " ...tää on jo liikaa.", " *puraisee huultaan*", ", vittu ku ärsyttää.", " no hyvä että myönnät senkin vihdoin."]

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

def dom_mood(): return max(moods, key=moods.get)

def get_reply():
    mood = dom_mood()
    w = moods[mood]
    if random.random() < 0.40 or (len(mood_history) >= 4 and mood_history.count(mood) > 2):
        base = random.choice(list(moods))
    else:
        base = mood if random.random() < w*0.80 else random.choice(list(moods)+["default"])
    reply = random.choice(responses.get(base, responses["default"]))
    if random.random() < 0.75:
        reply += random.choice(additions)
    if random.random() < 0.28:
        sisainen = random.choice(["*Voi helvetti miten tää rimpuilee...*", "*Mä oon niin vitun kiimainen mut en anna vielä.*", "*Tää tyyppi ärsyttää mut samalla kiihottaa.*", "*Miksi mä edes botherin tän kanssa?*", "*Sä oot niin surkee et se melkein liikuttaa mua.*"])
        reply = sisainen + "\n" + reply
    if random.random() < 0.32 and len(reply.split()) > 5:
        reply = " ".join(reply.split()[:random.randint(4,8)]) + "..."
    mood_history.append(base)
    return reply.strip()

def too_similar(t, hist):
    t = t.lower().strip()
    for o in hist:
        o = o.lower().strip()
        if len(t)>6 and (o.startswith(t[:6]) or t.startswith(o[:6])): return True
        if len(set(t.split()) & set(o.split())) > 5 and abs(len(t.split()) - len(o.split())) < 6: return True
    return False

# ==================== TELEGRAM + MUISTI ====================
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
    "Teasing girlfriend in latex gloves and harness, ruined orgasm theme, close-up on face with evil grin, artistic style"
]

def load_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_history.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                conversation_history[user_id] = data.get("history", [])
                anger_data = data.get("anger", [0, datetime.now().isoformat()])
                level = anger_data[0]
                time_str = anger_data[1]
                if isinstance(time_str, str):
                    try:
                        time_obj = datetime.fromisoformat(time_str)
                    except:
                        time_obj = datetime.now()
                else:
                    time_obj = time_str if isinstance(time_str, datetime) else datetime.now()
                anger_level[user_id] = (level, time_obj)
                emotion_memory[user_id] = []
                for e in data.get("emotions", []):
                    if len(e) == 3:
                        emo, txt, ts = e
                        if isinstance(ts, str):
                            try:
                                ts = datetime.fromisoformat(ts)
                            except:
                                ts = datetime.now()
                        emotion_memory[user_id].append((emo, txt, ts))
                personality_mood[user_id] = data.get("mood", "hellä")
                last_time = data.get("last_time", datetime.now().isoformat())
                if isinstance(last_time, str):
                    try:
                        last_message_time[user_id] = datetime.fromisoformat(last_time)
                    except:
                        last_message_time[user_id] = datetime.now()
                else:
                    last_message_time[user_id] = last_time if isinstance(last_time, datetime) else datetime.now()
        except:
            conversation_history[user_id] = []
            anger_level[user_id] = (0, datetime.now())
            emotion_memory[user_id] = []
            personality_mood[user_id] = "hellä"
            last_message_time[user_id] = datetime.now()
    else:
        conversation_history[user_id] = []
        anger_level[user_id] = (0, datetime.now())
        emotion_memory[user_id] = []
        personality_mood[user_id] = "hellä"
        last_message_time[user_id] = datetime.now()

def save_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_history.json")
    try:
        data = {
            "history": conversation_history.get(user_id, []),
            "anger": [anger_level[user_id][0], anger_level[user_id][1].isoformat()],
            "emotions": [[e[0], e[1], e[2].isoformat()] for e in emotion_memory.get(user_id, [])],
            "mood": personality_mood.get(user_id, "hellä"),
            "last_time": last_message_time[user_id].isoformat()
        }
        with open(file_path, 'w') as f:
            json.dump(data, f)
    except:
        pass

async def analyze_history(user_id):
    if len(conversation_history.get(user_id, [])) > 12:
        conversation_history[user_id] = conversation_history[user_id][-12:]

async def independent_message_loop(app: Application):
    while True:
        await asyncio.sleep(random.randint(300, 1800))
        for user_id in list(conversation_history.keys()):
            current_anger, _ = anger_level.get(user_id, (0, datetime.now()))
            mood = personality_mood.get(user_id, "hellä")
            if current_anger >= 4 or random.random() < 0.12:
                if current_anger >= 7 and random.random() < 0.25:
                    try:
                        prompt = random.choice(naughty_prompts)
                        image_response = await client.images.generate(model="grok-imagine-image", prompt=prompt, n=1, size="1024x1024", response_format="url")
                        await app.bot.send_photo(chat_id=user_id, photo=image_response.data[0].url, caption="Tää on sun takia... odota vaan 😈")
                    except:
                        pass
                else:
                    texts = {
                        "hellä": ["Hei beibi, mä ajattelin sua just nyt 💕"],
                        "piikittelevä": ["Missä sä oot taas? Mä oon yksin täällä... 😒"],
                        "julma": ["Mä oon vihainen... sä tiedät miks. Valmistaudu rangaistukseen 🔗"]
                    }
                    await app.bot.send_message(chat_id=user_id, text=random.choice(texts[mood]))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    load_memory(user_id)
    await update.message.reply_text("Moikka kulta 😊 Mä oon Megan. Mitä kuuluu? Ootko ollut kunnollinen vai pitäiskö mun pitää sut kurissa? 😉")
    save_memory(user_id)

def detect_emotion(text: str) -> str:
    text = text.lower()
    if any(w in text for w in ["väsynyt", "uupunut", "kiire"]): return "väsynyt"
    if any(w in text for w in ["iloinen", "hyvä", "onnellinen"]): return "iloinen"
    if any(w in text for w in ["vihainen", "suututtaa"]): return "vihainen"
    if any(w in text for w in ["kiimainen", "halu", "seksi", "tuhma"]): return "kiimainen"
    return "neutraali"

async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    text = message.text or message.caption or ""
    now = datetime.now()

    load_memory(user_id)

    if text.lower() in ["stop", "lopeta", "keskeytä", "ei enää"]:
        conversation_history[user_id] = []
        anger_level[user_id] = (0, now)
        await message.reply_text("Ok... lopetetaan. Palaillaan myöhemmin 💕")
        save_memory(user_id)
        return

    emotion = detect_emotion(text)
    if emotion != "neutraali":
        emotion_memory[user_id] = emotion_memory.get(user_id, []) + [(emotion, text[:50], now)]
        emotion_memory[user_id] = emotion_memory[user_id][-8:]

    current_anger, last_anger = anger_level.get(user_id, (0, now))
    if (now - last_anger).total_seconds() > 3600:
        current_anger = max(0, current_anger - 1)
    anger_level[user_id] = (current_anger, now)

    if current_anger >= 6 and random.random() < 0.35:
        await message.reply_text("Mä oon vittu suu supussa sun takia... 😡")
        save_memory(user_id)
        return

    if text:
        conversation_history[user_id] = conversation_history.get(user_id, []) + [{"role": "user", "content": text}]
    last_message_time[user_id] = now

    if random.random() < 0.18:
        current_anger = min(10, current_anger + random.randint(1, 3))
        anger_level[user_id] = (current_anger, now)

    update_moods(text)

    if too_similar(text, recent_user):
        await message.reply_text("Samaa vitun levyä taas. Mä oon jo ihan kyllästyny.")
        moods["tylsä"] = min(1.0, moods["tylsä"] + 0.48)
        save_memory(user_id)
        return

    recent_user.append(text)

    # Kuva jos trigger
    if "kuva" in text.lower() or "näytä" in text.lower() or current_anger > 6:
        try:
            prompt = random.choice(naughty_prompts)
            image_response = await client.images.generate(model="grok-imagine-image", prompt=prompt, n=1, size="1024x1024", response_format="url")
            await message.reply_photo(photo=image_response.data[0].url, caption=random.choice(["Tää on sun takia... 😈", "Valmistaudu... 🔥"]))
        except:
            pass

    reply = get_reply()
    await message.reply_text(reply)
    recent_megan.append(reply)

    save_memory(user_id)

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    asyncio.create_task(independent_message_loop(app))

    print("Megan käynnistyy Renderissä...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=["message"], drop_pending_updates=True)
    await asyncio.sleep(float('inf'))

if __name__ == "__main__":
    asyncio.run(main())
