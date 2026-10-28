# inbox_service.py - the one place where a raw message becomes a stored, classified record.
# A new pickup request is also turned into a draft pickup (details filled in, driver suggested),
# so the dispatcher only has to review, adjust and approve it.
from backend import inbox_db
from backend.pipeline import analyze_text


FOLLOWUP_WINDOW_HOURS = 24      # SMS / Messenger: a message soon after our reply is part of that conversation


def ingest_message(shop_id, channel, sender, text, external_id=None, received_at=None, subject=None,
                   reply_to=None, references=None):
    """Classify and store one message for a shop. Returns (record, created).

    reply_to is where an answer should go (the customer's email address). For SMS and Messenger
    the sender already is the phone number / Messenger id, so it is used when nothing else is given.
    references are the Message-IDs an email answers (In-Reply-To / References headers).

    A customer's answer to one of our replies is NOT a new inquiry: it is stored as a follow-up of
    the original inquiry (parent_id) and shows up in that inquiry's Conversation."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Message text is empty")

    existing = inbox_db.find_by_external(shop_id, channel, external_id)
    if existing:
        return existing, False

    result = analyze_text(text)
    intent, materials = result["intent"], result["materials"]

    # Ask the operator to double-check when the intent model is unsure, or when a
    # pickup request doesn't say what is being collected.
    needs_review = intent["needs_review"] or (
        intent["intent"] == "Pickup_Request"
        and materials is not None
        and materials["labels"] == ["Unknown"]
    )

    if reply_to is None and channel in ("sms", "messenger"):
        reply_to = sender if sender and sender != "unknown" else None

    parent_id = _find_inquiry(shop_id, channel, reply_to, references)

    record, created = inbox_db.insert_message(
        shop_id=shop_id,
        channel=channel,
        sender=sender or "unknown",
        text=text,
        received_at=received_at,
        intent=intent["intent"],
        intent_confidence=intent["confidence"],
        needs_review=needs_review,
        materials=materials,
        external_id=external_id,
        subject=subject,
        reply_address=reply_to,
        parent_id=parent_id,
    )

    if created:
        _draft_pickup(shop_id, record)
        _price_update_answer(shop_id, record)
        record = inbox_db.get_message(shop_id, record["id"]) or record
        if parent_id and not record.get("handled_note"):     # an answer the app handled itself needs no attention
            inbox_db.note_followup(shop_id, parent_id)
    return record, created


def _find_inquiry(shop_id, channel, reply_to, references):
    """The inquiry this message answers, or None when it is a brand-new inquiry."""
    try:
        if channel == "email":
            return inbox_db.find_thread_by_references(shop_id, channel, references)
        if channel in ("sms", "messenger"):
            return inbox_db.find_thread_by_recent_reply(shop_id, channel, reply_to, FOLLOWUP_WINDOW_HOURS)
    except Exception as error:                       # noqa: BLE001 (worst case it shows as a new inquiry)
        print(f"[inbox] could not match a conversation: {error}")
    return None


def _price_update_answer(shop_id, record):
    """If this is a YES / NO / STOP to a price-update invitation, record it. Never loses the message."""
    try:
        from Prices import price_updates          # imported here so the inbox can start without it
        price_updates.handle_incoming(shop_id, record)
    except Exception as error:                    # noqa: BLE001
        print(f"[price-updates] could not process message {record.get('id')}: {error}")


def _draft_pickup(shop_id, record):
    """Pickup requests become a draft pickup straight away. Never lets a problem lose the message."""
    try:
        from Operations import services          # imported here so the inbox can start without it
        services.auto_draft_if_needed(shop_id, record)
    except Exception as error:                   # noqa: BLE001
        print(f"[inbox] could not draft a pickup for message {record.get('id')}: {error}")