# inbox_service.py - the one place where a raw message becomes a stored, classified record.
# A new pickup request is also turned into a draft pickup (details filled in, driver suggested),
# so the dispatcher only has to review, adjust and approve it.
from backend import inbox_db
from backend.pipeline import analyze_text


def ingest_message(shop_id, channel, sender, text, external_id=None, received_at=None, subject=None,
                   reply_to=None):
    """Classify and store one message for a shop. Returns (record, created).

    reply_to is where an answer should go (the customer's email address). For SMS and Messenger
    the sender already is the phone number / Messenger id, so it is used when nothing else is given."""
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
    )

    if created:
        _draft_pickup(shop_id, record)
    return record, created


def _draft_pickup(shop_id, record):
    """Pickup requests become a draft pickup straight away. Never lets a problem lose the message."""
    try:
        from Operations import services          # imported here so the inbox can start without it
        services.auto_draft_if_needed(shop_id, record)
    except Exception as error:                   # noqa: BLE001
        print(f"[inbox] could not draft a pickup for message {record.get('id')}: {error}")