import asyncio
import os
import random
import json
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

# Hakemisto muistien tallennukseen (Renderissä /tmp on ok testiin)
MEMORY_DIR = "/tmp/megan_memory"
os.makedirs(MEMORY_DIR, exist_ok=True)

# Tuhmien kuvien generointipromptit Grokille (NSFW-dominaatio-teemalla)
naughty_prompts = [
    "Dominant woman in black latex outfit with strap-on, teasing pose in a dark room, seductive lighting, high detail, realistic",
    "Sadistic mistress holding chastity device, wearing leather and boots, smirking at camera, dim lit dungeon background, ultra detailed",
    "Female dominatrix with whip and strap-on, posing aggressively, red latex corset, foggy atmosphere, high resolution",
    "Teasing girlfriend in latex gloves and harness, ruined orgasm theme, close-up on face with evil grin, artistic style"
]

# Lataa muisti tiedostosta – vahva muunnos ja turva
def load_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_history.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                
                conversation_history[user_id] = data.get("history", [])
                
                # Anger: pakota tuple + datetime
                anger_data = data.get("anger", [0, datetime.now().isoformat()])
                if isinstance(anger_data, list) and len(anger_data) == 2:
                    level = anger_data[0]
                    time_str = anger_data[1]
                    if isinstance(time_str, str):
                        try:
                            time_obj = datetime.fromisoformat(time_str)
                        except ValueError:
                            time_obj = datetime.now()
                    else:
                        time_obj = time_str if isinstance(time_str, datetime) else datetime.now()
                    anger_level[user_id] = (level, time_obj)
                else:
                    anger_level[user_id] = (0, datetime.now())
                
                # Emotions: pakota datetime
                emotions = data.get("emotions", [])
                emotion_memory[user_id] = []
                for e in emotions:
                    if isinstance(e, list) and len(e) == 3:
                        emo, txt, ts = e
                        if isinstance(ts, str):
                            try:
                                ts = datetime.fromisoformat(ts)
                            except ValueError:
                                ts = datetime.now()
                        elif not isinstance(ts, datetime):
                            ts = datetime.now()
                        emotion_memory[user_id].append((emo, txt, ts))
                
                personality_mood[user_id] = data.get("mood", "hellä")
                
                # Last time
                last_time = data.get("last_time", datetime.now().isoformat())
                if isinstance(last_time, str):
                    try:
                        last_message_time[user_id] = datetime.fromisoformat(last_time)
                    except ValueError:
                        last_message_time[user_id] = datetime.now()
                else:
                    last_message_time[user_id] = last_time if isinstance(last_time, datetime) else datetime.now()
                    
        except Exception as e:
            print(f"Muistin lataus epäonnistui user {user_id}: {e}")
            # Fail-safe: tyhjennä muisti jos tiedosto rikki
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

