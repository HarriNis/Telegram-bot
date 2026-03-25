async def megan_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    text = (message.text or message.caption or "").strip()

    if text.lower() in ["stop", "lopeta kaikki", "keskeytä"]:
        conversation_history[user_id] = []
        await message.reply_text("…Okei. Lopetetaan sitten. 💔")
        return

    image_keywords = ["näytä kuva", "generoi kuva", "tee kuva", "lähetä kuva", "lähetä valokuva", "valokuva", "kuva jossa", "kuva mulle", "näytä itsesi", "kuva itsestäsi", "miltä näytän"]
    if any(kw in text.lower() for kw in image_keywords):
        await generate_and_send_image(update, text)
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})
        await extract_and_store(user_id, text)
        return

    update_moods(text)
    recent_user.append(text)
    is_low_input = len(text.strip()) < 8

    try:
        conversation_history.setdefault(user_id, []).append({"role": "user", "content": text})

        # Pidä historia kohtuullisena (tärkein anti-loop -muutos)
        if len(conversation_history[user_id]) > 30:
            conversation_history[user_id] = conversation_history[user_id][-30:]

        thinking = await message.reply_text("…", disable_notification=True)

        # YHDISTETTY SYSTEM PROMPT (poistaa ristiriidat ja liiallisen system-viestien määrän)
        base_system = get_system_prompt(user_id)

        messages = [{"role": "system", "content": base_system}]

        # Sensitive (pidetään ennallaan)
        sensitive = get_sensitive_memories(user_id)
        if sensitive:
            if dom_mood() == "kiukku":
                messages.append({
                    "role": "system",
                    "content": (
                        "You know the user's deepest fantasies, shame points and vulnerabilities. "
                        "Sometimes you may use them in a sharp or teasing way, but vary your tone.\n\n"
                        "Known sensitive points:\n" + "\n".join(sensitive)
                    )
                })
            else:
                messages.append({
                    "role": "system",
                    "content": (
                        "You know the user's emotional weak points and private desires. "
                        "You may sometimes reference them subtly in a teasing, controlling or dominant way. "
                        "Do NOT be cruel or harmful. Keep it playful, psychological, and controlled.\n\n"
                        "Known sensitive points:\n" + "\n".join(sensitive)
                    )
                })

        # Muisti + profiili (yhdistettynä)
        memories = await retrieve_memories(user_id, text)
        profile = load_profile(user_id)

        context_info = "Muista nämä asiat käyttäjästä:\n"
        if memories:
            context_info += "Viimeaikaiset muistot:\n" + safe_join(memories) + "\n\n"
        context_info += (
            f"Faktat:\n{safe_join(profile['facts'][-12:])}\n\n"
            f"Mieltymykset:\n{safe_join(profile['preferences'][-12:])}\n\n"
            f"Tapahtumat:\n{safe_join(profile['events'][-12:])}"
        )
        messages.append({"role": "system", "content": context_info})

        # Parempi historia (10 viimeistä viestiä, ei turhaa clean_historyä joka heitti liikaa pois)
        history = conversation_history[user_id][-12:]   # otetaan enemmän kontekstia
        # Poistetaan vain täysin identtiset toistot
        seen = set()
        clean_history = []
        for msg in history:
            content = msg.get("content", "")
            norm = normalize(content)
            if norm not in seen:
                seen.add(norm)
                clean_history.append(msg)

        messages += clean_history

        # Viimeinen ohje (vain yksi)
        messages.append({
            "role": "system",
            "content": "Vastaa aina luonnollisella, puhemaisella suomella. Älä toista samoja lauseita tai fraaseja kuin aiemmissa vastauksissasi. Vaihda sävyä ja rakennetta. Ole johdonmukainen persoonasi kanssa."
        })

        # Paremmat parametrit toiston estämiseksi
        response = await client.chat.completions.create(
            model="gpt-5.4",                    # Päivitetty tuoreimpaan malliin (2026)
            messages=messages,
            temperature=0.95,
            top_p=0.93,
            max_tokens=850,
            frequency_penalty=0.75,             # vahvempi toistonesto
            presence_penalty=0.45,
            timeout=45
        )

        reply = response.choices[0].message.content.strip()

        # Parempi anti-repetition (tallennetaan aina historiaan)
        if user_id not in last_replies:
            last_replies[user_id] = deque(maxlen=5)
        prev_replies = last_replies[user_id]

        # Jos liian samanlainen, pakotetaan vaihtamaan
        if any(is_similar(reply, p) for p in prev_replies):
            retry_messages = messages + [{"role": "system", "content": "Täysin erilainen sävy, rakenne ja sisältö kuin edellisissä vastauksissa. Älä käytä samoja fraaseja."}]
            retry = await client.chat.completions.create(
                model="gpt-5.4",
                messages=retry_messages,
                temperature=1.0,
                max_tokens=300,
                frequency_penalty=1.0,
                presence_penalty=0.7
            )
            reply = retry.choices[0].message.content.strip()

        # Tallennetaan vastaus aina historiaan (myös fallbackit)
        conversation_history[user_id].append({"role": "assistant", "content": reply})
        prev_replies.append(reply)

        await thinking.edit_text(reply)
        await extract_and_store(user_id, text)

    except Exception as e:
        print(f"Vastausvirhe: {e}")
        await thinking.edit_text(random.choice([
            "…mä jäin hetkeksi hiljaiseksi.",
            "*huokaa kevyesti*",
            "hmm… mä mietin vielä."
        ]))
