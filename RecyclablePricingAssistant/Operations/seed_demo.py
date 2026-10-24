"""Fills one shop with the demo day from the design (Rico, Liz, five pickups, Elena's request).

Run from the project root, with the owner's login email:
    python -m Operations.seed_demo owner@example.com
Safe to run twice: it stops if the shop already has trucks."""
import sys

from backend import accounts_db, db, inbox_service, pipeline, security
from Operations import ops_db, services

DRIVERS = [("Rico Mendoza", "rico@scrapdesk.local"), ("Liz Garcia", "liz@scrapdesk.local")]
TRUCKS = [("SD-01", "Small truck", 1500, 0), ("LG-02", "Light truck", 1000, 1)]
# customer, start, truck index, material, kg, rate, stop note
DAY = [
    ("Luna Mart", "09:00", 0, "Cardboard", 180, 4, "Call the contact before arrival."),
    ("Choi Eatery", "09:30", 1, "Mixed recyclables", 120, 5, None),
    ("Reyes Hardware", "10:00", 0, "Mixed scrap", 420, 8, "Check the loading area before hauling."),
    ("Northside Grocery", "11:00", 1, "Cardboard", 180, 4, None),
    ("Mabini Printing", "13:00", 0, "Paper / cardboard", 320, 4, "Separate paper from other materials."),
]
ELENA = ("We have 400 kg of cardboard and 250 kg of PET. Can we get ₱9/kg for cardboard and ₱19/kg "
         "for PET? If the price is okay, we'd like pickup today from 1:00-3:00 PM. "
         "Small truck access only at gate 2.")


def main(owner_email):
    db.init_db()
    ops_db.init_ops_db()
    owner = accounts_db.get_user_by_email(owner_email)
    if owner is None or owner["role"] != "owner":
        sys.exit(f"No owner account found for {owner_email}.")
    shop_id = owner["shop_id"]
    if ops_db.list_trucks(shop_id, active_only=False):
        sys.exit("This shop already has trucks - nothing was changed.")

    today = services.today_ph()
    drivers = []
    for name, email in DRIVERS:
        user = accounts_db.get_user_by_email(email) or accounts_db.create_user(
            shop_id, email, security.hash_password("ChangeMe123"), name, "driver")
        drivers.append(user)
    trucks = [services.create_truck(shop_id, code, label, cap, drivers[i]["id"])
              for code, label, cap, i in TRUCKS]

    for customer, start, t, material, kg, rate, note in DAY:
        ops_db.create_pickup(
            shop_id,
            {"customer_name": customer, "area": "Quezon City", "pickup_date": today,
             "window_start": start, "truck_id": trucks[t]["id"], "status": "confirmed",
             "stop_note": note, "approved_by": owner["id"]},
            [{"material": material, "expected_kg": kg, "requested_rate": rate, "approved_rate": rate}])

    pipeline.load_models()
    message, _ = inbox_service.ingest_message(shop_id, "messenger", "Elena Santos", ELENA)
    pickup, _ = services.create_from_message(shop_id, message["id"])
    ops_db.update_pickup(shop_id, pickup["id"], organization="Santos Packaging Warehouse",
                         address="18 Industria St., Bagumbayan", area="Bagumbayan, QC",
                         access_note="Small truck access. Loading is at gate 2. Call upon arrival.")
    print(f"Demo day added for {today}: 2 trucks, 5 confirmed pickups, 1 request waiting for approval.")
    print("Driver logins: rico@scrapdesk.local / liz@scrapdesk.local  (password: ChangeMe123)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m Operations.seed_demo owner@example.com")
    main(sys.argv[1])