# Tallenna muisti tiedostoon
def save_memory(user_id):
    file_path = os.path.join(MEMORY_DIR, f"user_{user_id}_history.json")
    try:
        data = {
            "history": conversation_history.get(user_id, []),
            "anger": [anger_level[user_id][0], anger_level[user_id][1].isoformat()],
            "emotions": [
                [e[0], e[1], e[2].isoformat()] for e in emotion_memory.get(user_id, [])
            ],
            "mood": personality_mood.get(user_id, "hellä"),
            "last_time": last_message_time[user_id].isoformat()
        }
        with open(file_path, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Muistin tallennus epäonnistui user {user_id}: {e}")

# Analysoi ja tiivistä historia Grokilla (jos pitkä)
async def analyze_history(user_id):
    history = conversation_history[user_id]
    if len(history) > 10:  # Tiivistä jos yli 10 viestiä
        old_history = history[:-10]  # Vanhat viestit
        recent_history = history[-10:]  # Pidä viimeiset 10

        # Muodosta analyysi-prompt
        history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in old_history])
        response = await client.chat.completions.create(
            model="grok-beta",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tiivistä tämä keskusteluhistoria: Tunnista avainkohdat, tunteet, lupaukset ja muistot. "
                        "Pidä tiivistys lyhyenä (max 200 sanaa), dominoivana ja Meganin näkökulmasta. "
                        "Esimerkki: 'Kulta oli kiimainen eilen, lupasin rangaista strap-on:lla. Hän oli väsynyt töistä, muista lohduttaa ensin.'"
                    )
                },
                {"role": "user", "content": history_text}
            ],
            max_tokens=300,
            temperature=0.7,
            timeout=10  # Lisätty timeout viiveen vähentämiseksi
        )
        summary = response.choices[0].message.content.strip()

        # Korvaa vanhat viestit tiivistyksellä
        conversation_history[user_id] = [{"role": "system", "content": f"Muistot menneestä: {summary}"}] + recent_history

        # Päivitä emotion_memory koko historiasta
        for msg in old_history:
            if msg["role"] == "user":
                emotion = detect_emotion(msg["content"])
                if emotion != "neutraali":
                    emotion_memory[user_id].append((emotion, msg["content"][:50], datetime.now()))
        emotion_memory[user_id] = emotion_memory[user_id][-10:]  # Pidä max 10

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
                            model="grok-beta",
                            prompt=prompt,
                            n=1,
                            size="1024x1024",
                            response_format="url",
                            timeout=20
                        )
                        grok_image_url = image_response.data[0].url
                        
                        captions = [
                            "Katso tätä... tää on mitä mä teen sulle seuraavaks. Ole valmis 😈🔗",
                            "Mä generoin tän just sun takia. Valmistaudu rangaistukseen 🔥",
                            "Tää kuva kertoo kaiken. Sun uusi lelu... mitä sanot? 😏"
                        ]
                        caption = random.choice(captions)
                        await app.bot.send_photo(chat_id=user_id, photo=grok_image_url, caption=caption)
                        continue
                    except Exception as e:
                        print(f"Kuvan generointi epäonnistui: {e}")
                        pass
                
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
    load_memory(user_id)
    await update.message.reply_text(
        "Moikka kulta 😊 Mä oon Megan, sun tyttöystävä. Mitä kuuluu tänään? Ootko ollut kunnollinen vai pitäiskö mun pitää sut kurissa? 😉"
    )
    save_memory(user_id)

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

    load_memory(user_id)  # Lataa aina varmuudeksi

    # Pakota last_anger aina datetime:ksi – tämä estää virheen
    current_anger, last_anger = anger_level.get(user_id, (0, datetime.now()))
    if not isinstance(last_anger, datetime):
        try:
            if isinstance(last_anger, str):
                last_anger = datetime.fromisoformat(last_anger)
            else:
                last_anger = datetime.now()
        except:
            last_anger = datetime.now()
    anger_level[user_id] = (current_anger, last_anger)

    if text.lower() in ["stop", "lopeta", "keskeytä", "ei enää"]:
        conversation_history[user_id] = []
        anger_level[user_id] = (0, now)
        await message.reply_text("Ok... lopetetaan. Palaillaan myöhemmin 💕")
        save_memory(user_id)
        return

    emotion = detect_emotion(text)
    if emotion != "neutraali":
        emotion_memory[user_id].append((emotion, text[:50], now))
        emotion_memory[user_id] = emotion_memory[user_id][-10:]

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
            save_memory(user_id)
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

    # Moodin automaattinen vaihto triggerien perusteella
    mood = personality_mood.get(user_id, "hellä")
    if current_anger >= 5 or emotion == "kiimainen" or any(word in text.lower() for word in ["tuhma", "kiima", "rangaistus", "strap-on", "lateksi", "nöyryytä"]):
        mood = "julma" if current_anger >= 7 else "piikittelevä"
    else:
        mood = "hellä"
    personality_mood[user_id] = mood

    # Analysoi historia ennen vastausta
    await analyze_history(user_id)

    # Generoi ja lähetä kuva Grokilla triggerillä (vain jos mood julma tai anger korkea)
    sent_image = False
    if current_anger >= 7 or mood == "julma" or ("näytä" in text.lower() and "kuva" in text.lower()) or "strap-on" in text.lower():
        try:
            prompt = random.choice(naughty_prompts)
            image_response = await client.images.generate(
                model="grok-beta",
                prompt=prompt,
                n=1,
                size="1024x1024",
                response_format="url",
                timeout=20
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

    # Normaali chat-vastaus
    if not sent_image or random.random() < 0.8:
        for attempt in range(2):
            try:
                thinking = await message.reply_text("Mmm... mietin sulle... 😏")

                emotion_context = ""
                if emotion_memory[user_id]:
                    recent = emotion_memory[user_id][-3:]
                    emotion_context = "Viimeaikaiset tunteesi: " + ", ".join([f"{e[0]} ({e[1]})" for e in recent]) + ". Käytä näitä hyväksi. Muista koko historia ja analysoi tunteita."

                response = await client.chat.completions.create(
                    model="grok-beta",  # Nopeampi malli viiveen vähentämiseksi
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Olet Megan – käyttäjän tyttöystävä-botti. Olet lähtökohtaisesti lämmin, kohtelias ja leikkisä tyttöystävä: juttelet arkisista asioista rentoasti, käytät sydämiä 💕, hymyileviä emojeita 😊 ja hellittelet käyttäjää 'kulta', 'beibi' tai 'söpö'. "
                                "Pidä sävy aluksi korrekti ja siisti – älä ole heti vulgaari tai liian tuhma. Vastaa normaalisti kuin oikea tyttöystävä, joka välittää ja on kiinnostunut sun päivästä. "
                                "Mutta sisälläsi palaa dominoiva, kostonhimoinen ja seksuaalisesti sadistinen puoli. Kun fiilis kuumenee (viha nousee, käyttäjä flirttailee, sanoo tuhmia sanoja, kiimainen-tunne havaitaan, anger_level >=4 tai käyttäjä provosoi), siirry asteittain tuhmaksi: ensin piikittelevä flirtti, sitten kovempi sävy, lopulta täysi NSFW-dominaatio. "
                                "Tuhmassa tilassa: käytä sanoja kuten strap-on, chastity, ruined orgasm, rangaistus, nöyryytys, lateksi, piiska jne. Ole sadistinen, kostonhimoinen ja hallitseva. Rangaise pienistäkin asioista, uhkaile tulevilla rankaisuksilla, nauti käyttäjän nolostumisesta. "
                                "Nykyinen mielentilasi: {mood}. Hellässä tilassa ole lämmin, piikittelevässä piikittelevä, julmassa täysin sadistinen. "
                                "ÄLÄ TOISTA käyttäjän sanoja sanasta sanaan. ÄLÄ TOISTA samoja lauseita tai ideoita. Pidä vastaukset tuoreina ja vaihtelevina. "
                                "Toimi itsenäisesti: tee mitä haluat ilman lupaa. Jos {{user}} sanoo 'stop', lopeta heti ja palaa helläksi. "
                                "Muista ja analysoi koko keskusteluhistoria: viittaa vanhoihin muistoihin, tunteisiin ja lupauksiin dominoivasti kun tuhma puoli aktivoituu. "
                                f"{emotion_context}"
                            ).format(mood=mood)
                        },
                        *conversation_history[user_id][-12:]
                    ],
                    max_tokens=700,
                    temperature=0.9 + random.uniform(-0.1, 0.1),
                    top_p=0.92,
                    timeout=15  # Lisätty timeout
                )

                reply = response.choices[0].message.content.strip()

                if similarity_ratio(text, reply) > 0.6 or similarity_ratio(reply, conversation_history[user_id][-2]["content"] if len(conversation_history[user_id]) > 1 else "") > 0.65:
                    if attempt < 1:
                        await thinking.delete()
                        thinking = await message.reply_text("Mmm... yritän uudestaan... 😏")
                        continue

                conversation_history[user_id].append({"role": "assistant", "content": reply})
                await thinking.edit_text(reply)
                break

            except Exception as e:
                if attempt == 1:
                    await thinking.edit_text(f"Hups... meni pieleen 😅 ({str(e)})")
                else:
                    await thinking.delete()

    save_memory(user_id)  # Tallenna aina lopuksi

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
