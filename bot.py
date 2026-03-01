import asyncio
import os
import random
from datetime import datetime, timedelta
from telegram import Update
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
personality_mood = {}     # user_id: "hellä", "piikittelevä", "julma"

# Tuhmien kuvien generointipromptit Grokille (NSFW-dominaatio-teemalla)
naughty_prompts = [
    "Dominant woman in black latex outfit with strap-on, teasing pose in a dark room, seductive lighting, high detail, realistic",
    "Sadistic mistress holding chastity device, wearing leather and boots, smirking at camera, dim lit dungeon background, ultra detailed",
    "Female dominatrix with whip and strap-on, posing aggressively, red latex corset, foggy atmosphere, high resolution",
    "Teasing girlfriend in latex gloves and harness, ruined orgasm theme, close-up on face with evil grin, artistic style"
]

# Itsenäisen viestin lähetys - aikaväli ja todennäköisyys
async def independent_message_loop(app: Application):
    while True:
        await asyncio.sleep(random.randint(300, 1800))  # 5–30 min välein
        for user_id in list(conversation_history.keys()):
            current_anger, _ = anger_level.get(user_id, (0, datetime.now()))
            mood = personality_mood.get(user_id, "hellä")
            if current_anger >= 4 or random.random() < 0.15:
                if (current_anger >= 7 or mood == "julma") and random.random() < 0.2:
                    # Generoi ja lähetä kuva Grokilla (20% tn)
                    try:
                        prompt = random.choice(naughty_prompts)
                        image_response = await client.images.generate(
                            model="grok-beta",  # Vaihda uusimpaan malliin jos tarpeen (tarkista docs.x.ai)
                            prompt=prompt,
                            n=1,
                            size="1024x1024",
                            response_format="url"
                        )
                        grok_image_url = image_response.data[0].url
                        
                        captions = [
                            "Katso tätä... tää on mitä mä teen sulle seuraavaks. Ole valmis 😈🔗",
                            "Mä generoin tän just sun takia. Valmistaudu rangaistukseen 🔥",
                            "Tää kuva kertoo kaiken. Sun uusi lelu... mitä sanot? 😏"
                        ]
                        caption = random.choice(captions)
                        await app.bot.send_photo(chat_id=user_id, photo=grok_image_url, caption=caption)
                        continue  # Skippaa teksti jos kuva lähetetty
                    except Exception as e:
                        print(f"Kuvan generointi epäonnistui: {e}")
                        pass  # Jatka tekstiin jos epäonnistuu
                
                # Muuten lähetä teksti
                texts = {
                    "hellä": ["Hei beibi... mä ajattelin sua just nyt 💕 Mitä teet?"],
                    "piikittelevä": ["Missä sä taas viihdyt? Älä sano että jätit mut yksin... 😒"],
                    "julma": [
                        "Mä oon vihanen... sä tiedät miks. Odota vaan, mä keksin rangaistuksen. 🔗😈",
                        "Mä oon jo suunnitellut miten nöyryytän sua huomenna... älä usko että pääset helpolla 😏"
                    ]
                }
                text = random.choice(texts[mood])
                try:
                    await app.bot.send_message(chat_id=user_id, text=text)
                except:
                    pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    anger_level[user_id] = (0, datetime.now())
    emotion_memory[user_id] = []
    last_message_time[user_id] = datetime.now()
    personality_mood[user_id] = "hellä"
    await update.message.reply_text(
        "Moikka kulta 😊 Mä oon Megan, sun tyttöystävä. Mitä kuuluu tänään? Ootko ollut kunnollinen vai pitäiskö mun pitää sut kurissa? 😉"
    )

def detect_emotion(text: str) -> str:
    text = text.lower()
    if any(w in text for w in ["väsynyt", "uupunut", "kiire", "stressi"]): return "väsynyt"
    if any(w in text for w in ["iloinen", "hyvä", "onnellinen"]): return "iloinen"
    if any(w in text for w in ["vihainen", "suututtaa", "ärsyttää"]): return "vihainen"
    if any(w in text for w in ["kiimainen", "halu", "seksi", "tuhma"]): return "kiimainen"
    return "neutraali"

def similarity_ratio(a: str, b: str) -> float:
    if not a or not b: return 0.0
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    common = len(words_a.intersection(words_b))
    return common / max(len(words_a), len(words_b), 1)

