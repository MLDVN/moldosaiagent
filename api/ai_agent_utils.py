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
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo") # Modelul OpenAI
model = "gpt-4o-mini"  # Sau 'gpt-3.5-turbo' pentru costuri mai mici
# GOOGLE_SHEETS_CREDENTIALS_JSON = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
GOOGLE_SHEETS_CREDENTIALS_JSON = 'C:/Users/vladm/work/ai_stuff/gsheets_creds_bot.json'
# GOOGLE_SHEETS_URL = os.environ.get("GOOGLE_SHEETS_URL")
GOOGLE_SHEETS_URL = "https://docs.google.com/spreadsheets/d/1KZUSKyTtK5n_58MdOvwsEm9AX2ElauYbJq27DxLGluo"

# --- Google Sheets Integration ---
gc = None # Obiectul client gspread

def get_gspread_client():
    """
    Returnează un client gspread autentificat.
    Autentificarea se face o singură dată la prima solicitare.
    """
    global gc
    if gc is None:
        if not GOOGLE_SHEETS_CREDENTIALS_JSON:
            raise ValueError("GOOGLE_SHEETS_CREDENTIALS variable not set.")
        try:
            creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS_JSON)
            gc = gspread.service_account_from_dict(creds_dict)
            print("gspread client authenticated.")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in GOOGLE_SHEETS_CREDENTIALS: {e}")
        except Exception as e:
            raise Exception(f"Failed to authenticate gspread: {e}")
    return gc

def get_worksheet(sheet_name, url=GOOGLE_SHEETS_URL):
    """Obține o foaie de lucru specifică dintr-un Google Sheet."""
    if not url:
        raise ValueError("GOOGLE_SHEETS_URL variable not set.")
    try:
        client = get_gspread_client()
        spreadsheet = client.open_by_url(url)
        worksheet = spreadsheet.worksheet(sheet_name)
        return worksheet
    except Exception as e:
        print(f"Error getting worksheet '{sheet_name}': {e}")
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
    """Scrie o listă de mesaje în Google Sheet, adăugându-le la datele existente."""
    try:
        ws = get_worksheet(sheet_name)
        # Folosim append_row pentru a adăuga rânduri noi, este mai eficient
        for row in msg_list:
            # Adăugăm și un timestamp pentru log-uri
            row_with_timestamp = row + [datetime.now().isoformat()]
            ws.append_row(row_with_timestamp)
        print(f"Data appended to sheet '{sheet_name}'.")
    except Exception as e:
        print(f"Error sending message to worksheet '{sheet_name}': {e}")
        raise # Răspândim eroarea pentru a fi tratată în index.py


# --- Gestionarea Istoricului Conversației în Google Sheets ---
CONVERSATION_SHEET_NAME = "ChatBotLogs" # Numele foii pentru istoricul conversațiilor

def get_conversation_history_gsheet(sender_id, max_messages=10):
    """
    Recuperează istoricul conversației pentru un utilizator din Google Sheets.
    Returnează o listă de dicționare {'role': ..., 'content': ...}.
    """
    try:
        ws = get_worksheet(CONVERSATION_SHEET_NAME)
        # Căutăm rândul corespunzător sender_id-ului
        # Această metodă este eficientă pentru căutări unice
        cell = ws.find(sender_id, in_column=1) # Căutăm în prima coloană (SenderID)

        if cell:
            # Dacă sender_id-ul este găsit, citim conținutul coloanei ConversationHistory
            # Presupunem că ConversationHistory este a 2-a coloană (index 2)
            conversation_json_str = ws.cell(cell.row, cell.col + 1).value
            if conversation_json_str:
                conversation = json.loads(conversation_json_str)
                # Limităm numărul de mesaje pentru a controla tokenii OpenAI
                return conversation[-max_messages:]
        return [] # Returnăm listă goală dacă nu s-a găsit sau nu există istoric
    except Exception as e:
        print(f"Error getting conversation history from GSheet for {sender_id}: {e}")
        # În caz de eroare, tratăm ca și cum nu ar exista istoric
        return []

def save_conversation_gsheet(sender_id, conversation):
    """
    Salvează sau actualizează istoricul conversației pentru un utilizator în Google Sheets.
    """
    try:
        ws = get_worksheet(CONVERSATION_SHEET_NAME)
        conversation_json_str = json.dumps(conversation)

        cell = ws.find(sender_id, in_column=1) # Căutăm în prima coloană (SenderID)

        if cell:
            # Actualizăm rândul existent
            # gs.update_cell(row, col, value)
            ws.update_cell(cell.row, cell.col + 1, conversation_json_str)
            print(f"Updated conversation history for {sender_id} in GSheet.")
        else:
            # Adăugăm un rând nou dacă utilizatorul nu există
            ws.append_row([sender_id, conversation_json_str])
            print(f"Created new conversation history for {sender_id} in GSheet.")
    except Exception as e:
        print(f"Error saving conversation to GSheet for {sender_id}: {e}")
        # Logăm eroarea, dar nu o aruncăm pentru a nu bloca răspunsul botului


