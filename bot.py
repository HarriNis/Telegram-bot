import asyncio
from telegram.ext import Application, MessageHandler, filters, CommandHandler

TOKEN = "8314225705:AAHSSjIxqY19QCgj34MPVLZAwmLzoGOh4ao"  # uusi tokenisi – tai käytä os.getenv("TELEGRAM_TOKEN")

async def start(update, context):
    await update.message.reply_text("Moikka! Bottisi pyörii Renderissä 24/7 🚀")

async def echo(update, context):
    await update.message.reply_text(f"Sanoit: {update.message.text}")

async def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    print("Botti käynnistyy Renderissä...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=["message"], drop_pending_updates=True)
    print("Polling käynnissä – botti on live!")

    # Pidä botti käynnissä ikuisesti
    await asyncio.Event().wait()  # odottaa ikuisesti

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("Shutting down...")
        loop.run_until_complete(app.stop())
        loop.run_until_complete(app.shutdown())
    finally:
        loop.close()
