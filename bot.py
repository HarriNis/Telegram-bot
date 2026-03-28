Kyllä — tämä on itse asiassa erittäin hyvä pohja jo nyt, mutta siinä on pari selkeää “pullonkaulaa”, jotka rajoittavat:
	1.	vastausten pituutta ja monisanaisuutta
	2.	fantasioiden muistamista ja aktiivista hyödyntämistä

Alla saat täsmälliset muutokset, ei yleistä teoriaa.

⸻

🔧 1. Tee vastauksista monisanaisempia (ja rikkaampia)

Ongelma

Vaikka max_tokens=850, botti:
	•	valitsee lyhyitä vastauksia (scoring bias)
	•	system prompt painottaa “avoid over-describing”

⸻

✅ MUUTOS 1: säädä scoringia

Nykyinen:

def score_response(text):
    score = 0
    if len(text) > 60: score += 1

Korvaa:

def score_response(text):
    score = 0

    length = len(text)

    if length > 80: score += 1
    if length > 160: score += 2
    if length > 300: score += 2   # suosii pidempiä

    if "?" in text: score += 1

    if any(w in text.lower() for w in [
        "haluan", "tuntuu", "ärsyttää", "kiinnostaa", "ajattelin"
    ]):
        score += 1

    if any(w in text.lower() for w in [
        "mitä jos", "entä jos", "pitäiskö", "voisit"
    ]):
        score += 1

    return score

👉 Tämä yksin tekee jo isoimman muutoksen.

⸻

✅ MUUTOS 2: pakota sisältöä system promptiin

Lisää get_system_prompt loppuun:

**Response style upgrade:**
- Responses should often be multi-sentence, not minimal
- Expand emotions, reactions and descriptions naturally
- Avoid one-liners unless mood specifically demands it
- Build a sense of flow and presence


⸻

✅ MUUTOS 3: vähennä “liiallista minimalismia”

Poista tai pehmennä tämä:

- Avoid over-describing environment

Korvaa:

- Keep descriptions focused, but do not avoid detail when it adds emotional depth


⸻

🧠 2. Tee fantasioista pysyvä ja aktiivinen muisti

Tämä on tärkein osa.

⸻

❗ Ongelma nyt
	•	Fantasiat menee sensitive tai general
	•	mutta niitä EI:
	•	strukturoitu
	•	priorisoida tarpeeksi
	•	käytetä aktiivisesti generoinnissa

⸻

✅ MUUTOS 4: lisää uusi muistityyppi fantasy

Muuta store_memory:

tag = "sensitive" if any(w in txt for w in [...]) else "general"

👉 korvaa:

if any(w in txt for w in ["fantasia", "haluan", "kuvittele", "jos me", "mitä jos me"]):
    tag = "fantasy"
elif any(w in txt for w in ["pelkään", "häpeän", "ahdistaa"]):
    tag = "sensitive"
else:
    tag = "general"


⸻

✅ MUUTOS 5: boostaa fantasioiden retrieval

retrieve_memories → lisää painotus:

importance = 1.5 if any(w in content.lower() for ...) else 1.0

👉 muokkaa:

importance = 1.0

if any(w in content.lower() for ["haluan", "tunne", "ikävä"]):
    importance += 0.5

if '"type": "fantasy"' in content:
    importance += 1.2   # 🔥 iso boost


⸻

✅ MUUTOS 6: tuo fantasiat suoraan promptiin

Lisää ennen message buildia:

fantasy_memories = [
    m for m in memories
    if '"type": "fantasy"' in m
]

Sitten injektoi:

if fantasy_memories:
    messages.insert(0, {
        "role": "user",
        "content": (
            "User fantasies you should remember and may build on:\n"
            + "\n".join(fantasy_memories[:5])
        )
    })


⸻

✅ MUUTOS 7: anna lupa käyttää niitä aktiivisesti

Lisää system promptiin:

**Fantasy continuity rules:**
- If the user has shared fantasies before, you may reuse and build on them
- You are encouraged to bring them up naturally later
- Treat fantasies as shared ongoing experiences, not isolated ideas


⸻

🔁 3. Tee että botti itse palaa fantasioihin

Lisää tähän:

if random.random() < 0.25 and fantasy_memories:

👉 ja injektoi:

messages.insert(0, {
    "role": "user",
    "content": "You may bring up one of the user's past fantasies naturally in this reply."
})


⸻

🎯 4. Bonus: tee muistista “halu”

Lisää update_desire:

if state.get("core_desires"):
    if random.random() < 0.3:
        state["desire"] = "revisit a shared fantasy"


⸻

🧩 Lopputulos

Näillä muutoksilla botti:

✔ Puhuu enemmän
	•	pidemmät vastaukset
	•	enemmän tunnetta + sisältöä

✔ Muistaa fantasiat oikeasti
	•	tallennetaan omana tyyppinä
	•	haetaan aktiivisesti
	•	painotetaan rankingissa

✔ Käyttää niitä itse
	•	tuo niitä takaisin keskusteluun
	•	rakentaa jatkumoa

⸻

🚀 Jos haluat vielä next level

Voin tehdä sinulle seuraavaksi:
	•	“fantasy evolution system” (fantasiat kehittyy ajan myötä)
	•	“obsession tracking” (mitkä teemat toistuu eniten)
	•	tai “long-term storyline engine”

Sano vaan 👍
