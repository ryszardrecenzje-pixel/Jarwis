import io
import json
import re
import time
import os
from datetime import datetime, date, timedelta
from google import genai
import pandas as pd
from PIL import Image
import streamlit as st
import plotly.express as px

# ── localStorage (Faza 2) ─────────────────────
try:
    from streamlit_local_storage import LocalStorage
    _local_storage = LocalStorage()
    HAS_LOCAL_STORAGE = True
except Exception:
    _local_storage = None
    HAS_LOCAL_STORAGE = False

# ── Google Drive (Faza 3) ─────────────────────
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
    HAS_GOOGLE = True
except Exception:
    HAS_GOOGLE = False

# ──────────────────────────────────────────────
st.set_page_config(
    page_title="Jarwis – Menedżer Paragonów",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

LS_KEY = "jarwis_historia_v1"
DRIVE_FILENAME = "jarwis_historia.json"
DRIVE_FOLDER_NAME = "Jarwis"
HISTORY_VERSION = 1
MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
]
# drive.file = tylko pliki utworzone przez tę aplikację
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.file",
]

# ──────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .main-header {
        background: linear-gradient(135deg, #1e3a5f 0%, #0f766e 100%);
        padding: 1.5rem 2rem; border-radius: 16px; color: white;
        margin-bottom: 1.5rem; box-shadow: 0 8px 24px rgba(15, 118, 110, 0.25);
    }
    .main-header h1 { margin: 0; font-size: 1.9rem; font-weight: 700; }
    .main-header p { margin: 0.4rem 0 0 0; opacity: 0.9; font-size: 1rem; }
    .metric-card {
        background: white; border: 1px solid #e2e8f0; border-radius: 12px;
        padding: 1.1rem 1.3rem; box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        text-align: center; height: 100%;
    }
    .metric-card .label {
        font-size: 0.8rem; color: #64748b; font-weight: 500;
        text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 0.3rem;
    }
    .metric-card .value { font-size: 1.6rem; font-weight: 700; color: #0f172a; }
    .metric-card .unit { font-size: 0.9rem; color: #64748b; font-weight: 500; }
    .stDownloadButton > button {
        background: linear-gradient(135deg, #0f766e, #0d9488) !important;
        color: white !important; border: none !important; border-radius: 10px !important;
        font-weight: 600 !important;
    }
    div[data-testid="stSidebar"] { background: #f8fafc; border-right: 1px solid #e2e8f0; }
    .receipt-badge {
        display: inline-block; background: #ecfdf5; color: #065f46;
        padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="main-header">
        <h1>🧾 Jarwis – Inteligentny Analizator Paragonów</h1>
        <p>Paragony • localStorage • Google Drive • podsumowania kwartalne i półroczne</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────
defaults = {
    "paragony_data": [],
    "processed_files": set(),
    "failed_files": {},
    "storage_loaded": False,
    "storage_status": "",
    "google_creds": None,
    "google_email": None,
    "drive_file_id": None,
    "drive_status": "",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ──────────────────────────────────────────────
# Historia – serializacja
# ──────────────────────────────────────────────
def history_to_serializable(paragony_data):
    out = []
    for p in paragony_data:
        out.append({
            "nazwa_pliku": p["nazwa_pliku"],
            "data_paragonu": p.get("data_paragonu"),
            "sklep": p.get("sklep"),
            "dane": p.get("dane", []),
            "model": p.get("model"),
            "dodano": p.get("dodano"),
        })
    return {
        "version": HISTORY_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "paragony": out,
    }


def apply_history_payload(payload: dict, merge: bool = False):
    """Wczytuje historię. merge=True dokłada brakujące nazwy plików zamiast nadpisywać."""
    incoming = payload.get("paragony", [])
    if not merge:
        st.session_state.paragony_data = []
        st.session_state.processed_files = set()

    existing = {p["nazwa_pliku"] for p in st.session_state.paragony_data}
    for p in incoming:
        name = p.get("nazwa_pliku", "nieznany.jpg")
        if merge and name in existing:
            continue
        st.session_state.paragony_data.append({
            "nazwa_pliku": name,
            "data_paragonu": p.get("data_paragonu"),
            "sklep": p.get("sklep"),
            "dane": p.get("dane", []),
            "model": p.get("model"),
            "dodano": p.get("dodano"),
            "obraz": None,
        })
        st.session_state.processed_files.add(name)


# ──────────────────────────────────────────────
# localStorage helpers
# ──────────────────────────────────────────────
def save_to_browser():
    if not HAS_LOCAL_STORAGE or _local_storage is None:
        return False
    try:
        payload = history_to_serializable(st.session_state.paragony_data)
        _local_storage.setItem(LS_KEY, json.dumps(payload, ensure_ascii=False))
        st.session_state.storage_status = (
            f"localStorage · {len(payload['paragony'])} par. · {datetime.now().strftime('%H:%M:%S')}"
        )
        return True
    except Exception as e:
        st.session_state.storage_status = f"localStorage błąd: {e}"
        return False


def load_from_browser():
    if not HAS_LOCAL_STORAGE or _local_storage is None:
        return -1
    try:
        raw = _local_storage.getItem(LS_KEY)
        if not raw:
            return 0
        payload = raw if isinstance(raw, dict) else json.loads(raw)
        if "paragony" not in payload:
            return 0
        apply_history_payload(payload)
        st.session_state.storage_status = f"Przywrócono z localStorage · {len(payload['paragony'])} par."
        return len(payload["paragony"])
    except Exception as e:
        st.session_state.storage_status = f"localStorage błąd: {e}"
        return -1


# ──────────────────────────────────────────────
# Google OAuth + Drive
# ──────────────────────────────────────────────
def _google_client_config():
    """Czyta client_id / secret z secrets."""
    try:
        cid = st.secrets.get("GOOGLE_CLIENT_ID") or st.secrets["google"]["client_id"]
        csec = st.secrets.get("GOOGLE_CLIENT_SECRET") or st.secrets["google"]["client_secret"]
    except Exception:
        return None
    if not cid or not csec:
        return None
    return {
        "web": {
            "client_id": cid,
            "client_secret": csec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_redirect_uri()],
        }
    }


def _redirect_uri():
    """URI powrotu – Streamlit Cloud lub lokalnie."""
    # Można nadpisać w secrets: GOOGLE_REDIRECT_URI
    try:
        custom = st.secrets.get("GOOGLE_REDIRECT_URI")
        if custom:
            return custom
    except Exception:
        pass
    # Streamlit ustawia czasem te zmienne
    host = os.environ.get("STREAMLIT_SERVER_URL") or ""
    if host:
        return host.rstrip("/") + "/"
    # Fallback – użytkownik musi ustawić GOOGLE_REDIRECT_URI w secrets
    return "https://localhost:8501/"


def google_configured():
    return HAS_GOOGLE and _google_client_config() is not None


def get_google_auth_url():
    conf = _google_client_config()
    if not conf:
        return None
    flow = Flow.from_client_config(conf, scopes=GOOGLE_SCOPES, redirect_uri=_redirect_uri())
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    st.session_state["oauth_state"] = state
    return auth_url


def complete_google_oauth(code: str):
    conf = _google_client_config()
    flow = Flow.from_client_config(conf, scopes=GOOGLE_SCOPES, redirect_uri=_redirect_uri())
    flow.fetch_token(code=code)
    creds = flow.credentials
    st.session_state.google_creds = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or GOOGLE_SCOPES),
    }
    # email
    try:
        service = build("oauth2", "v2", credentials=creds)
        info = service.userinfo().get().execute()
        st.session_state.google_email = info.get("email")
    except Exception:
        st.session_state.google_email = "połączono"


def creds_from_session():
    data = st.session_state.google_creds
    if not data:
        return None
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )


def drive_service():
    creds = creds_from_session()
    if not creds:
        return None
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def drive_find_or_create_folder(service):
    q = (
        f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    res = service.files().list(q=q, spaces="drive", fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": DRIVE_FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def drive_find_history_file(service, folder_id):
    q = (
        f"name='{DRIVE_FILENAME}' and '{folder_id}' in parents and trashed=false"
    )
    res = service.files().list(q=q, spaces="drive", fields="files(id, name, modifiedTime)").execute()
    files = res.get("files", [])
    return files[0] if files else None


def save_to_drive():
    """Zapisuje historię JSON na Google Drive użytkownika."""
    if not st.session_state.google_creds:
        return False
    try:
        service = drive_service()
        folder_id = drive_find_or_create_folder(service)
        payload = history_to_serializable(st.session_state.paragony_data)
        content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype="application/json", resumable=False)

        existing = drive_find_history_file(service, folder_id)
        if existing:
            service.files().update(
                fileId=existing["id"], media_body=media
            ).execute()
            st.session_state.drive_file_id = existing["id"]
        else:
            meta = {"name": DRIVE_FILENAME, "parents": [folder_id]}
            created = service.files().create(
                body=meta, media_body=media, fields="id"
            ).execute()
            st.session_state.drive_file_id = created["id"]

        st.session_state.drive_status = (
            f"Drive · zapisano {len(payload['paragony'])} par. · "
            f"{datetime.now().strftime('%H:%M:%S')}"
        )
        return True
    except Exception as e:
        st.session_state.drive_status = f"Drive błąd zapisu: {e}"
        return False


def load_from_drive(merge: bool = False):
    if not st.session_state.google_creds:
        return -1
    try:
        service = drive_service()
        folder_id = drive_find_or_create_folder(service)
        existing = drive_find_history_file(service, folder_id)
        if not existing:
            st.session_state.drive_status = "Drive · brak pliku historii (jeszcze nic nie zapisano)"
            return 0

        request = service.files().get_media(fileId=existing["id"])
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)
        payload = json.loads(buf.read().decode("utf-8"))
        apply_history_payload(payload, merge=merge)
        st.session_state.drive_file_id = existing["id"]
        st.session_state.drive_status = (
            f"Drive · wczytano {len(payload.get('paragony', []))} par. · "
            f"{existing.get('modifiedTime', '')[:19]}"
        )
        return len(payload.get("paragony", []))
    except Exception as e:
        st.session_state.drive_status = f"Drive błąd odczytu: {e}"
        return -1


def persist_all():
    """Zapis lokalny + Drive (jeśli połączono)."""
    save_to_browser()
    if st.session_state.google_creds:
        save_to_drive()


# Obsługa powrotu z OAuth (?code=...)
qp = st.query_params
if "code" in qp and not st.session_state.google_creds and google_configured():
    try:
        complete_google_oauth(qp["code"])
        # wyczyść parametry z URL
        st.query_params.clear()
        # po połączeniu – wczytaj historię z Drive
        n = load_from_drive(merge=True)
        save_to_browser()
        if n and n > 0:
            st.toast(f"Połączono z Google · przywrócono {n} paragonów z Drive", icon="☁️")
        else:
            st.toast("Połączono z Google Drive", icon="☁️")
        st.rerun()
    except Exception as e:
        st.error(f"Błąd logowania Google: {e}")

# Auto-load localStorage przy starcie
if not st.session_state.storage_loaded:
    st.session_state.storage_loaded = True
    if not st.session_state.paragony_data and HAS_LOCAL_STORAGE:
        n = load_from_browser()
        if n and n > 0:
            st.toast(f"Przywrócono {n} paragonów z pamięci urządzenia", icon="💾")

# ──────────────────────────────────────────────
# Analiza AI
# ──────────────────────────────────────────────
def analyze_receipt(image, api_key: str):
    client = genai.Client(api_key=api_key)
    prompt = """
Jesteś precyzyjnym systemem OCR i analizy paragonów sklepowych (Polska).
Zwróć WYŁĄCZNIE czysty JSON (jeden obiekt) – bez markdown.

{
  "data_paragonu": "YYYY-MM-DD" lub null,
  "sklep": "nazwa sklepu lub null",
  "pozycje": [
    {"Produkt": "nazwa", "Typ": "Spożywcze|Napoje|Chemia|Kosmetyki|Narzędzia|Ogród|Materiały budowlane|Elektronika|Odzież|Dom i mieszkanie|Zdrowie|Inne", "Cena": 12.99, "Ilość": 1}
  ]
}

Tylko pozycje produktów. Brak ilości → 1. Niepewna kategoria → Inne.
"""
    last_error = None
    for model_name in MODELS:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name, contents=[image, prompt]
                )
                raw = response.text.strip()
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw).strip()
                data = json.loads(raw)
                if isinstance(data, list):
                    data = {"data_paragonu": None, "sklep": None, "pozycje": data}
                if not isinstance(data, dict):
                    raise ValueError("Oczekiwano obiektu JSON")

                cleaned = []
                for it in data.get("pozycje") or []:
                    if not isinstance(it, dict):
                        continue
                    produkt = str(it.get("Produkt", "")).strip()
                    if not produkt:
                        continue
                    try:
                        cena = float(it.get("Cena", 0))
                    except (TypeError, ValueError):
                        cena = 0.0
                    try:
                        ilosc = float(it.get("Ilość", 1))
                    except (TypeError, ValueError):
                        ilosc = 1.0
                    cleaned.append({
                        "Produkt": produkt,
                        "Typ": str(it.get("Typ", "Inne")).strip() or "Inne",
                        "Cena": round(cena, 2),
                        "Ilość": ilosc,
                    })

                data_paragonu = data.get("data_paragonu")
                if data_paragonu:
                    data_paragonu = str(data_paragonu)[:10]
                    try:
                        datetime.strptime(data_paragonu, "%Y-%m-%d")
                    except Exception:
                        data_paragonu = None
                sklep = data.get("sklep")
                if sklep:
                    sklep = str(sklep).strip()[:80] or None
                return cleaned, model_name, data_paragonu, sklep
            except Exception as e:
                last_error = str(e)
                if any(x in last_error for x in ("503", "UNAVAILABLE", "high demand", "overloaded")):
                    time.sleep(2 * (attempt + 1))
                    continue
                break
    raise RuntimeError(last_error or "Nie udało się przeanalizować paragonu")


