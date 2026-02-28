import asyncio
from telegram.ext import Application, MessageHandler, filters, CommandHandler

TOKEN = "8314225705:AAFxObpju67JKpTS2fuNJp7BBRMc-W1EizA"  # ← VAIHDA OMAAN TOKENIISI!

async def start(update, context):
    await update.message.reply_text("Moikka! Bottisi pyörii Renderissä 24/7 🚀")

async def echo(update, context):
    await update.message.reply_text(f"Sanoit: {update.message.text}")

async def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    print("Botti käynnistyy Renderissä...")
    await app.run_polling(allowed_updates=["message"], drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
