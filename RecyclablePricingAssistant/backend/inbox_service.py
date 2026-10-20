# inbox_service.py - the one place where a raw message becomes a stored, classified record.
from backend import inbox_db
from backend.pipeline import analyze_text


def ingest_message(shop_id, channel, sender, text, external_id=None, received_at=None, subject=None):
    """Classify and store one message for a shop. Returns (record, created)."""
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

    return inbox_db.insert_message(
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
    )