# ──────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────
with st.sidebar:
    st.header("🔑 Ustawienia AI")
    api_key_input = st.text_input("Klucz Google Gemini API", type="password")
    api_key = api_key_input or st.secrets.get("GEMINI_API_KEY")

    st.divider()
    st.subheader("☁️ Google Drive (Faza 3)")

    if not HAS_GOOGLE:
        st.error("Brak bibliotek Google – dodaj je do requirements.txt i zrestartuj.")
    elif not google_configured():
        st.warning(
            "Brak konfiguracji OAuth.\n\n"
            "W Streamlit **Secrets** dodaj:\n\n"
            "```toml\n"
            "GOOGLE_CLIENT_ID = \"....apps.googleusercontent.com\"\n"
            "GOOGLE_CLIENT_SECRET = \"...\"\n"
            "GOOGLE_REDIRECT_URI = \"https://TWOJA-APP.streamlit.app/\"\n"
            "```\n\n"
            "W Google Cloud Console → OAuth Client (Web) "
            "dodaj ten sam Redirect URI."
        )
    elif st.session_state.google_creds:
        st.success(f"Połączono: **{st.session_state.google_email or 'Google'}**")
        if st.session_state.drive_status:
            st.caption(st.session_state.drive_status)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("☁️ Zapisz na Drive", use_container_width=True):
                if save_to_drive():
                    st.toast("Zapisano na Google Drive", icon="☁️")
        with c2:
            if st.button("☁️ Wczytaj z Drive", use_container_width=True):
                n = load_from_drive(merge=False)
                save_to_browser()
                if n and n > 0:
                    st.toast(f"Wczytano {n} paragonów", icon="☁️")
                    st.rerun()
                elif n == 0:
                    st.info("Na Drive nie ma jeszcze historii.")
        if st.button("🔌 Rozłącz Google", use_container_width=True):
            st.session_state.google_creds = None
            st.session_state.google_email = None
            st.session_state.drive_file_id = None
            st.session_state.drive_status = ""
            st.rerun()
        st.caption(f"Plik: Drive / {DRIVE_FOLDER_NAME} / {DRIVE_FILENAME}")
    else:
        auth_url = get_google_auth_url()
        if auth_url:
            st.markdown(
                f'<a href="{auth_url}" target="_self">'
                f'<button style="width:100%;padding:0.6rem;border:none;border-radius:8px;'
                f'background:#0f766e;color:white;font-weight:600;cursor:pointer;">'
                f"🔗 Połącz z Google Drive</button></a>",
                unsafe_allow_html=True,
            )
            st.caption("Zaloguj się kontem Google – historia będzie w folderze „Jarwis” na Twoim Drive.")
        else:
            st.error("Nie można utworzyć URL logowania.")

    st.divider()
    st.subheader("💾 Pamięć urządzenia")
    if HAS_LOCAL_STORAGE:
        st.caption("localStorage aktywny")
        if st.session_state.storage_status:
            st.caption(st.session_state.storage_status)
        b1, b2 = st.columns(2)
        with b1:
            if st.button("💾 Zapisz", use_container_width=True, key="ls_save"):
                save_to_browser()
                st.toast("localStorage OK", icon="💾")
        with b2:
            if st.button("📥 Wczytaj", use_container_width=True, key="ls_load"):
                n = load_from_browser()
                if n and n > 0:
                    st.rerun()
    else:
        st.caption("localStorage niedostępny (brak pakietu)")

    st.divider()
    st.subheader("📂 Sesja")
    if st.session_state.paragony_data:
        for idx, p in enumerate(st.session_state.paragony_data):
            col1, col2 = st.columns([4, 1])
            with col1:
                label = p["nazwa_pliku"]
                if p.get("data_paragonu"):
                    label = f"{p['data_paragonu']} · {label}"
                st.markdown(
                    f"<span class='receipt-badge'>#{idx+1}</span> <small>{label}</small>",
                    unsafe_allow_html=True,
                )
            with col2:
                if st.button("✕", key=f"del_{idx}"):
                    st.session_state.paragony_data.pop(idx)
                    st.session_state.processed_files = {
                        x["nazwa_pliku"] for x in st.session_state.paragony_data
                    }
                    persist_all()
                    st.rerun()
        if st.button("🧹 Wyczyść sesję", use_container_width=True):
            st.session_state.paragony_data = []
            st.session_state.processed_files = set()
            st.session_state.failed_files = {}
            persist_all()
            st.rerun()
    else:
        st.info("Brak paragonów.")

    st.divider()
    st.subheader("📄 Kopia JSON")
    if st.session_state.paragony_data:
        hist = history_to_serializable(st.session_state.paragony_data)
        st.download_button(
            "⬇️ Eksportuj JSON",
            data=json.dumps(hist, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"jarwis_historia_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True,
        )
    hist_file = st.file_uploader("Wczytaj JSON", type=["json"], key="hist_up")
    if hist_file is not None:
        try:
            payload = json.load(hist_file)
            if "paragony" in payload and st.button(
                f"📥 Załaduj {len(payload['paragony'])} paragonów", use_container_width=True
            ):
                apply_history_payload(payload)
                persist_all()
                st.rerun()
        except Exception as e:
            st.error(str(e))

# ──────────────────────────────────────────────
# Upload + analiza
# ──────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "📷 Zdjęcia paragonów (JPG / PNG)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

if uploaded_files:
    if not api_key:
        st.error("⚠️ Brak klucza Gemini API.")
    else:
        for uploaded_file in uploaded_files:
            if uploaded_file.name in st.session_state.processed_files:
                continue
            with st.status(f"🤖 {uploaded_file.name}...", expanded=True) as status:
                try:
                    image = Image.open(uploaded_file)
                    if image.mode != "RGB":
                        image = image.convert("RGB")
                except Exception as e:
                    status.update(label="❌ Błąd otwarcia", state="error")
                    st.error(str(e))
                    continue
                try:
                    cleaned, used_model, data_paragonu, sklep = analyze_receipt(image, api_key)
                    st.session_state.paragony_data.append({
                        "nazwa_pliku": uploaded_file.name,
                        "obraz": image,
                        "dane": cleaned,
                        "model": used_model,
                        "data_paragonu": data_paragonu,
                        "sklep": sklep,
                        "dodano": datetime.now().isoformat(timespec="seconds"),
                    })
                    st.session_state.processed_files.add(uploaded_file.name)
                    st.session_state.failed_files.pop(uploaded_file.name, None)
                    persist_all()  # localStorage + Drive
                    extra = " · ".join(filter(None, [data_paragonu, sklep]))
                    status.update(
                        label=f"✅ {uploaded_file.name} ({len(cleaned)}) {extra} · {used_model}",
                        state="complete",
                    )
                except Exception as e:
                    st.session_state.failed_files[uploaded_file.name] = str(e)
                    status.update(label="❌ Błąd", state="error")
                    st.error(f"**{uploaded_file.name}**\n```\n{e}\n```")

if st.session_state.failed_files:
    for fname in list(st.session_state.failed_files.keys()):
        c1, c2 = st.columns([4, 1])
        c1.caption(f"❌ {fname}")
        if c2.button("🔄 Ponów", key=f"retry_{fname}"):
            st.session_state.processed_files.discard(fname)
            st.session_state.failed_files.pop(fname, None)
            st.rerun()

if not st.session_state.paragony_data:
    st.info("Wrzuć paragony albo połącz Google Drive / poczekaj na localStorage.")
    st.markdown("""
**Warstwy zapisu**
1. **localStorage** – automatycznie na tym telefonie/przeglądarce  
2. **Google Drive** – po kliknięciu „Połącz z Google” (folder `Jarwis`)  
3. **JSON** – ręczna kopia zapasowa  

Po połączeniu z Google każdy nowy paragon zapisuje się też na Drive.
""")
    st.stop()

# ──────────────────────────────────────────────
# DataFrame + filtry + UI wyników
# ──────────────────────────────────────────────
rows = []
for p in st.session_state.paragony_data:
    for item in p["dane"]:
        row = item.copy()
        row["Paragon"] = p["nazwa_pliku"]
        row["Data"] = p.get("data_paragonu")
        row["Sklep"] = p.get("sklep")
        rows.append(row)

df = pd.DataFrame(rows)
if df.empty:
    st.warning("Brak pozycji.")
    st.stop()

df["Wartość (PLN)"] = (df["Cena"] * df["Ilość"]).round(2)
df["Data_dt"] = pd.to_datetime(df["Data"], errors="coerce")

st.subheader("📅 Zakres podsumowania")
fc1, fc2, fc3 = st.columns([2, 2, 3])
with fc1:
    period = st.selectbox(
        "Okres",
        [
            "Cała historia", "Bieżący miesiąc", "Poprzedni miesiąc",
            "Bieżący kwartał", "Poprzedni kwartał", "Bieżące półrocze",
            "Ostatnie 6 miesięcy", "Bieżący rok", "Własny zakres",
        ],
    )

today = date.today()

def quarter_start(d):
    return date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)