# --- Agentul AI (OpenAI) ---
def get_bot_response(sender_id, user_message):
    """
    Extrage răspunsul de la OpenAI, incluzând istoricul conversației
    și baza de cunoștințe din Google Sheets.
    """
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set.")

    client = OpenAI(api_key=OPENAI_API_KEY)

    # 1. Obține lista FAQs din Google Sheets
    faqs_data = get_gsheet_data('SMAB') # Presupunem că 'SMAB' e numele foii cu FAQs
    faqs_str = ""
    if len(faqs_data) > 1: # Ignorăm rândul de antet (presupunem că primul rând e antet)
        faqs_str = '\n'.join([f"Întrebare: {f[0]}, Răspuns: {f[1]}" for f in faqs_data[1:] if len(f) >= 2])
        print("FAQs loaded from Google Sheet.")
    else:
        print("No FAQs found or sheet 'SMAB' is empty.")


    # 2. Obține lista de produse (dacă este cazul)
    products_data = get_gsheet_data('Products') # Presupunem că 'Products' e numele foii cu produse
    products_str = ""
    if len(products_data) > 1:
        # Asigură-te că rândurile au suficiente coloane pentru a evita IndexError
        products_str = '[' + '\n'.join([f"Nume produs: {p[0]}, Pret: {p[1]} {p[4]}" for p in products_data[1:] if len(p) >= 5]) + ']'
        print("Products loaded from Google Sheet.")
    else:
        print("No products found or sheet 'Products' is empty.")

    # 3. Creează mesajul de sistem cu baza de cunoștințe
    # system_message = (
    #     "Ești un asistent util pentru o burgerie numită 'Burger Mania'. "
    #     "Folosește următoarele informații pentru a răspunde:\n"
    #     f"**Întrebări frecvente**:\n{faqs_str}\n\n"
    #     f"**Listă Produse**:\n{products_str}\n"
    #     f"**Comenzi**:[Procesul de comanda include preluarea adresei de livrare, numarul de telefon si ce produse doreste clientul. Nu avem inca implementat un sistem de plata direct, ci doar de preluare comanda, asadar la final de conversatie aminteste ca plata se face la livrare cu cardul sau cash.]\n\n"
    #     "Răspunde clar, concis și bazat doar pe informațiile furnizate. "
    #     "Incearca sa il ghidezi spre una dintre optiuni sau la final sa il intrebi daca mai are alte intrebari."
    #     "Dacă nu știi răspunsul, spune că vei verifica cu echipa și oferă un număr de telefon (ex. 07xx-xxx-xxx) sau adresa de email (ex. contact@burgeriemania.ro) pentru contact direct."
    # )
    system_message = (
        "Ești un asistent util pentru compania noastra. "
        "Folosește următoarele informații pentru a răspunde:\n"
        f"**Întrebări frecvente**:\n{faqs}\n\n"
        f"**Listă Produse**:\n{products}\n"
        f"**Comenzi**:[--soon--]\n\n"
        "Răspunde clar, concis și bazat doar pe informațiile furnizate. "
        "Incearca sa il ghidezi spre una dintre optiuni."
        "Dacă nu știi răspunsul, spune că vei verifica cu echipa."
    )

    # 4. Recuperează istoricul conversației din Google Sheets
    conversation_history = get_conversation_history_gsheet(sender_id)

    # 5. Construiește lista de mesaje pentru OpenAI API
    messages = []
    # Adaugă mesajul de sistem
    messages.append({'role': 'system', 'content': system_message})
    # Adaugă istoricul conversației
    messages.extend(conversation_history)
    # Adaugă mesajul curent al utilizatorului
    messages.append({'role': 'user', 'content': user_message})

    # 6. Apel la OpenAI API
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=1000,
            temperature=0.7
        )
        bot_response_content = response.choices[0].message.content.strip()

        # 7. Salvează mesajul utilizatorului și răspunsul botului în istoricul Google Sheets
        # Actualizăm lista de mesaje înainte de a o salva
        conversation_history.append({'role': 'user', 'content': user_message})
        conversation_history.append({'role': 'assistant', 'content': bot_response_content})
        save_conversation_gsheet(sender_id, conversation_history)

        print(f"\nConvo for {sender_id}: {messages}")
        return bot_response_content

    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return "Ne pare rău, am o problemă tehnică momentan. Te rog să încerci din nou mai târziu."
