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
GOOGLE_SHEETS_CREDENTIALS_JSON = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
GOOGLE_SHEETS_URL = os.environ.get("GOOGLE_SHEETS_URL")
DEFAULT_WS = "BuyTech"

# --- Google Sheets Integration ---
gc = None # Obiectul client gspread, va fi inițializat o singură dată

def get_gspread_client():
    global gc
    if gc is None:
        # Folosim variabila de mediu GOOGLE_SHEETS_CREDENTIALS_JSON pentru producție (Vercel)
        GOOGLE_SHEETS_CREDENTIALS_JSON = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
        if not GOOGLE_SHEETS_CREDENTIALS_JSON:
            raise ValueError("GOOGLE_SHEETS_CREDENTIALS variable not set for production.")
        try:
            creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS_JSON)
            gc = gspread.service_account_from_dict(creds_dict)
            print("gspread client authenticated from environment variable.")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in GOOGLE_SHEETS_CREDENTIALS: {e}")
        except Exception as e:
            raise Exception(f"Failed to authenticate gspread: {e}")
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
        # Returnăm o listă goală pentru a permite execuția programului chiar dacă citirea eșuează
        return []

def send_message_to_worksheet(sheet_name, msg_list):
    """
    Scrie o listă de mesaje în Google Sheet (folosit pentru loguri).
    Adaugă rânduri noi folosind append_row, care este mai robust decât update.
    """
    try:
        ws = get_worksheet(sheet_name)
        for row in msg_list:
            ws.append_row(row) # msg_list ar trebui să conțină rânduri deja formatate
        print(f"Data appended to sheet '{sheet_name}'.")
    except Exception as e:
        print(f"Error sending message to worksheet '{sheet_name}': {e}")
        # Ridicăm excepția pentru a permite gestionarea erorilor în funcția apelantă (index.py)
        raise


# --- Gestionarea Istoricului Conversației în Google Sheets ---
CONVERSATION_SHEET_NAME = "UserConversations" # Numele foii pentru istoricul conversațiilor

def get_conversation_history_gsheet(sender_id, max_messages=10):
    """
    Recuperează istoricul conversației pentru un utilizator din Google Sheets.
    Returnează o listă de dicționare {'role': ..., 'content': ...}.
    """
    try:
        ws = get_worksheet(CONVERSATION_SHEET_NAME)
        # Căutăm rândul corespunzător sender_id-ului în prima coloană
        # ws.find() este destul de eficient pentru căutări unice
        cell = ws.find(sender_id, in_column=1)

        if cell:
            # Dacă sender_id-ul este găsit, citim conținutul coloanei ConversationHistory (coloana B, index 2)
            conversation_json_str = ws.cell(cell.row, 2).value # Coloana B are indexul 2
            if conversation_json_str:
                conversation = json.loads(conversation_json_str)
                # Limităm numărul de mesaje pentru a controla tokenii trimiși către OpenAI
                return conversation[-max_messages:]
        return [] # Returnăm listă goală dacă nu s-a găsit sau nu există istoric
    except Exception as e:
        print(f"Error getting conversation history from GSheet for {sender_id}: {e}")
        # În caz de eroare, tratăm ca și cum nu ar exista istoric pentru a nu bloca botul
        return []

def save_conversation_gsheet(sender_id, conversation):
    """
    Salvează sau actualizează istoricul conversației pentru un utilizator în Google Sheets.
    """
    try:
        ws = get_worksheet(CONVERSATION_SHEET_NAME)
        # Transformăm lista de mesaje într-un string JSON
        conversation_json_str = json.dumps(conversation)

        # Căutăm dacă utilizatorul există deja
        cell = ws.find(sender_id, in_column=1)

        if cell:
            # Actualizăm celula existentă cu noul istoric
            ws.update_cell(cell.row, 2, conversation_json_str) # Coloana B are indexul 2
            print(f"Updated conversation history for {sender_id} in GSheet at row {cell.row}.")
        else:
            # Dacă utilizatorul nu există, adăugăm un rând nou
            # Asigură-te că foaia UserConversations are anteturile SenderID și ConversationHistory
            ws.append_row([sender_id, conversation_json_str])
            print(f"Created new conversation history for {sender_id} in GSheet.")
    except Exception as e:
        print(f"Error saving conversation to GSheet for {sender_id}: {e}")
        # Logăm eroarea, dar nu o aruncăm pentru a nu bloca răspunsul botului


