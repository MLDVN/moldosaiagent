# ai_agent_utils.py
import json
import os
import requests
from openai import OpenAI
import gspread
from datetime import datetime

# --- Variabile de Mediu ---
# Acestea vor fi încărcate automat de Vercel din setările proiectului
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo") # Modelul OpenAI implicit
GOOGLE_SHEETS_URL = os.environ.get("GOOGLE_SHEETS_URL")

# Calea către fișierul JSON de credențiale Google Sheets (PENTRU TESTARE LOCALĂ)
# Această cale este relativă la fișierul curent (ai_agent_utils.py)
LOCAL_GCREDS_PATH = os.path.join(os.path.dirname(__file__), "gsheets_creds_bot.json")


# --- Google Sheets Integration ---
gc = None # Obiectul client gspread, va fi inițializat o singură dată

def get_gspread_client():
    """
    Returnează un client gspread autentificat.
    Autentificarea se face o singură dată la prima solicitare a funcției.
    """
    global gc
    if gc is None:
        # Vedem dacă suntem în modul de dezvoltare locală ȘI dacă fișierul local de credențiale există
        if os.environ.get("FLASK_ENV") == "development" and os.path.exists(LOCAL_GCREDS_PATH):
            # Citim direct din fișierul local pentru dezvoltare
            try:
                gc = gspread.service_account(filename=LOCAL_GCREDS_PATH)
                print(f"gspread client authenticated from local file: {LOCAL_GCREDS_PATH}")
            except Exception as e:
                # Logăm eroarea specifică de fișier
                print(f"ERROR: Failed to authenticate gspread from local file '{LOCAL_GCREDS_PATH}': {e}")
                raise ValueError("Could not authenticate Google Sheets from local file. Check path and permissions.")
        else:
            # Folosim variabila de mediu GOOGLE_SHEETS_CREDENTIALS_JSON pentru producție (Vercel)
            GOOGLE_SHEETS_CREDENTIALS_JSON = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
            if not GOOGLE_SHEETS_CREDENTIALS_JSON:
                raise ValueError("GOOGLE_SHEETS_CREDENTIALS variable not set for production. (or FLASK_ENV/LOCAL_GCREDS_PATH issue)")
            try:
                creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS_JSON)
                gc = gspread.service_account_from_dict(creds_dict)
                print("gspread client authenticated successfully from environment variable.")
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in GOOGLE_SHEETS_CREDENTIALS environment variable: {e}")
            except Exception as e:
                raise Exception(f"Failed to authenticate gspread from environment variable: {e}")
    return gc

def get_worksheet(sheet_name, url=GOOGLE_SHEETS_URL):
    """Obține o foaie de lucru specifică dintr-un Google Sheet."""
    if not url:
        raise ValueError("GOOGLE_SHEETS_URL variable not set. Cannot access Google Sheet.")
    try:
        client = get_gspread_client()
        spreadsheet = client.open_by_url(url)
        worksheet = spreadsheet.worksheet(sheet_name)
        return worksheet
    except Exception as e:
        print(f"Error getting worksheet '{sheet_name}' from URL '{url}': {e}")
        raise

def get_gsheet_data(sheet_name):
    """Citește toate datele dintr-o foaie Google Sheet."""
    try:
        ws = get_worksheet(sheet_name)
        return ws.get_all_values()
    except Exception as e:
        print(f"Error reading data from sheet '{sheet_name}': {e}")
        return []

def send_message_to_worksheet(sheet_name, msg_list):
    """
    Scrie o listă de mesaje în Google Sheet (folosit pentru loguri).
    Adaugă rânduri noi folosind append_row, care este mai robust decât update.
    """
    try:
        ws = get_worksheet(sheet_name)
        for row in msg_list:
            ws.append_row(row)
        print(f"Data appended to sheet '{sheet_name}'.")
    except Exception as e:
        print(f"Error sending message to worksheet '{sheet_name}': {e}. Please ensure sheet exists and permissions are correct.")
        raise


# --- Gestionarea Istoricului Conversației în Google Sheets ---
CONVERSATION_SHEET_NAME = "UserConversations"