def half_start(d):
    return date(d.year, 1 if d.month <= 6 else 7, 1)

start_d = end_d = None
if period == "Bieżący miesiąc":
    start_d, end_d = date(today.year, today.month, 1), today
elif period == "Poprzedni miesiąc":
    end_d = date(today.year, today.month, 1) - timedelta(days=1)
    start_d = date(end_d.year, end_d.month, 1)
elif period == "Bieżący kwartał":
    start_d, end_d = quarter_start(today), today
elif period == "Poprzedni kwartał":
    end_d = quarter_start(today) - timedelta(days=1)
    start_d = quarter_start(end_d)
elif period == "Bieżące półrocze":
    start_d, end_d = half_start(today), today
elif period == "Ostatnie 6 miesięcy":
    m, y = today.month - 6, today.year
    if m <= 0:
        m, y = m + 12, y - 1
    start_d, end_d = date(y, m, 1), today
elif period == "Bieżący rok":
    start_d, end_d = date(today.year, 1, 1), today
elif period == "Własny zakres":
    with fc2:
        start_d = st.date_input("Od", value=today - timedelta(days=90))
    with fc3:
        end_d = st.date_input("Do", value=today)

df_f = df.copy()
if start_d and end_d:
    df_f = df_f[(df_f["Data_dt"].dt.date >= start_d) & (df_f["Data_dt"].dt.date <= end_d)]
    st.caption(f"Filtr: **{start_d}** → **{end_d}** · {len(df_f)} poz.")