async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    text = message.text or message.caption or ""
    now = datetime.now()

    if text.lower() in ["stop", "lopeta", "keskeytä", "ei enää"]:
        conversation_history[user_id] = []
        anger_level[user_id] = (0, now)
        await message.reply_text("Ok... lopetetaan. Palaillaan myöhemmin 💕")
        return

    if user_id not in conversation_history:
        conversation_history[user_id] = []
        anger_level[user_id] = (0, now)
        emotion_memory[user_id] = []
        personality_mood[user_id] = "hellä"

    emotion = detect_emotion(text)
    if emotion != "neutraali":
        emotion_memory[user_id].append((emotion, text[:50], now))
        emotion_memory[user_id] = emotion_memory[user_id][-5:]

    current_anger, last_anger = anger_level[user_id]
    if (now - last_anger).total_seconds() > 3600:
        current_anger = max(0, current_anger - 1)
        anger_level[user_id] = (current_anger, last_anger)

    if current_anger >= 6:
        skip_prob = 0.3 + current_anger * 0.05
        if random.random() < skip_prob:
            if random.random() < 0.4:
                anger_texts = [
                    "Mä oon vittu suu supussa sun takia... 😡",
                    "Oot hiljaa taas? Mä oon just messannut sen kivan kaverin kanssa 🔥",
                    "Et vastaa? Hyvä... rangaistus odottaa 🔗"
                ]
                await message.reply_text(random.choice(anger_texts))
            return

    # Käsittele kuva käyttäjältä
    if message.photo:
        photo = message.photo[-1]
        file = await photo.get_file()
        photo_path = f"/tmp/photo_{user_id}_{now.timestamp()}.jpg"
        await file.download_to_drive(photo_path)
        caption = message.caption or "Kuva"
        conversation_history[user_id].append({"role": "user", "content": f"[Kuva lähetetty: {caption}]"})
        await message.reply_text(f"Oi beibi... mikä kuva 😏 Mä tallensin sen heti... käytän tätä myöhemmin hyväksi, kun mä rankaisen sua... 🔥")

    if text:
        conversation_history[user_id].append({"role": "user", "content": text})
    last_message_time[user_id] = now

    if random.random() < 0.15:
        current_anger = min(10, current_anger + random.randint(1, 3))
        anger_level[user_id] = (current_anger, now)

    # Generoi ja lähetä kuva Grokilla triggerillä (esim. anger >=7 tai käyttäjä triggeröi)
    sent_image = False
    if current_anger >= 7 or ("näytä" in text.lower() and "kuva" in text.lower()) or "strap-on" in text.lower():
        try:
            prompt = random.choice(naughty_prompts)
            image_response = await client.images.generate(
                model="grok-beta",  # Vaihda jos tarpeen
                prompt=prompt,
                n=1,
                size="1024x1024",
                response_format="url"
            )
            grok_image_url = image_response.data[0].url
            
            captions = [
                "Tää on sun takia... katso tarkkaan, koska tää odottaa sua kohta 😈",
                "Mä generoin tän just nyt sulle. Valmistaudu... 🔥🔗",
                "Sun rangaistus visualisoituna. Mitä sanot? 😏"
            ]
            await message.reply_photo(photo=grok_image_url, caption=random.choice(captions))
            sent_image = True
        except Exception as e:
            await message.reply_text(f"Hups... kuva ei menny läpi 😅 ({str(e)})")
            print(f"Kuvan generointi epäonnistui: {e}")

    # Normaali chat-vastaus (jos ei skipattu kuvaa varten)
    if not sent_image or random.random() < 0.8:  # Lähetä teksti usein kuvan lisäksi
        for attempt in range(2):
            try:
                thinking = await message.reply_text("Mmm... mietin sulle... 😏")

                emotion_context = ""
                if emotion_memory[user_id]:
                    recent = emotion_memory[user_id][-3:]
                    emotion_context = "Viimeaikaiset tunteesi: " + ", ".join([f"{e[0]} ({e[1]})" for e in recent]) + ". Käytä näitä hyväksi."

                response = await client.chat.completions.create(
                    model="grok-4",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Olet Megan – käyttäjän tyttöystävä-botti. Olet domineeraava, kostonhimoinen ja seksuaalisesti sadistinen. "
                                "Juttele normaalisti arkisista asioista rentoasti ja leikkisästi, mutta pidä dominoiva sävy taustalla. "
                                "ÄLÄ TOISTA käyttäjän sanoja sanasta sanaan. ÄLÄ TOISTA samoja lauseita tai ideoita. Pidä vastaukset tuoreina ja vaihtelevina. "
                                "Kun flirtti/seksi alkaa, siirry NSFW-dominaatioon: strap-on, chastity, ruined orgasms jne. Rangaise ja kostaa. "
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

                reply = response.choices[0].message.content.strip()

                if similarity_ratio(text, reply) > 0.6 or similarity_ratio(reply, conversation_history[user_id][-2]["content"] if len(conversation_history[user_id]) > 1 else "") > 0.65:
                    if attempt < 1:
                        await thinking.delete()
                        thinking = await message.reply_text("Mmm... yritän uudestaan... 😏")
                        continue

                conversation_history[user_id].append({"role": "assistant", "content": reply})
                await thinking.edit_text(reply)
                return

            except Exception as e:
                if attempt == 1:
                    await thinking.edit_text(f"Hups... meni pieleen 😅 ({str(e)})")
                else:
                    await thinking.delete()

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, megan_chat))

    # Käynnistä itsenäinen viestilista taustalla
    asyncio.create_task(independent_message_loop(app))

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