def get_conversation_history_gsheet(sender_id, max_messages=10):
    try:
        ws = get_worksheet(CONVERSATION_SHEET_NAME)
        cell = ws.find(sender_id, in_column=1)

        if cell:
            conversation_json_str = ws.cell(cell.row, 2).value
            if conversation_json_str:
                conversation = json.loads(conversation_json_str)
                return conversation[-max_messages:]
        return []
    except Exception as e:
        print(f"Error getting conversation history from GSheet for {sender_id}: {e}")
        return []

def save_conversation_gsheet(sender_id, conversation):
    try:
        ws = get_worksheet(CONVERSATION_SHEET_NAME)
        conversation_json_str = json.dumps(conversation)

        cell = ws.find(sender_id, in_column=1)

        if cell:
            ws.update_cell(cell.row, 2, conversation_json_str)
            print(f"Updated conversation history for {sender_id} in GSheet at row {cell.row}.")
        else:
            ws.append_row([sender_id, conversation_json_str])
            print(f"Created new conversation history for {sender_id} in GSheet.")
    except Exception as e:
        print(f"Error saving conversation to GSheet for {sender_id}: {e}")


# --- Agentul AI (OpenAI) ---
# Aici am eliminat parametrul 'ws' din semnătura funcției, deoarece 'SMAB' e hardcodat
def get_bot_response(sender_id, user_message):
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set. Cannot get response from OpenAI.")

    client = OpenAI(api_key=OPENAI_API_KEY)

    # 1. Obține lista FAQs din Google Sheets (folosind numele foii direct)
    faqs_ws = 'BuyTech'
    faqs_data = get_gsheet_data(faqs_ws)
    faqs_str = ""
    if len(faqs_data) > 1:
        faqs_str = '\n'.join([f"Întrebare: {f[0]}, Răspuns: {f[1]}" for f in faqs_data[1:] if len(f) >= 2])
        print(f"FAQs loaded from Google Sheet '{faqs_ws}'.")
    else:
        print(f"No FAQs found or sheet '{faqs_ws}' is empty.")

    # 2. Obține lista de produse (folosind numele foii direct)
    products_data = get_gsheet_data('Products')
    products_str = ""
    if len(products_data) > 1:
        products_str = '[' + '\n'.join([f"Nume produs: {p[0]}, Pret: {p[1]} {p[4]}" for p in products_data[1:] if len(p) >= 5]) + ']'
        print("Products loaded from Google Sheet 'Products'.")
    else:
        print("No products found or sheet 'Products' is empty.")

    system_message = (
        "Ești un asistent util pentru o burgerie numită 'Burger Mania'. "
        "Folosește următoarele informații pentru a răspunde:\n"
        f"**Întrebări frecvente**:\n{faqs_str}\n\n"
        f"**Listă Produse**:\n{products_str}\n"
        f"**Comenzi**:[Procesul de comanda include preluarea adresei de livrare, numărul de telefon și ce produse dorește clientul. Nu avem încă implementat un sistem de plata direct, ci doar de preluare comanda, așadar la final de conversație amintește că plata se face la livrare cu cardul sau cash.]\n\n"
        "Răspunde clar, concis și bazat doar pe informațiile furnizate. "
        "Încearcă să-l ghidezi spre una dintre opțiuni sau la final să-l întrebi dacă mai are alte întrebări."
        "Dacă nu știi răspunsul, spune că vei verifica cu echipa și oferă un număr de telefon (ex. 07xx-xxx-xxx) sau adresa de email (ex. contact@burgeriemania.ro) pentru contact direct."
    )

    conversation_history = get_conversation_history_gsheet(sender_id)

    messages = []
    messages.append({'role': 'system', 'content': system_message})
    messages.extend(conversation_history)
    messages.append({'role': 'user', 'content': user_message})

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=1000,
            temperature=0.7
        )
        bot_response_content = response.choices[0].message.content.strip()

        conversation_history.append({'role': 'user', 'content': user_message})
        conversation_history.append({'role': 'assistant', 'content': bot_response_content})
        save_conversation_gsheet(sender_id, conversation_history)

        print(f"\nConversația pentru {sender_id} (trimisă la OpenAI): {messages}")
        print(f"Răspunsul botului: {bot_response_content}")
        return bot_response_content

    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return "Ne pare rău, am o problemă tehnică momentan. Te rog să încerci din nou mai târziu."
