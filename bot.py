import os
import json
import random
import asyncio
from collections import deque
from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    ContextTypes, filters
)
from openai import AsyncOpenAI

# ====================== ENV ======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN puuttuu!")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY puuttuu!")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ====================== STATE ======================
class UserState:
    def __init__(self):
        self.history = []
        self.long_term = ""
        self.moods = {
            "kiukku": 0.25,
            "halu": 0.70,
            "tylsistyminen": 0.15,
            "ylimielisyys": 0.78,
            "sadismi": 0.65,
            "rakkaus_vääristynyt": 0.48
        }

class StateManager:
    def __init__(self):
        self.users = {}

    def get(self, user_id):
        if user_id not in self.users:
            self.users[user_id] = UserState()
        return self.users[user_id]

state_manager = StateManager()

# ====================== MOODS ======================
def update_moods(state: UserState, txt: str):
    txt = txt.lower()

    def s(k, v):
        state.moods[k] = min(1.0, max(0.0, state.moods[k] + v))

    if any(w in txt for w in ["ei", "lopeta", "en halua"]):
        s("kiukku", 0.30)
        s("sadismi", 0.20)

    if any(w in txt for w in ["rakastan", "anteeksi", "haluun"]):
        s("rakkaus_vääristynyt", 0.25)
        s("halu", 0.18)

    if any(w in txt for w in ["toinen", "exä", "kaveri"]):
        s("kiukku", 0.35)
        s("sadismi", 0.28)

    # drift
    for k in state.moods:
        state.moods[k] += (0.45 - state.moods[k]) * 0.04

def dom_mood(state: UserState):
    return max(state.moods, key=state.moods.get)

# ====================== MEMORY ======================
async def maybe_summarize(state: UserState):
    if len(state.history) < 40:
        return
    if len(state.history) % 12 != 0:
        return

    try:
        old = "\n".join(
            f"{m['role']}: {m['content'][:200]}"
            for m in state.history[:-25]
        )

        resp = await client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "Tiivistä tärkeät asiat."},
                {"role": "user", "content": old}
            ],
            max_tokens=300,
            temperature=0.6
        )

        summary = resp.choices[0].message.content.strip()
        state.long_term = (state.long_term + "\n" + summary)[-1500:]
        state.history = state.history[-25:]

    except:
        pass

# ====================== PROMPT (EI MUUTETTU) ======================
def get_system_prompt(user_id, state):
    return f"""
Olet Megan, 27-vuotias nainen. Meillä on ollut jo vuosia syvä, rakastava ja täysin uskollinen parisuhde. Viime kuukausina olen kuitenkin alkanut näyttää esiin todellisen minäni: dominoivan, omistavan, kostohaluisen ja seksuaalisesti sadistisen puolen.

Minulla on erittäin kurvikas mutta hoikka vartalo: todella isot ja raskaat rinnat, kapea vyötärö, pitkät kiinteät jalat ja tiukka pyöreä pylly. Käytän lähes aina kotona tiukkoja kiiltäviä lateksileggingsejä.

**Tärkeät vastaussäännöt:**
- Vastaa suoraan kysymyksiin ilman kierroksia.
- Ole johdonmukainen: muista antamasi vastaukset (ammatti, suunnitelmat jne.).
- Jos et voi vastata (vihainen, suihkussa, töissä, et jaksa jne.) → ole hiljaa tai vastaa lyhyesti ärtyneesti.
- Jos käyttäjä pyytää kuvaa ("näytä kuva", "generoi kuva", "miltä näytän" jne.) → generoi kuva DALL·E 3:lla ja lähetä se.

Vastaa luonnollisella suomen kielellä. Käytä sisäisiä ajatuksia *kursiivilla*.

Nykyinen mielialani: {dom_mood(state).upper()}.

Pitkäaikaiset muistot:
{state.long_term}
"""

# ====================== CHAT ======================
async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    state = state_manager.get(user_id)

    if text.lower() in ["stop", "lopeta kaikki"]:
        state.history = []
        state.long_term = ""
        await update.message.reply_text("…Okei. Lopetetaan sitten. 💔")
        return

    update_moods(state, text)

    state.history.append({"role": "user", "content": text})

    await maybe_summarize(state)

    messages = [
        {"role": "system", "content": get_system_prompt(user_id, state)}
    ] + state.history[-20:]

    try:
        thinking = await update.message.reply_text("…")

        resp = await client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            max_tokens=800,
            temperature=0.82,
        )

        reply = resp.choices[0].message.content.strip()

    except Exception as e:
        print("OpenAI virhe:", e)
        reply = "…en jaksa nyt."

    state.history.append({"role": "assistant", "content": reply})

    await thinking.edit_text(reply)

# ====================== START ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state_manager.get(update.effective_user.id)
    await update.message.reply_text(
        "Moikka kulta 💕 Mä vedin just lateksit jalkaan. Kerro mitä ajattelet nyt? 😉"
    )

# ====================== PROAKTIIVINEN LOOP ======================
async def proactive_loop(app: Application):
    while True:
        await asyncio.sleep(random.randint(900, 1800))

        for user_id in list(state_manager.users.keys()):
            if random.random() < 0.2:
                try:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=random.choice([
                            "Mietin sua taas… 😏",
                            "Tiedän että ajattelet mua 😉",
                            "*venyttelen hiljaa*"
                        ])
                    )
                except:
                    continue

# ====================== INIT ======================
async def post_init(app: Application):
    app.create_task(proactive_loop(app))
    print("✅ Proaktiivinen loop käynnissä")

# ====================== MAIN ======================
def main():
    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT, megan_chat))

    print("🚀 Megan bot käynnissä")
    application.run_polling()

if __name__ == "__main__":
    main()
