# api/index.py
import json
import os
from flask import Flask, request, jsonify
import requests
from datetime import datetime # Importăm datetime pentru timestamp-uri în log

# Importăm logica agentului AI din fișierul separat
from .ai_agent_utils import get_bot_response, send_message_to_worksheet

app = Flask(__name__)

# Variabile de mediu (setate pe Vercel)
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")

# --- Rută Rădăcină Opțională pentru testare în browser ---
@app.route("/", methods=["GET"])
def home():
    """
    Rută simplă pentru a verifica dacă aplicația rulează.
    Va returna un mesaj atunci când accesezi URL-ul Vercel direct din browser (fără /api/webhook).
    """
    return jsonify({"status": "running", "message": "Chatbot-ul este activ și așteaptă mesaje pe /api/webhook"}), 200
# --- Sfârșit rută rădăcină opțională ---


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
                                # Verificăm tipul de mesaj. Ne interesează mesajele text.
                                # Poți adăuga logica pentru alte tipuri (imagini, audio, etc.) dacă e necesar.
                                if message.get("type") == "text":
                                    sender_id = message["from"]
                                    user_message_text = message["text"]["body"]

                                    print(f"Received message from {sender_id}: {user_message_text}")

                                    # Apelăm funcția agentului AI pentru a obține răspunsul
                                    # Aceasta se va ocupa de istoricul conversației și knowledge base.
                                    bot_response_text = get_bot_response(sender_id, user_message_text)

                                    # Salvăm mesajul utilizatorului și răspunsul botului în Google Sheet-uri pentru log
                                    try:
                                        # Data și ora pentru log
                                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        send_message_to_worksheet("ChatBotLogs", [[sender_id, user_message_text, bot_response_text, timestamp]])
                                        print("Message logged to Google Sheet 'ChatBotLogs'.")
                                    except Exception as gs_e:
                                        print(f"Error logging to Google Sheet 'ChatBotLogs': {gs_e}")

                                    # Trimitem răspunsul înapoi către utilizator prin API-ul Meta
                                    send_meta_message(sender_id, bot_response_text)
                                elif message.get("type") == "button":
                                    # Exemplu de gestionare a răspunsurilor de la butoane (dacă folosești butoane rapide WhatsApp)
                                    sender_id = message["from"]
                                    button_payload = message["button"]["payload"]
                                    print(f"Received button click from {sender_id}: {button_payload}")
                                    # Aici poți adăuga logică pentru a răspunde la click-uri pe butoane
                                    send_meta_message(sender_id, f"Ai apăsat: {button_payload}. Îți pot fi de ajutor cu altceva?")
                                else:
                                    print(f"Received unsupported message type: {message.get('type')}")
                                    sender_id = message["from"]
                                    send_meta_message(sender_id, "Scuze, pot procesa doar mesaje text momentan. Te rog să îmi scrii întrebarea ta.")

        except Exception as e:
            print(f"Error processing webhook data: {e}")
            # Este esențial să returnăm 200 OK către Meta chiar și în caz de eroare,
            # pentru a evita reîncercările multiple ale aceluiași mesaj.
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
        "messaging_product": "whatsapp", # Lasă "whatsapp" pentru WhatsApp. Schimbă la "instagram" pentru Instagram.
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

# Pentru testare locală (rulează `python api/index.py`)
# Această secțiune NU este folosită în producție pe Vercel, unde variabilele de mediu sunt setate separat.
if __name__ == "__main__":
    # Setează variabilele de mediu pentru testarea locală
    # Asigură-te că acestea sunt doar pentru dezvoltare locală și NU le lași în Git!
    os.environ["VERIFY_TOKEN"] = "un_token_secret_pentru_test" # Alege-ți propriul token
    os.environ["META_ACCESS_TOKEN"] = "YOUR_META_ACCESS_TOKEN_FOR_LOCAL_TESTING" # Token de test Meta
    os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "YOUR_WHATSAPP_PHONE_NUMBER_ID" # ID-ul numărului tău de test din Meta Developers
    os.environ["OPENAI_API_KEY"] = "sk-YOUR_OPENAI_API_KEY" # Cheia ta OpenAI
    # Credențialele Google Sheets ca JSON string, pe o singură linie
    # Înlocuiește cu conținutul real al fișierului JSON, transformat într-un string pe o linie.
    os.environ["GOOGLE_SHEETS_CREDENTIALS"] = json.dumps({"type": "service_account", "project_id": "your-project-id", "private_key_id": "...", "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n", "client_email": "...", "client_id": "...", "auth_uri": "...", "token_uri": "...", "auth_provider_x509_cert_url": "...", "client_x509_cert_url": "..."})
    os.environ["GOOGLE_SHEETS_URL"] = "https://docs.google.com/spreadsheets/d/YOUR_GOOGLE_SHEET_ID/edit"

    app.run(debug=True, port=os.environ.get("PORT", 5000))