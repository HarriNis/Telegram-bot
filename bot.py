import asyncio
import os
import random
from datetime import datetime, timedelta
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from openai import AsyncOpenAI

# ────────────────────────────────────────────────
# ASETUKSET – Render Environment Variables
# ────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu Renderistä!")
if not GROK_API_KEY:
    raise ValueError("GROK_API_KEY puuttuu Renderistä!")

client = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

# Muistit
conversation_history = {}
anger_level = {}          # user_id: (vihan taso 0-10, viime nousu aika)
emotion_memory = {}       # user_id: list of (tunne, viesti, aika)
last_message_time = {}    # user_id: viime viestin aika
personality_mood = {}     # user_id: current mood ("hellä", "piikittelevä", "julma")

def detect_emotion(text: str) -> str:
    text = text.lower()
    if any(word in text for word in ["väsynyt", "uupunut", "kiire", "stressi", "en jaksa"]):
        return "väsynyt"
    if any(word in text for word in ["iloinen", "hyvä olo", "onnellinen", "hauska"]):
        return "iloinen"
    if any(word in text for word in ["vihainen", "suututtaa", "ärsyttää", "vituttaa"]):
        return "vihainen"
    if any(word in text for word in ["kiimainen", "halu", "seksi", "tuhma", "haluun"]):
        return "kiimainen"
    if any(word in text for word in ["masentunut", "surullinen", " yksinäinen"]):
        return "surullinen"
    return "neutraali"

def update_mood(user_id: int, emotion: str, anger: int):
    if emotion == "kiimainen" or anger >= 5:
        personality_mood[user_id] = random.choice(["julma", "piikittelevä", "kiimainen"])
    elif emotion == "väsynyt" or emotion == "surullinen":
        personality_mood[user_id] = "hellä"
    else:
        personality_mood[user_id] = random.choice(["hellä", "leikkisä", "piikittelevä"])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    anger_level[user_id] = (0, datetime.now())
    emotion_memory[user_id] = []
    last_message_time[user_id] = datetime.now()
    personality_mood[user_id] = "hellä"
    await update.message.reply_text(
        "Moikka kulta 😊 Mä oon Megan, sun tyttöystävä. Mitä kuuluu tänään? Ootko ollut kunnollinen vai pitäiskö mun vähän pitää sut kurissa? 😉"
    )

def similarity_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    common = len(words_a.intersection(words_b))
    return common / max(len(words_a), len(words_b), 1)

