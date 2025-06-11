# api/index.py
import json
import os
from flask import Flask, request, jsonify
import requests
from datetime import datetime

# --- IMPORTANT: Importul pentru Vercel (Production) ---
# Acest import trebuie să fie relativ pentru ca Vercel să găsească fișierul
# ai_agent_utils.py în același pachet 'api'.
from .ai_agent_utils import get_bot_response, send_message_to_worksheet


app = Flask(__name__)

# Variabile de mediu (setate pe Vercel)
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")


# --- Rută Rădăcină Opțională pentru testare în browser (pe /api) ---
# Aceasta va mapa la https://domeniul-tau.vercel.app/api
@app.route("/api", methods=["GET"])
def api_root():
    """
    Rută simplă pentru a verifica dacă aplicația rulează.
    Va returna un mesaj atunci când accesezi URL-ul Vercel cu /api la final.
    """
    return jsonify({"status": "running", "message": "Chatbot-ul este activ și așteaptă mesaje pe /api/webhook"}), 200


# --- Ruta webhook corectă ---
# Aceasta va mapa la https://domeniul-tau.vercel.app/api/webhook
@app.route("/api/webhook", methods=["GET", "POST"]) # <--- Aceasta este ruta pentru /api/webhook pe Vercel
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
            if "entry" in data and data["entry"]:
                for entry in data["entry"]:
                    for change in entry.get("changes", []):
                        if change.get("field") == "messages":
                            for message in change.get("value", {}).get("messages", []):
                                if message.get("type") == "text":
                                    sender_id = message["from"]
                                    user_message_text = message["text"]["body"]

                                    print(f"Received message from {sender_id}: {user_message_text}")

                                    bot_response_text = get_bot_response(sender_id, user_message_text)

                                    try:
                                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        send_message_to_worksheet("ChatBotLogs", [[sender_id, user_message_text, bot_response_text, timestamp]])
                                        print("Message logged to Google Sheet 'ChatBotLogs'.")
                                    except Exception as gs_e:
                                        print(f"Error logging to Google Sheet 'ChatBotLogs': {gs_e}")

                                    send_meta_message(sender_id, bot_response_text)
                                elif message.get("type") == "button":
                                    sender_id = message["from"]
                                    button_payload = message["button"]["payload"]
                                    print(f"Received button click from {sender_id}: {button_payload}")
                                    send_meta_message(sender_id, f"Ai apăsat: {button_payload}. Îți pot fi de ajutor cu altceva?")
                                else:
                                    print(f"Received unsupported message type: {message.get('type')}")
                                    sender_id = message["from"]
                                    send_meta_message(sender_id, "Scuze, pot procesa doar mesaje text momentan. Te rog să îmi scrii întrebarea ta.")

        except Exception as e:
            print(f"Error processing webhook data: {e}")
            return jsonify({"status": "error", "message": str(e)}), 200

        return "OK", 200

def send_meta_message(to, text):
    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"Message sent successfully to {to}: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send message to {to}: {e}")

# --- Pentru testare locală (rulează `python api/index.py`) ---
if __name__ == "__main__":
    import sys
    import os
    # Adaugă directorul părinte ('moldosaiagent') la PATH-ul Python
    # pentru a permite importul absolut al pachetului 'api'
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # Acum putem importa din pachetul 'api'
    from api.ai_agent_utils import get_bot_response, send_message_to_worksheet

    # Setează variabilele de mediu pentru testarea locală
    os.environ["VERIFY_TOKEN"] = "MoldoAiAgentVerifyToken"
    os.environ["META_ACCESS_TOKEN"] = "YOUR_META_ACCESS_TOKEN_PENTRU_TESTARE_LOCALA"
    os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "YOUR_WHATSAPP_PHONE_NUMBER_ID"
    os.environ["OPENAI_API_KEY"] = "sk-YOUR_OPENAI_API_KEY"
    os.environ["GOOGLE_SHEETS_CREDENTIALS"] = json.dumps({"type": "service_account", "project_id": "...", "private_key_id": "...", "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n", "client_email": "...", "client_id": "...", "auth_uri": "...", "token_uri": "...", "auth_provider_x509_cert_url": "...", "client_x509_cert_url": "..."})
    os.environ["GOOGLE_SHEETS_URL"] = "https://docs.google.com/spreadsheets/d/YOUR_GOOGLE_SHEET_ID/edit"
    os.environ["FLASK_ENV"] = "development"

    app.run(debug=True, port=os.environ.get("PORT", 5000))
