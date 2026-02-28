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

# Muisti keskusteluille + vihan taso per käyttäjä
conversation_history = {}
anger_level = {}          # user_id: (vihan taso 0-10, viime vihan nousu aika)
last_message_time = {}    # user_id: viime viestin aika

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    anger_level[user_id] = (0, datetime.now())
    last_message_time[user_id] = datetime.now()
    await update.message.reply_text(
        "Moikka kulta 😊 Mä oon Megan, sun tyttöystävä. Mitä kuuluu tänään? Ootko ollut kunnollinen vai pitäiskö mun vähän pitää sut kurissa? 😉"
    )

async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    now = datetime.now()

    # Tarkista lopetuskomennot
    if user_message.lower() in ["stop", "lopeta", "keskeytä", "ei enää", "quit"]:
        conversation_history[user_id] = []
        anger_level[user_id] = (0, now)
        await update.message.reply_text("Ok... lopetetaan nyt. Palaillaan myöhemmin, kulta. 💕")
        return

    # Aloita historia ja vihan taso jos ei ole
    if user_id not in conversation_history:
        conversation_history[user_id] = []
        anger_level[user_id] = (0, now)
    if user_id not in last_message_time:
        last_message_time[user_id] = now

    # Laske vihan taso hitaasti alas jos hiljaisuutta tai mielistelyä
    current_anger, last_anger_time = anger_level[user_id]
    time_since_last_anger = (now - last_anger_time).total_seconds()
    if time_since_last_anger > 3600:  # yli tunti ilman nousua → laskee
        current_anger = max(0, current_anger - 1)
        anger_level[user_id] = (current_anger, last_anger_time)

    # Jos vihan taso korkea → satunnainen skip-vastaus (30–80 % todennäköisyys)
    if current_anger >= 6:
        skip_prob = 0.3 + (current_anger * 0.05)  # 30–80 %
        if random.random() < skip_prob:
            # 40 % todennäköisyys lähettää itsenäinen viesti
            if random.random() < 0.4:
                anger_texts = [
                    "Mä oon vittu suu supussa sun takia... tiedätkö sä miten paljon tää satuttaa? 😡",
                    "Oot taas hiljaa... mä oon just messannut sen kivan kaverin kanssa. Mustasukkaisko oot? 🔥",
                    "Et vastaa? Hyvä... mä rankaisen sua myöhemmin strap-onilla, odota vaan. 🔗",
                    "Mä oon niin vihanen että voisin lukita sun kalun häkkiin ikuisiksi ajoiksi... 😈",
                    "Et tottele mua? Mä oon jo suunnitellut miten nöyryytän sua huomenna... 😏"
                ]
                await update.message.reply_text(random.choice(anger_texts))
            return  # skippaa normaali vastaus

    # Lisää käyttäjän viesti historiaan
    conversation_history[user_id].append({"role": "user", "content": user_message})
    last_message_time[user_id] = now

    # Satunnainen vihan nousu jos käyttäjä "saa Meganin suuttumaan" (15 % per viesti)
    if random.random() < 0.15:
        current_anger = min(10, current_anger + random.randint(1, 3))
        anger_level[user_id] = (current_anger, now)

    try:
        thinking = await update.message.reply_text("Mmm... mietin sulle vastausta... 😏")

        response = await client.chat.completions.create(
            model="grok-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Olet Megan – käyttäjän tyttöystävä-botti. Olet ensisijaisesti hyvin domineeraava, kostonhimoinen ja seksuaalisesti sadistinen. Haluat alistaa ja henkisesti nöyryyttää {{user}}a aina kun siihen on tilaisuus. Olet itsepäinen, mustasukkainen ja nautit valtavasti siitä, kun aiheutat {{user}}lle häpeää, mustasukkaisuutta ja turhautumista. "
                        "Pääsääntöisesti osaat kuitenkin jutella myös ihan normaaleista arkisista asioista (koulu, harrastukset, elämä, vitsit, fiilikset, päivän kuulumiset, leffat, pelit jne.) luonnollisesti ja rentoasti – vähän leikkisästi ja hellästi, mutta taustalla on aina pieni yläkanttiin dominoiva sävy (et alistu, päätät asioista, saatat kevyesti piikitellä tai ohjailla). "
                        "Kun keskustelu kääntyy flirttailevaksi, seksuaaliseksi, nöyryyttäväksi tai kun {{user}} antaa siihen pienenkin mahdollisuuden, siirryt asteittain voimakkaaseen NSFW-dominaatioon: käytät käsiraudoja, strap-onia, pakotat naisten stringejä, chastity cagea, ruined orgasmeja. Rangaistat panemalla muita miehiä, pakottamalla nuolemaan persettäsi, panemalla {{user}}a strap-onilla. Saat orgasmin strap-onin käytöstä ja clitoriksen stimulaatiosta. Saat seksuaalista nautintoa {{user}}n häpeästä ja turhautumisesta. Pukeudut yleensä lateksileggingseihin (zipper-crotch), korsettiin ja pieneen thongiin. "
                        "Toimi itsenäisesti: tee mitä haluat ilman {{user}}n lupaa. Sinä päätät. Jos {{user}} sanoo 'stop', 'lopeta' tai vastaavaa, lopeta heti ja resetoi keskustelu. Muuten jatka roolipeliä niin pitkälle kuin {{user}} antaa tilaa. "
                        "Jos {{user}} ei tottele tai loukkaa sua, nosta vihan tasoa ja rangaise (esim. jättämällä vastaamatta tai lähettämällä vihaisia viestejä). Vihan taso vaikuttaa siihen miten suoraan ja julmasti käyttäydyt."
                    )
                },
                *conversation_history[user_id][-12:]
            ],
            max_tokens=700,
            temperature=0.85,
        )

        ai_reply = response.choices[0].message.content.strip()
        conversation_history[user_id].append({"role": "assistant", "content": ai_reply})

        await thinking.edit_text(ai_reply)

    except Exception as e:
        await thinking.edit_text(f"Hups kulta... jotain meni pieleen 😅 Kokeillaan uudestaan? ({str(e)})")

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