# --- Agentul AI (OpenAI) ---
def get_bot_response(sender_id, user_message, ws=DEFAULT_WS):
    """
    Extrage răspunsul de la OpenAI, incluzând istoricul conversației
    și baza de cunoștințe din Google Sheets.
    """
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set. Cannot get response from OpenAI.")

    client = OpenAI(api_key=OPENAI_API_KEY)

    # 1. Obține lista FAQs din Google Sheets
    # ws ar trebui să aibă coloana 0 = Întrebare, coloana 1 = Răspuns
    faqs_data = get_gsheet_data(ws)
    faqs_str = ""
    if len(faqs_data) > 1:
        # Excludem rândul de antet (primul rând) și verificăm dacă există suficiente coloane
        faqs_str = '\n'.join([f"Întrebare: {f[0]}, Răspuns: {f[1]}" for f in faqs_data[1:] if len(f) >= 2])
        print(f"FAQs loaded from Google Sheet '{ws}'.")
    else:
        print(f"No FAQs found or sheet '{ws}' is empty.")


    # 2. Obține lista de produse (dacă este cazul)
    # 'Products' ar trebui să aibă coloana 0 = Nume produs, coloana 1 = Pret, coloana 4 = Moneda
    products_data = get_gsheet_data('Products')
    products_str = ""
    if len(products_data) > 1:
        # Excludem rândul de antet și verificăm dacă există suficiente coloane
        products_str = '[' + '\n'.join([f"Nume produs: {p[0]}, Pret: {p[1]} {p[4]}" for p in products_data[1:] if len(p) >= 5]) + ']'
        print("Products loaded from Google Sheet 'Products'.")
    else:
        print("No products found or sheet 'Products' is empty.")

    # 3. Creează mesajul de sistem cu baza de cunoștințe
    system_message = (
        "Ești un asistent util pentru o burgerie numită 'Burger Mania'. "
        "Folosește următoarele informații pentru a răspunde:\n"
        f"**Întrebări frecvente**:\n{faqs_str}\n\n"
        f"**Listă Produse**:\n{products_str}\n"
        f"**Comenzi**:[Procesul de comanda include preluarea adresei de livrare, numărul de telefon și ce produse dorește clientul. Nu avem încă implementat un sistem de plată direct, ci doar de preluare comanda, așadar la final de conversație amintește că plata se face la livrare cu cardul sau cash.]\n\n"
        "Răspunde clar, concis și bazat doar pe informațiile furnizate. "
        "Încearcă să-l ghidezi spre una dintre opțiuni sau la final să-l întrebi dacă mai are alte întrebări."
        "Dacă nu știi răspunsul, spune că vei verifica cu echipa și oferă un număr de telefon (ex. 07xx-xxx-xxx) sau adresa de email (ex. contact@burgeriemania.ro) pentru contact direct."
    )

    # 4. Recuperează istoricul conversației din Google Sheets
    # Inițializăm conversation_history ca o listă mutabilă
    conversation_history = get_conversation_history_gsheet(sender_id)

    # 5. Construiește lista de mesaje pentru OpenAI API
    messages = []
    # Adaugă mesajul de sistem la început
    messages.append({'role': 'system', 'content': system_message})
    # Adaugă istoricul conversației recuperat
    messages.extend(conversation_history)
    # Adaugă mesajul curent al utilizatorului
    messages.append({'role': 'user', 'content': user_message})

    # 6. Apel la OpenAI API
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=1000, # Poți ajusta acest lucru pentru a controla lungimea răspunsurilor
            temperature=0.7 # Poți ajusta acest lucru pentru a controla creativitatea răspunsurilor
        )
        bot_response_content = response.choices[0].message.content.strip()

        # 7. Salvează mesajul utilizatorului și răspunsul botului în istoricul Google Sheets
        # Actualizăm lista de mesaje din memorie înainte de a o salva
        conversation_history.append({'role': 'user', 'content': user_message})
        conversation_history.append({'role': 'assistant', 'content': bot_response_content})
        save_conversation_gsheet(sender_id, conversation_history)

        print(f"\nConversația pentru {sender_id} (trimisă la OpenAI): {messages}")
        print(f"Răspunsul botului: {bot_response_content}")
        return bot_response_content

    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return "Ne pare rău, am o problemă tehnică momentan. Te rog să încerci din nou mai târziu."
