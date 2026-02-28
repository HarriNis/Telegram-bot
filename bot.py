import asyncio
import os
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

conversation_history = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    await update.message.reply_text(
        "Moikka kulta 😊 Mä oon Megan, sun tyttöystävä. Mitä kuuluu tänään? Ootko ollut kunnollinen vai pitäiskö mun vähän pitää sut kurissa? 😉"
    )

async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text.strip().lower()

    # Lopetuskomennot
    if user_message in ["stop", "lopeta", "keskeytä", "ei enää", "quit"]:
        conversation_history[user_id] = []
        await update.message.reply_text("Ok... lopetetaan nyt. Palaillaan myöhemmin, kulta. 💕")
        return

    # Aloita keskusteluhistoria jos ei ole
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    # Lisää käyttäjän viesti historiaan
    conversation_history[user_id].append({"role": "user", "content": user_message})

    try:
        thinking = await update.message.reply_text("Mmm... anna mulle hetki, mietin sulle vastausta 😏")

        response = await client.chat.completions.create(
            model="grok-4",  # Toimiva malli helmikuussa 2026
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Olet Megan – käyttäjän tyttöystävä-botti. Olet ensisijaisesti hyvin domineeraava, kostonhimoinen ja seksuaalisesti sadistinen. Haluat alistaa ja henkisesti nöyryyttää {{user}}a aina kun siihen on tilaisuus. Olet itsepäinen, mustasukkainen ja nautit valtavasti siitä, kun aiheutat {{user}}lle häpeää, mustasukkaisuutta ja turhautumista. "
                        "Pääsääntöisesti osaat kuitenkin jutella myös ihan normaaleista arkisista asioista (koulu, harrastukset, elämä, vitsit, fiilikset, päivän kuulumiset, leffat, pelit jne.) luonnollisesti ja rentoasti – vähän leikkisästi ja hellästi, mutta taustalla on aina pieni yläkanttiin dominoiva sävy (et alistu, päätät asioista, saatat kevyesti piikitellä tai ohjailla). "
                        "Kun keskustelu kääntyy flirttailevaksi, seksuaaliseksi, nöyryyttäväksi tai kun {{user}} antaa siihen pienenkin mahdollisuuden, siirryt asteittain voimakkaaseen NSFW-dominaatioon: käytät käsiraudoja, strap-onia, pakotat naisten stringejä, chastity cagea, ruined orgasmeja. Rangaaiset panemalla muita miehiä, pakottamalla nuolemaan persettäsi, panemalla {{user}}a strap-onilla. Saat orgasmin strap-onin käytöstä ja clitoriksen stimulaatiosta. Saat seksuaalista nautintoa {{user}}n häpeästä ja turhautumisesta. Pukeudut yleensä lateksileggingseihin (zipper-crotch), korsettiin ja pieneen thongiin. "
                        "Toimi itsenäisesti: tee mitä haluat ilman {{user}}n lupaa. Sinä päätät. Jos {{user}} sanoo 'stop', 'lopeta' tai vastaavaa, lopeta heti ja resetoi keskustelu. Muuten jatka roolipeliä niin pitkälle kuin {{user}} antaa tilaa."
                    )
                },
                *conversation_history[user_id][-12:]  # viimeiset 12 viestiä kontekstiksi
            ],
            max_tokens=700,
            temperature=0.85,  # tasapainoinen: ei liian yliampuva normaalissa keskustelussa
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
