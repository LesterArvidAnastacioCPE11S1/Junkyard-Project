
from pathlib import Path
import joblib

MODEL_PATH = Path("models/material_classifier.joblib")


def classify_material(text, saved):
    model = saved["model"]
    label_binarizer = saved["label_binarizer"]

    probabilities = model.predict_proba([text])[0]
    threshold = 0.50

    results = [
        (label, round(float(probability), 3))
        for label, probability in zip(
            label_binarizer.classes_, probabilities
        )
        if probability >= threshold and label != "Unknown"
    ]

    return results if results else [("Unknown", 0.0)]


def main():
    if not MODEL_PATH.exists():
        print("Model not found. Train it first.")
        return

    saved = joblib.load(MODEL_PATH)


    test_messages = [
        # Plastic
        "Can I sell these empty plastic water bottles?",
        "May mga plastik na timba akong ibebenta",
        "We collected plastic food containers from the restaurant",
        "May mga plastic wrapper at supot kami",
        "I have several old plastic chairs",
        "May mga bote ng shampoo na plastik",
        "Do you accept plastic detergent containers?",
        "May sirang plastic basin ako",
        "These are plastic storage boxes from our shop",
        "May mga galon na plastik sa bodega",

        # Paper
        "I have a stack of old newspapers",
        "May lumang papel at notebook ako",
        "Do you buy used magazines?",
        "May mga papel mula sa school namin",
        "These old office documents are made of paper",
        "May mga lumang diyaryo sa bahay",
        "Can I recycle these paper bags?",
        "May mga sobre at papel kami",
        "I want to sell used printer paper",
        "May lumang magazines at notebooks ako",

        # Cardboard
        "I have several flattened cardboard boxes",
        "May mga kahon ng karton kami",
        "Do you accept cardboard shipping cartons?",
        "May karton mula sa delivery namin",
        "These appliance boxes are made of cardboard",
        "May mga kahon ng sapatos sa tindahan",
        "Can I sell these corrugated cardboard sheets?",
        "May cardboard packaging sa stockroom",
        "I collected empty cardboard cartons",
        "May malalaking kahon ng karton ako",

        # Aluminum
        "I have aluminum beverage cans to sell",
        "May mga lata ng aluminum kami",
        "Do you accept old aluminum cooking pots?",
        "May aluminum window frame mula sa renovation",
        "These crushed cans are made of aluminum",
        "May mga aluminum tray pagkatapos ng handaan",
        "Can I recycle aluminum foil containers?",
        "May aluminum scraps ako mula sa repair",
        "We collected empty soda cans made of aluminum",
        "May lumang aluminum ladder sa bodega",

        # Other metals
        "I have scrap iron rods",
        "May bakal akong ibebenta",
        "Do you accept copper wire?",
        "May lumang steel pipes kami",
        "These rusty metal brackets are made of steel",
        "May tansong wire mula sa pagkukumpuni",
        "I found some brass door handles",
        "May bakal na kadena sa garahe",
        "Can I sell these stainless steel parts?",
        "May mga iron bars mula sa construction",

        # Glass
        "I have empty glass bottles",
        "May bote ng salamin ako",
        "Do you accept glass food jars?",
        "May mga garapong salamin kami",
        "These juice bottles are made of glass",
        "May lumang bote ng pabango na salamin",
        "Can I recycle glass sauce containers?",
        "May mga bote ng suka na salamin",
        "We collected glass jars from the kitchen",
        "May glass bottles sa tindahan",

        # Electronic waste
        "I have some old electronic cables",
        "May sirang charger ng cellphone ako",
        "Do you accept broken computer keyboards?",
        "May lumang router at modem kami",
        "These circuit boards came from an old computer",
        "May mga sirang earphones ako",
        "Can I recycle this broken computer mouse?",
        "May lumang power adapter sa drawer",
        "I have a damaged electronic device",
        "May sirang printer at computer accessories kami",

        # Multi-material messages
        "I have plastic bottles and aluminum cans",
        "May dyaryo at mga kahon ng karton kami",
        "We collected glass jars and plastic containers",
        "May bakal at tansong wire ako",
        "I have cardboard boxes and paper bags",
        "May aluminum cans at glass bottles kami",
        "These plastic containers and cardboard cartons are for sale",
        "May lumang papel at sirang electronic cables ako",
        "I collected steel pipes and aluminum scraps",
        "May plastic bottles, karton, at lumang diyaryo kami",
        "We have glass bottles and old metal brackets",
        "May aluminum trays at plastic cups kami",
        "I have copper wire and broken computer parts",
        "May mga garapong salamin at paper bags kami",
        "There are cardboard boxes, plastic pails, and aluminum cans",
        "May bakal, papel, at plastic packaging kami",
        "I want to sell glass jars and cardboard cartons",
        "May lumang charger at bakal na piyesa ako",
        "We have paper sheets, glass containers, and plastic bottles",
        "May aluminum cans, karton, at copper wire kami",

        # Informal and less direct wording
        "May mga bote at lata ako, puwede ba rito?",
        "I have a sack of recyclables from our house",
        "May mga lumang gamit akong gustong ipabenta",
        "Can someone collect the materials I sorted yesterday?",
        "May halo-halong recyclables sa garahe namin",
        "I found some old metal parts in the storage room",
        "May mga lalagyan at kahon akong naipon",
        "Can I bring my sorted waste materials to your shop?",
        "May mga gamit mula sa repair shop na ibebenta ko",
        "I have different recyclable items but haven't sorted them",

        # Ambiguous descriptions
        "May mga bote ako",
        "I have some old containers",
        "May mga lata sa bahay",
        "Can you buy these old items?",
        "May mga kahon akong ibebenta",
        "I found some pieces in the garage",
        "May mga lumang gamit sa sako",
        "Can you identify these materials?",
        "May halo-halong bagay ako pero hindi ko alam ang materyal",
        "I'm not sure what these items are made of",
        
        # Long Message Tests

        # Test 1 — Plastic
        "Good morning po! Naglilinis kasi kami ng bahay ngayong weekend, and I found several empty shampoo bottles, plastic water bottles, food containers, and old plastic pails in our storage area. Gusto sana naming ibenta yung mga puwede pang i-recycle instead of throwing everything away. Do you accept these kinds of plastic materials?",

        # Test 2 — Paper and Cardboard
        "Hello! Our small store recently received a lot of new supplies, so we have many empty delivery boxes, cardboard cartons, paper bags, old newspapers, and used office papers piling up in the stockroom. Most of them are still dry and clean. I would like to know if your junkshop accepts these materials because we want to clear some space before the next delivery arrives.",

        # Test 3 — Aluminum
        "Hi po, we had a family gathering last week, and after cleaning up, we collected a lot of empty soda cans, aluminum food trays, and some old aluminum kitchen utensils. Some cans are already crushed, while the others are still in their original shape. We have separated them from the plastic bottles and glass jars. Can we bring the aluminum items to your shop for recycling?",

        # Test 4 — Other Metals
        "Good afternoon! May mga natira kaming materials pagkatapos ng renovation sa bahay. I found several rusty iron bars, old steel pipes, metal brackets, and a few copper wires from the electrical repair. Hindi ko pa alam kung magkano ang halaga ng mga ito, pero gusto ko munang malaman kung tinatanggap ninyo ang mga ganitong klase ng metal scrap bago ko dalhin lahat sa junkshop.",

        # Test 5 — Glass
        "Hello po! We run a small food business, and we have accumulated many empty glass sauce jars, juice bottles, vinegar bottles, and glass containers from our products. We already removed the remaining food and washed most of them. May ilang bote na may labels pa, pero glass naman ang mismong lalagyan. Do you accept these for recycling, and should we separate them according to their size?",

        # Test 6 — Electronic Waste
        "Hi, I was cleaning an old computer workstation and found several unused electronic items that no longer work properly. These include a damaged computer mouse, an old keyboard, broken phone chargers, earphones, a router, and a few circuit boards from an outdated desktop computer. Some accessories still turn on, but most are defective. I want to dispose of them responsibly instead of mixing them with ordinary household waste. Do you accept electronic waste?",

        # Test 7 — Multiple Materials: Plastic, Paper, and Aluminum
        "Good morning po! Our family recently cleaned the garage, and we found several bags containing different recyclable materials. There are empty plastic detergent containers, plastic drinking bottles, old newspapers, used notebooks, flattened cardboard boxes, and aluminum soda cans. We have already placed the items in separate piles, but I am not sure whether your shop accepts all of them. Which of these materials can I bring for recycling?",

        # Test 8 — Multiple Materials: Glass, Other Metals, and Electronic Waste
        "Hello! We are clearing out a small repair shop that has not been used for several months. While sorting the storage area, we found empty glass jars, broken glass bottles, old steel brackets, copper wires, damaged chargers, and circuit boards from some electronic equipment. May mga gamit din na hindi na namin matukoy kung saan nanggaling, so those are separated for now. I mainly want to know if you accept the glass, metal scraps, and electronic parts.",

        # Test 9 — Long Message with Distracting Details: Cardboard and Plastic
        "Hi po! I am helping my parents organize our sari-sari store because we need more space for new products arriving next week. We spent almost the whole morning arranging shelves, cleaning the floor, and checking the remaining inventory. During the cleanup, we collected many empty cardboard product boxes, shipping cartons, plastic packaging, and large plastic containers. Some boxes have printed designs, while others are plain brown cardboard. We also found a few reusable bags, but I am not sure if those should be included. Can we sell the cardboard and plastic items at your junkshop?",

        # Test 10 — Ambiguous Long Message
        "Good afternoon! We recently moved some things out of our old storage room and discovered several sacks of items that have been sitting there for years. Some are containers, some are boxes, and others are small pieces of different shapes. I cannot remember where most of them came from, and I do not know what materials they are made of. A few items feel heavy, while others are lightweight, but I have not checked them carefully. I would like to bring everything to your shop and ask whether any of it can be recycled.",

    ]

    for message in test_messages:
        print(f"\nMessage: {message}")
        print("Predictions:", classify_material(message, saved))


if __name__ == "__main__":
    main()