else:
    st.caption(f"Cała historia · {len(df_f)} poz.")

if df_f.empty:
    st.warning("Brak pozycji w okresie.")
    st.stop()

total_spend = df_f["Wartość (PLN)"].sum()
total_items = len(df_f)
n_rec = df_f["Paragon"].nunique()
avg_r = total_spend / n_rec if n_rec else 0
n_cat = df_f["Typ"].nunique()

for col, label, value, unit in zip(
    st.columns(5),
    ["Suma", "Pozycje", "Paragony", "Średnio", "Kategorie"],
    [f"{total_spend:,.2f}", str(total_items), str(n_rec), f"{avg_r:,.2f}", str(n_cat)],
    ["PLN", "szt.", "szt.", "PLN", ""],
):
    with col:
        st.markdown(
            f'<div class="metric-card"><div class="label">{label}</div>'
            f'<div class="value">{value}</div><div class="unit">{unit}</div></div>',
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)
tab_overview, tab_details, tab_receipts, tab_export = st.tabs(
    ["📊 Podsumowanie", "🛒 Szczegóły", "🧾 Paragony", "📥 Eksport"]
)

with tab_overview:
    podsumowanie = (
        df_f.groupby("Typ", as_index=False)["Wartość (PLN)"]
        .sum().sort_values("Wartość (PLN)", ascending=False)
    )
    cch, ctb = st.columns([1.6, 1])
    with cch:
        fig = px.bar(
            podsumowanie, x="Typ", y="Wartość (PLN)",
            color="Wartość (PLN)", color_continuous_scale=["#99f6e4", "#0f766e"],
            text_auto=".2f",
        )
        fig.update_layout(
            showlegend=False, height=400, coloraxis_showscale=False,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            xaxis_title="", yaxis_title="PLN",
        )
        fig.update_traces(textposition="outside", marker_line_width=0)
        st.plotly_chart(fig, use_container_width=True)

        fig2 = px.pie(
            podsumowanie, values="Wartość (PLN)", names="Typ", hole=0.45,
            color_discrete_sequence=px.colors.sequential.Teal,
        )
        fig2.update_traces(textposition="inside", textinfo="percent+label")
        fig2.update_layout(height=340, showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

        if df_f["Data_dt"].notna().any():
            monthly = (
                df_f.dropna(subset=["Data_dt"])
                .assign(Miesiąc=lambda x: x["Data_dt"].dt.to_period("M").astype(str))
                .groupby("Miesiąc", as_index=False)["Wartość (PLN)"].sum()
                .sort_values("Miesiąc")
            )
            if len(monthly) > 1:
                st.plotly_chart(
                    px.line(monthly, x="Miesiąc", y="Wartość (PLN)", markers=True),
                    use_container_width=True,
                )
    with ctb:
        st.dataframe(
            podsumowanie.style.format({"Wartość (PLN)": "{:.2f}"}),
            use_container_width=True, hide_index=True,
        )
        st.markdown("---")
        st.subheader("Top 5")
        st.dataframe(
            df_f.nlargest(5, "Wartość (PLN)")[
                ["Produkt", "Typ", "Wartość (PLN)", "Data"]
            ].style.format({"Wartość (PLN)": "{:.2f}"}),
            use_container_width=True, hide_index=True,
        )

with tab_details:
    f1, f2, f3 = st.columns(3)
    with f1:
        filter_cat = st.multiselect("Kategoria", sorted(df_f["Typ"].dropna().unique()))
    with f2:
        filter_receipt = st.multiselect("Paragon", sorted(df_f["Paragon"].unique()))
    with f3:
        sort_by = st.selectbox("Sortuj", ["Wartość ↓", "Wartość ↑", "Data ↓", "Produkt A-Z"])
    filtered = df_f.copy()
    if filter_cat:
        filtered = filtered[filtered["Typ"].isin(filter_cat)]
    if filter_receipt:
        filtered = filtered[filtered["Paragon"].isin(filter_receipt)]
    if sort_by == "Wartość ↓":
        filtered = filtered.sort_values("Wartość (PLN)", ascending=False)
    elif sort_by == "Wartość ↑":
        filtered = filtered.sort_values("Wartość (PLN)", ascending=True)
    elif sort_by == "Data ↓":
        filtered = filtered.sort_values("Data_dt", ascending=False, na_position="last")
    else:
        filtered = filtered.sort_values("Produkt")
    cols_show = [c for c in ["Data", "Sklep", "Produkt", "Typ", "Cena", "Ilość", "Wartość (PLN)", "Paragon"] if c in filtered.columns]
    st.dataframe(
        filtered[cols_show].style.format(
            {"Cena": "{:.2f}", "Ilość": "{:g}", "Wartość (PLN)": "{:.2f}"}, na_rep="—"
        ),
        use_container_width=True, hide_index=True, height=480,
    )

with tab_receipts:
    for idx, p in enumerate(st.session_state.paragony_data):
        meta = " · ".join(filter(None, [
            p.get("data_paragonu"), p.get("sklep"), f"{len(p['dane'])} poz."
        ]))
        with st.expander(f"🧾 #{idx+1} {p['nazwa_pliku']} · {meta}", expanded=(idx == 0)):
            e1, e2 = st.columns(2)
            with e1:
                nd = st.text_input("Data YYYY-MM-DD", value=p.get("data_paragonu") or "", key=f"d_{idx}")
            with e2:
                ns = st.text_input("Sklep", value=p.get("sklep") or "", key=f"s_{idx}")
            if st.button("💾 Zapisz meta", key=f"sm_{idx}"):
                val = nd.strip() or None
                if val:
                    try:
                        datetime.strptime(val, "%Y-%m-%d")
                    except ValueError:
                        st.error("Zła data")
                        val = p.get("data_paragonu")
                st.session_state.paragony_data[idx]["data_paragonu"] = val
                st.session_state.paragony_data[idx]["sklep"] = ns.strip() or None
                persist_all()
                st.rerun()
            c1, c2 = st.columns([1, 1.4])
            with c1:
                if p.get("obraz") is not None:
                    st.image(p["obraz"], use_container_width=True)
                else:
                    st.caption("(brak podglądu obrazu)")
            with c2:
                if p["dane"]:
                    ld = pd.DataFrame(p["dane"])
                    ld["Wartość (PLN)"] = (ld["Cena"] * ld["Ilość"]).round(2)
                    st.dataframe(
                        ld.style.format({"Cena": "{:.2f}", "Ilość": "{:g}", "Wartość (PLN)": "{:.2f}"}),
                        use_container_width=True, hide_index=True,
                    )
                    st.markdown(f"**Suma: {ld['Wartość (PLN)'].sum():,.2f} PLN**")

with tab_export:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df_f.drop(columns=["Data_dt"], errors="ignore").to_excel(writer, sheet_name="Zakupy", index=False)
        podsumowanie.to_excel(writer, sheet_name="Kategorie", index=False)
    st.download_button(
        "⬇️ Excel (filtr)",
        data=out.getvalue(),
        file_name=f"jarwis_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    hist = history_to_serializable(st.session_state.paragony_data)
    st.download_button(
        "⬇️ Pełna historia JSON",
        data=json.dumps(hist, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"jarwis_historia_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
        mime="application/json",
        use_container_width=True,
    )
