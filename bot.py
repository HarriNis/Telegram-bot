import asyncio
from telegram.ext import Application, MessageHandler, filters, CommandHandler

TOKEN = "8314225705:AAHSSjIxqY19QCgj34MPVLZAwmLzoGOh4ao"  # uusi tokenisi

async def start(update, context):
    await update.message.reply_text("Moikka! Bottisi pyörii Renderissä 24/7 🚀")

async def echo(update, context):
    await update.message.reply_text(f"Sanoit: {update.message.text}")

async def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    print("Botti käynnistyy Renderissä...")

    # Manuaalinen käynnistys ilman loop-konfliktia
    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=["message"],
        drop_pending_updates=True,
        poll_interval=2.0
    )

    print("Polling käynnissä – botti on live!")

    # Pidä sovellus käynnissä ikuisesti
    await asyncio.sleep(float('inf'))  # ikuinen odotus ilman loop-virhettä

if __name__ == "__main__":
    # Luo uusi event loop Renderin ympäristöön
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("Shutting down...")
        loop.run_until_complete(app.stop())
        loop.run_until_complete(app.shutdown())
    finally:
        loop.close()