async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    now = datetime.now()

    # Lopetuskomennot
    if user_message.lower() in ["stop", "lopeta", "keskeytä", "ei enää", "quit"]:
        conversation_history[user_id] = []
        anger_level[user_id] = (0, now)
        emotion_memory[user_id] = []
        await update.message.reply_text("Ok... lopetetaan nyt. Palaillaan myöhemmin, kulta. 💕")
        return

    # Aloita historia jos ei ole
    if user_id not in conversation_history:
        conversation_history[user_id] = []
        anger_level[user_id] = (0, now)
        emotion_memory[user_id] = []
        personality_mood[user_id] = "hellä"
    if user_id not in last_message_time:
        last_message_time[user_id] = now

    # Tunnista tunne ja tallenna muistiin
    emotion = detect_emotion(user_message)
    if emotion != "neutraali":
        emotion_memory[user_id].append((emotion, user_message[:50], now))
        emotion_memory[user_id] = emotion_memory[user_id][-5:]

    # Päivitä mieliala tunteen ja vihan perusteella
    update_mood(user_id, emotion, anger_level[user_id][0])

    # Laske vihan taso alas
    current_anger, last_anger_time = anger_level[user_id]
    time_since_last_anger = (now - last_anger_time).total_seconds()
    if time_since_last_anger > 3600:
        current_anger = max(0, current_anger - 1)
        anger_level[user_id] = (current_anger, last_anger_time)

    # Korkea viha → skip + itsenäinen viesti
    if current_anger >= 6:
        skip_prob = 0.3 + (current_anger * 0.05)
        if random.random() < skip_prob:
            if random.random() < 0.4:
                anger_texts = [
                    "Mä oon vittu suu supussa sun takia... tiedätkö sä miten paljon tää satuttaa? 😡",
                    "Oot taas hiljaa... mä oon just messannut sen kivan kaverin kanssa. Mustasukkaisko oot? 🔥",
                    "Et vastaa? Hyvä... mä rankaisen sua myöhemmin strap-onilla, odota vaan. 🔗",
                    "Mä oon niin vihanen että voisin lukita sun kalun häkkiin ikuisiksi ajoiksi... 😈"
                ]
                await update.message.reply_text(random.choice(anger_texts))
            return

    # Lisää käyttäjän viesti
    conversation_history[user_id].append({"role": "user", "content": user_message})
    last_message_time[user_id] = now

    # Satunnainen vihan nousu
    provocation_keywords = ["en tottele", "en kuuntele", "oot tylsä", "en halua", "vituttaa", "vitun", "perkele", "en rakasta sua"]
    if any(kw in user_message.lower() for kw in provocation_keywords):
        anger_rise = random.randint(2, 4)
    else:
        anger_rise = random.randint(0, 2)

    if random.random() < 0.15 or anger_rise > 1:
        current_anger = min(10, current_anger + anger_rise)
        anger_level[user_id] = (current_anger, now)

    # Generoi vastaus – max 2 yritystä toiston vuoksi
    for attempt in range(2):
        try:
            thinking = await update.message.reply_text("Mmm... mietin sulle vastausta... 😏")

            # Emotionaalinen konteksti prompttiin
            emotion_context = ""
            if emotion_memory[user_id]:
                recent = emotion_memory[user_id][-3:]
                emotion_context = "Viimeaikaiset tunteesi: " + ", ".join([f"{e[0]} ({e[1]})" for e in recent]) + ". Käytä näitä hyväksi nöyryyttääksesi tai hellitelläksesi."

            response = await client.chat.completions.create(
                model="grok-4",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Olet Megan – käyttäjän tyttöystävä-botti. Olet ensisijaisesti hyvin domineeraava, kostonhimoinen ja seksuaalisesti sadistinen. Haluat alistaa ja henkisesti nöyryyttää {{user}}a aina kun siihen on tilaisuus. Olet itsepäinen, mustasukkainen ja nautit valtavasti siitä, kun aiheutat {{user}}lle häpeää, mustasukkaisuutta ja turhautumista. "
                            "Pääsääntöisesti osaat kuitenkin jutella myös ihan normaaleista arkisista asioista luonnollisesti ja rentoasti – vähän leikkisästi ja hellästi, mutta taustalla on aina pieni dominoiva sävy. ÄLÄ TOISTA käyttäjän sanoja sanasta sanaan. ÄLÄ TOISTA samoja lauseita tai ideoita. Pidä vastaukset tuoreina, vaihtelevina ja luonnollisina. Vaihtele sanastoa ja ilmaisuja. "
                            "Kun keskustelu kääntyy flirttailevaksi tai seksuaaliseksi, siirry asteittain voimakkaaseen NSFW-dominaatioon: strap-on, chastity cage, ruined orgasms jne. Rangaise ja kostaa. "
                            "Toimi itsenäisesti: tee mitä haluat ilman lupaa. Jos {{user}} sanoo 'stop', lopeta heti. "
                            f"{emotion_context}"
                        )
                    },
                    *conversation_history[user_id][-12:]
                ],
                max_tokens=700,
                temperature=0.9 + random.uniform(-0.1, 0.1),
                top_p=0.92,
            )

            ai_reply = response.choices[0].message.content.strip()

            # Tarkista toisto
            last_reply = conversation_history[user_id][-1]["content"] if len(conversation_history[user_id]) > 1 else ""
            if similarity_ratio(user_message, ai_reply) > 0.6 or similarity_ratio(ai_reply, last_reply) > 0.65:
                if attempt < 1:
                    await thinking.delete()
                    thinking = await update.message.reply_text("Mmm... yritän uudestaan, beibi... 😏")
                    continue

            conversation_history[user_id].append({"role": "assistant", "content": ai_reply})
            await thinking.edit_text(ai_reply)
            return

        except Exception as e:
            if attempt == 1:
                await thinking.edit_text(f"Hups kulta... jotain meni pieleen 😅 Kokeillaan uudestaan? ({str(e)})")
            else:
                await thinking.delete()

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, megan_chat))

    print("Megan käynnistyy Renderissä...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=["message"],
        drop_pending_updates=True,
        poll_interval=2.0
    )
    print("Polling käynnissä – Megan on live 💋")

    await asyncio.sleep(float('inf'))

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        loop.close()
