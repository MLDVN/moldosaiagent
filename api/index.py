# api/index.py
import json
import os
from flask import Flask, request, jsonify
import requests

# Importăm logica agentului AI din fișierul separat
# initialize_db nu mai este necesar deoarece nu folosim DB
from .ai_agent_utils import get_bot_response, send_message_to_worksheet #, initialize_db

app = Flask(__name__)

# initialize_db() nu mai este apelat deoarece nu folosim o bază de date externă.
# Logic aici dacă ai avea o inițializare globală non-DB necesară pentru Flask

# Variabile de mediu (setate pe Vercel)
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
# WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_PHONE_NUMBER_ID = '692303190630828'

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    """
    Gestionează cererile webhook de la Meta (WhatsApp/Instagram).
    """
    if request.method == "GET":
        # Verificare webhook (cerută de Meta pentru a valida URL-ul)
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode and token:
            if mode == "subscribe" and token == VERIFY_TOKEN:
                print("WEBHOOK_VERIFIED")
                return challenge, 200
            else:
                print("WEBHOOK_VERIFICATION_FAILED: Token mismatch.")
                return "VERIFICATION_FAILED", 403
        print("WEBHOOK_VERIFICATION_FAILED: Missing parameters.")
        return "Missing parameters", 400

    elif request.method == "POST":
        # Procesează mesajele primite de la Meta
        data = request.get_json()
        print("Received webhook data:", json.dumps(data, indent=2))

        try:
            # Structura Meta pentru webhook-uri poate varia ușor.
            # Acesta este un exemplu pentru mesajele WhatsApp.
            if "entry" in data and data["entry"]:
                for entry in data["entry"]:
                    for change in entry.get("changes", []):
                        if change.get("field") == "messages":
                            for message in change.get("value", {}).get("messages", []):
                                if message.get("type") == "text":
                                    sender_id = message["from"]
                                    user_message_text = message["text"]["body"]

                                    print(f"Received message from {sender_id}: {user_message_text}")

                                    # Apelăm funcția agentului AI pentru a obține răspunsul
                                    # Aceasta se va ocupa de istoricul conversației și knowledge base.
                                    bot_response_text = get_bot_response(sender_id, user_message_text)

                                    # Salvăm mesajul utilizatorului și răspunsul botului în Google Sheet-uri pentru log
                                    # Asigură-te că send_message_to_worksheet gestionează excepțiile intern
                                    try:
                                        # Data și ora pentru log
                                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        send_message_to_worksheet("ChatBotLogs", [[user_message_text, bot_response_text, timestamp]])
                                        print("Message logged to Google Sheet.")
                                    except Exception as gs_e:
                                        print(f"Error logging to Google Sheet: {gs_e}")

                                    # Trimitem răspunsul înapoi către utilizator prin API-ul Meta
                                    send_meta_message(sender_id, bot_response_text)
                                elif message.get("type") == "button":
                                    # Exemplu de gestionare a răspunsurilor de la butoane
                                    sender_id = message["from"]
                                    button_payload = message["button"]["payload"]
                                    print(f"Received button click from {sender_id}: {button_payload}")
                                    # Aici poți adăuga logică pentru a răspunde la click-uri pe butoane
                                    send_meta_message(sender_id, f"Ai apăsat: {button_payload}")
                                else:
                                    print(f"Received unsupported message type: {message.get('type')}")
                                    sender_id = message["from"]
                                    send_meta_message(sender_id, "Scuze, pot procesa doar mesaje text momentan.")

        except Exception as e:
            print(f"Error processing webhook data: {e}")
            # Răspunsul la Meta ar trebui să fie întotdeauna 200 OK pentru a evita reîncercările
            return jsonify({"status": "error", "message": str(e)}), 200

        return "OK", 200

def send_meta_message(to, text):
    """
    Trimite un mesaj text înapoi către utilizatorul WhatsApp/Instagram.
    Ajustează URL-ul și "messaging_product" pentru Instagram dacă este cazul.
    """
    # Pentru WhatsApp Cloud API
    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp", # Sau "instagram" pentru Instagram
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status() # Aruncă excepție pentru coduri de status HTTP eronate
        print(f"Message sent successfully to {to}: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send message to {to}: {e}")

# Pentru testare locală (nu se folosește în producție pe Vercel)
if __name__ == "__main__":
    # Setează variabilele de mediu pentru testarea locală
    os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "692303190630828"
    app.run(debug=True, port=os.environ.get("PORT", 5000))

