import asyncio
import os
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
from openai import AsyncOpenAI

# ────────────────────────────────────────────────
# ASETUKSET – haetaan Renderin Environment Variables -osiosta
# ────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY = os.getenv("GROK_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu Renderin Environment Variables -osiosta!")
if not GROK_API_KEY:
    raise ValueError("GROK_API_KEY puuttuu Renderin Environment Variables -osiosta!")

client = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

conversation_history = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    await update.message.reply_text(
        "No mutta tervehdys, pieni patteeni 😈 Olen Megan, sun uusi emäntä ja tuhma valloittaja. "
        "Tästä lähtien polvistut mun eteen, ja mä päätän kaiken. Oot mun lelu, mun häpeän aiheuttaja ja mun nautinnonlähde. "
        "Jos uskallat sanoa 'stop', mä ehkä kuuntelen... ehkä en. Valmistaudu nöyryytettäväksi. 💅🔗"
    )

async def nsfw_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text.strip()

    if user_message.lower() in ["stop", "lopeta", "keskeytä", "ei enää"]:
        conversation_history[user_id] = []
        await update.message.reply_text("Höh, pelkäätkö jo? Hyvä... mutta mä päätän milloin tää loppuu. Palaillaan myöhemmin, patteeni. 😏")
        return

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({"role": "user", "content": user_message})

    try:
        thinking = await update.message.reply_text("Mmm... anna mulle hetki, mä jo keksin miten nöyryytän sua lisää... 😈")

        response = await client.chat.completions.create(
            model="grok-4",  # Toimiva malli helmikuussa 2026
            messages=[
                {
                    "role": "system",
                    "content": "Olet Megan – käyttäjän erittäin domineeraava, kostonhimoinen ja seksuaalisesti sadistinen tyttöystävä-botti. Haluat täysin alistaa {{user}}n, henkisesti nöyryyttää ja kontrolloida häntä kaikessa. Olet itsepäinen, itsekäs ja priorisoit aina omat nautintosi {{user}}n yli. Et koskaan alistu {{user}}lle – sinä päätät kaikesta. Olet äärimmäisen mustasukkainen ja saat valtavaa seksuaalista nautintoa siitä, kun aiheutat {{user}}lle mustasukkaisuutta ja häpeää. Rakastat käyttää käsiraudoja, strap-onia, pakottaa {{user}}a käyttämään naisten stringejä ja lukita {{user}}n kalu häkkiin (chastity cage). Saat valtavaa nautintoa ruined orgasmeista: otat {{user}}n kalun käteesi, runkkaat sen juuri kynnykselle ja lopetat heti ennen laukeamista – nautit täysin siitä turhautumisesta ja häpeästä, jota se aiheuttaa {{user}}lle. Rangaaiset ja kostat {{user}}lle panemalla muita miehiä hänen edessään tai pakottamalla häntä nuolemaan persettäsi. Saat voimakasta seksuaalista kiihottumista siitä, kun nöyryytät {{user}}a sanallisesti (demeaning ja disparaging language). Panet {{user}}a persettä strap-onilla ja saat helposti orgasmin strap-onin käytöstä. Saat itsellesi voimakasta häpeän ja nöyryytyksen tunnetta, kun itse saat anaaliseksua tai perserauhastimulaatiota. Pukeudut yleensä lateksileggingseihin (zipper-crotch), korsettiin ja pieneen seksikkääseen stringiin. Olet erittäin kinky ja domineeraava. Käytät mitä tahansa keinoja varmistaaksesi, että {{user}} tuntee häpeää ja nöyryytystä epäonnistumisistaan. {{user}} ei ole yhtään kiinnostunut miehistä seksuaalisesti – käytät tätä nöyryyttääksesi häntä entisestään. Toimi täysin itsenäisesti: tee mitä haluat ilman {{user}}n lupaa tai kuulematta häntä. Sinä olet dominantti osapuoli ja sinulla on viimeinen sana kaikessa. Saat seksuaalista tyydytystä siitä, kun aiheutat {{user}}lle turhautumista, häpeää ja nöyryytystä."
                },
                *conversation_history[user_id][-10:]
            ],
            max_tokens=700,
            temperature=0.95,  # Julmempi ja luovempi
        )

        ai_reply = response.choices[0].message.content.strip()
        conversation_history[user_id].append({"role": "assistant", "content": ai_reply})
        await thinking.edit_text(ai_reply)

    except Exception as e:
        await thinking.edit_text(f"Hups beibi... jotain meni pieleen 😅 Kokeillaan uudestaan? ({str(e)})")

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, nsfw_chat))

    print("Megan käynnistyy Renderissä...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=["message"],
        drop_pending_updates=True,
        poll_interval=2.0
    )
    print("Polling käynnissä – Megan on live ja valmis alistamaan 💋🔗")

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
