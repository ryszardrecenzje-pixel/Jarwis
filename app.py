import io
import json
import re
import time
from datetime import datetime, date, timedelta
from google import genai
import pandas as pd
from PIL import Image
import streamlit as st
import plotly.express as px

# localStorage – auto-zapis w przeglądarce telefonu/komputera
try:
    from streamlit_local_storage import LocalStorage
    _local_storage = LocalStorage()
    HAS_LOCAL_STORAGE = True
except Exception:
    _local_storage = None
    HAS_LOCAL_STORAGE = False

# ──────────────────────────────────────────────
# Konfiguracja
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="Jarwis – Menedżer Paragonów",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

LS_KEY = "jarwis_historia_v1"
MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
]
HISTORY_VERSION = 1

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
        <p>Analizuj paragony • historia w pamięci przeglądarki • podsumowania kwartalne i półroczne</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────
if "paragony_data" not in st.session_state:
    st.session_state.paragony_data = []
if "processed_files" not in st.session_state:
    st.session_state.processed_files = set()
if "failed_files" not in st.session_state:
    st.session_state.failed_files = {}
if "storage_loaded" not in st.session_state:
    st.session_state.storage_loaded = False
if "storage_status" not in st.session_state:
    st.session_state.storage_status = ""

# ──────────────────────────────────────────────
# Serializacja historii (bez obrazów PIL)
# ──────────────────────────────────────────────
def history_to_serializable(paragony_data):
    out = []
    for p in paragony_data:
        out.append({
            "nazwa_pliku": p["nazwa_pliku"],
            "data_paragonu": p.get("data_paragonu"),
            "sklep": p.get("sklep"),
            "dane": p["dane"],
            "model": p.get("model"),
            "dodano": p.get("dodano"),
        })
    return {
        "version": HISTORY_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "paragony": out,
    }


def apply_history_payload(payload: dict):
    paragony = payload.get("paragony", [])
    st.session_state.paragony_data = []
    st.session_state.processed_files = set()
    for p in paragony:
        entry = {
            "nazwa_pliku": p.get("nazwa_pliku", "nieznany.jpg"),
            "data_paragonu": p.get("data_paragonu"),
            "sklep": p.get("sklep"),
            "dane": p.get("dane", []),
            "model": p.get("model"),
            "dodano": p.get("dodano"),
            "obraz": None,
        }
        st.session_state.paragony_data.append(entry)
        st.session_state.processed_files.add(entry["nazwa_pliku"])


def save_to_browser():
    """Zapisuje historię do localStorage przeglądarki."""
    if not HAS_LOCAL_STORAGE or _local_storage is None:
        return False
    try:
        payload = history_to_serializable(st.session_state.paragony_data)
        _local_storage.setItem(LS_KEY, json.dumps(payload, ensure_ascii=False))
        st.session_state.storage_status = (
            f"Zapisano w przeglądarce · {len(payload['paragony'])} paragonów · "
            f"{datetime.now().strftime('%H:%M:%S')}"
        )
        return True
    except Exception as e:
        st.session_state.storage_status = f"Błąd zapisu: {e}"
        return False


def load_from_browser():
    """Wczytuje historię z localStorage. Zwraca liczbę paragonów lub -1 przy braku."""
    if not HAS_LOCAL_STORAGE or _local_storage is None:
        return -1
    try:
        raw = _local_storage.getItem(LS_KEY)
        if not raw:
            return 0
        if isinstance(raw, dict):
            payload = raw
        else:
            payload = json.loads(raw)
        if "paragony" not in payload:
            return 0
        apply_history_payload(payload)
        st.session_state.storage_status = (
            f"Przywrócono z przeglądarki · {len(payload['paragony'])} paragonów"
        )
        return len(payload["paragony"])
    except Exception as e:
        st.session_state.storage_status = f"Błąd odczytu: {e}"
        return -1


def clear_browser_storage():
    if not HAS_LOCAL_STORAGE or _local_storage is None:
        return
    try:
        _local_storage.deleteItem(LS_KEY)
        st.session_state.storage_status = "Wyczyszczono pamięć przeglądarki"
    except Exception:
        try:
            _local_storage.setItem(LS_KEY, "")
        except Exception:
            pass


# Auto-wczytanie z localStorage przy pierwszym załadowaniu pustej sesji
if not st.session_state.storage_loaded:
    st.session_state.storage_loaded = True
    if not st.session_state.paragony_data and HAS_LOCAL_STORAGE:
        n = load_from_browser()
        if n and n > 0:
            st.toast(f"Przywrócono {n} paragonów z pamięci tego urządzenia", icon="💾")

# ──────────────────────────────────────────────
# Analiza AI
# ──────────────────────────────────────────────
def analyze_receipt(image, api_key: str):
    client = genai.Client(api_key=api_key)
    prompt = """
Jesteś precyzyjnym systemem OCR i analizy paragonów sklepowych (Polska).

Zwróć WYŁĄCZNIE czysty JSON (jeden obiekt) – bez markdown, bez ```json.

{
  "data_paragonu": "YYYY-MM-DD" lub null,
  "sklep": "nazwa sklepu lub null",
  "pozycje": [
    {
      "Produkt": "nazwa",
      "Typ": "Spożywcze|Napoje|Chemia|Kosmetyki|Narzędzia|Ogród|Materiały budowlane|Elektronika|Odzież|Dom i mieszkanie|Zdrowie|Inne",
      "Cena": 12.99,
      "Ilość": 1
    }
  ]
}

Zasady: tylko pozycje produktów; brak ilości → 1; niepewna kategoria → Inne; data z nagłówka paragonu.
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

                pozycje = data.get("pozycje") or []
                cleaned = []
                for it in pozycje:
                    if not isinstance(it, dict):
                        continue
                    produkt = str(it.get("Produkt", "")).strip()
                    if not produkt:
                        continue
                    typ = str(it.get("Typ", "Inne")).strip() or "Inne"
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
                        "Typ": typ,
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
    st.subheader("💾 Pamięć tego urządzenia")

    if HAS_LOCAL_STORAGE:
        st.success("localStorage aktywny – historia zapisuje się automatycznie na tym telefonie/komputerze.")
        if st.session_state.storage_status:
            st.caption(st.session_state.storage_status)

        b1, b2 = st.columns(2)
        with b1:
            if st.button("💾 Zapisz teraz", use_container_width=True):
                if save_to_browser():
                    st.toast("Zapisano w przeglądarce", icon="💾")
        with b2:
            if st.button("📥 Wczytaj", use_container_width=True):
                n = load_from_browser()
                if n and n > 0:
                    st.toast(f"Przywrócono {n} paragonów", icon="📥")
                    st.rerun()
                elif n == 0:
                    st.warning("Brak zapisanej historii w tej przeglądarce.")
        if st.button("🗑️ Wyczyść pamięć przeglądarki", use_container_width=True):
            clear_browser_storage()
            st.toast("Wyczyszczono localStorage", icon="🗑️")
    else:
        st.warning(
            "Pakiet streamlit-local-storage niedostępny. "
            "Dodaj go do requirements.txt i zrestartuj app."
        )

    st.divider()
    st.subheader("📂 Paragony w sesji")
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
                        item["nazwa_pliku"] for item in st.session_state.paragony_data
                    }
                    save_to_browser()
                    st.rerun()
        if st.button("🧹 Wyczyść sesję", use_container_width=True):
            st.session_state.paragony_data = []
            st.session_state.processed_files = set()
            st.session_state.failed_files = {}
            save_to_browser()
            st.rerun()
    else:
        st.info("Brak paragonów w sesji.")

    st.divider()
    st.subheader("📄 Kopia zapasowa (JSON)")
    if st.session_state.paragony_data:
        hist = history_to_serializable(st.session_state.paragony_data)
        st.download_button(
            "⬇️ Eksportuj JSON",
            data=json.dumps(hist, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"jarwis_historia_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True,
            help="Dodatkowa kopia np. na Google Drive (na wypadek czyszczenia przeglądarki).",
        )

    hist_file = st.file_uploader("Wczytaj JSON", type=["json"], key="history_uploader")
    if hist_file is not None:
        try:
            payload = json.load(hist_file)
            if "paragony" in payload:
                n = len(payload["paragony"])
                if st.button(f"📥 Załaduj {n} paragonów z pliku", use_container_width=True):
                    apply_history_payload(payload)
                    save_to_browser()
                    st.success(f"Wczytano {n} paragonów.")
                    st.rerun()
            else:
                st.error("To nie jest plik historii Jarwis.")
        except Exception as e:
            st.error(f"Błąd JSON: {e}")

    st.caption("Faza 3 (Google Drive) – później. localStorage = ten telefon/przeglądarka.")

# ──────────────────────────────────────────────
# Upload i analiza
# ──────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "📷 Wybierz zdjęcie(a) paragonu (JPG / PNG)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

if uploaded_files:
    if not api_key:
        st.error("⚠️ Brak klucza API.")
    else:
        for uploaded_file in uploaded_files:
            if uploaded_file.name in st.session_state.processed_files:
                continue
            with st.status(f"🤖 Analizuję: **{uploaded_file.name}**...", expanded=True) as status:
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
                    save_to_browser()  # auto-zapis po każdym paragonie
                    extra = []
                    if data_paragonu:
                        extra.append(data_paragonu)
                    if sklep:
                        extra.append(sklep)
                    extra_s = f" · {' · '.join(extra)}" if extra else ""
                    status.update(
                        label=f"✅ {uploaded_file.name} ({len(cleaned)} poz.){extra_s} · {used_model}",
                        state="complete",
                    )
                except Exception as e:
                    st.session_state.failed_files[uploaded_file.name] = str(e)
                    status.update(label="❌ Błąd", state="error")
                    st.error(f"**{uploaded_file.name}**\n\n```\n{e}\n```")

if st.session_state.get("failed_files"):
    st.warning("Nieudane pliki – możesz ponowić:")
    for fname in list(st.session_state.failed_files.keys()):
        c1, c2 = st.columns([4, 1])
        c1.caption(f"❌ {fname}")
        if c2.button("🔄 Ponów", key=f"retry_{fname}"):
            st.session_state.processed_files.discard(fname)
            st.session_state.failed_files.pop(fname, None)
            st.rerun()

if not st.session_state.paragony_data:
    st.info(
        "👆 Wrzuć paragony **albo** poczekaj – jeśli wcześniej coś zapisałeś na tym telefonie, "
        "historia powinna wczytać się sama z pamięci przeglądarki."
    )
    st.markdown("""
**Jak działa zapis na telefonie (localStorage):**
- Po każdym przeanalizowanym paragonie historia zapisuje się **automatycznie** w przeglądarce.
- Po zamknięciu karty / restarcie aplikacji dane **wracają same** (ta sama przeglądarka, to samo urządzenie).
- Dodatkowo możesz zrobić kopię JSON na Google Drive (sidebar).
- Uwaga: wyczyszczenie danych strony w ustawieniach telefonu kasuje localStorage.
""")
    st.stop()

# ──────────────────────────────────────────────
# DataFrame
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
    st.warning("Brak pozycji produktowych.")
    st.stop()

df["Wartość (PLN)"] = (df["Cena"] * df["Ilość"]).round(2)
df["Data_dt"] = pd.to_datetime(df["Data"], errors="coerce")

# ──────────────────────────────────────────────
# Filtr okresu
# ──────────────────────────────────────────────
st.subheader("📅 Zakres podsumowania")
fc1, fc2, fc3 = st.columns([2, 2, 3])
with fc1:
    period = st.selectbox(
        "Okres",
        [
            "Cała historia",
            "Bieżący miesiąc",
            "Poprzedni miesiąc",
            "Bieżący kwartał",
            "Poprzedni kwartał",
            "Bieżące półrocze",
            "Ostatnie 6 miesięcy",
            "Bieżący rok",
            "Własny zakres",
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
    mask = (df_f["Data_dt"].dt.date >= start_d) & (df_f["Data_dt"].dt.date <= end_d)
    df_f = df_f[mask]
    st.caption(f"Filtr: **{start_d}** → **{end_d}** · pozycji: {len(df_f)}")
else:
    st.caption(f"Cała historia · pozycji: {len(df_f)}")

if df_f.empty:
    st.warning("Brak pozycji w wybranym okresie.")
    st.stop()

# Metryki
total_spend = df_f["Wartość (PLN)"].sum()
total_items = len(df_f)
receipts_in_period = df_f["Paragon"].nunique()
avg_receipt = total_spend / receipts_in_period if receipts_in_period else 0
unique_cat = df_f["Typ"].nunique()

cols = st.columns(5)
for col, label, value, unit in zip(
    cols,
    ["Suma wydatków", "Pozycje", "Paragony", "Średnio / paragon", "Kategorie"],
    [f"{total_spend:,.2f}", str(total_items), str(receipts_in_period), f"{avg_receipt:,.2f}", str(unique_cat)],
    ["PLN", "produktów", "szt.", "PLN", "różnych"],
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
        .sum()
        .sort_values("Wartość (PLN)", ascending=False)
    )
    col_chart, col_table = st.columns([1.6, 1])
    with col_chart:
        st.subheader("Wydatki według kategorii")
        fig_bar = px.bar(
            podsumowanie, x="Typ", y="Wartość (PLN)",
            color="Wartość (PLN)", color_continuous_scale=["#99f6e4", "#0f766e"],
            text_auto=".2f",
        )
        fig_bar.update_layout(
            showlegend=False, height=400, coloraxis_showscale=False,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            xaxis_title="", yaxis_title="PLN", margin=dict(t=20, b=40, l=40, r=20),
        )
        fig_bar.update_traces(textposition="outside", marker_line_width=0)
        st.plotly_chart(fig_bar, use_container_width=True)

        fig_pie = px.pie(
            podsumowanie, values="Wartość (PLN)", names="Typ", hole=0.45,
            color_discrete_sequence=px.colors.sequential.Teal,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        fig_pie.update_layout(height=360, showlegend=False, margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig_pie, use_container_width=True)

        if df_f["Data_dt"].notna().any():
            monthly = (
                df_f.dropna(subset=["Data_dt"])
                .assign(Miesiąc=lambda x: x["Data_dt"].dt.to_period("M").astype(str))
                .groupby("Miesiąc", as_index=False)["Wartość (PLN)"].sum()
                .sort_values("Miesiąc")
            )
            if len(monthly) > 1:
                st.subheader("Trend miesięczny")
                fig_m = px.line(monthly, x="Miesiąc", y="Wartość (PLN)", markers=True)
                fig_m.update_layout(height=300, margin=dict(t=20, b=40, l=40, r=20))
                st.plotly_chart(fig_m, use_container_width=True)

    with col_table:
        st.subheader("Tabela kategorii")
        st.dataframe(
            podsumowanie.style.format({"Wartość (PLN)": "{:.2f}"}),
            use_container_width=True, hide_index=True,
        )
        st.markdown("---")
        st.subheader("Top 5 najdroższych")
        top5 = df_f.nlargest(5, "Wartość (PLN)")[["Produkt", "Typ", "Wartość (PLN)", "Data", "Paragon"]]
        st.dataframe(
            top5.style.format({"Wartość (PLN)": "{:.2f}"}),
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

    show_cols = [c for c in ["Data", "Sklep", "Produkt", "Typ", "Cena", "Ilość", "Wartość (PLN)", "Paragon"] if c in filtered.columns]
    st.dataframe(
        filtered[show_cols].style.format(
            {"Cena": "{:.2f}", "Ilość": "{:g}", "Wartość (PLN)": "{:.2f}"}, na_rep="—"
        ),
        use_container_width=True, hide_index=True, height=480,
    )

with tab_receipts:
    for idx, p in enumerate(st.session_state.paragony_data):
        meta = []
        if p.get("data_paragonu"):
            meta.append(p["data_paragonu"])
        if p.get("sklep"):
            meta.append(p["sklep"])
        meta.append(f"{len(p['dane'])} poz.")
        with st.expander(f"🧾 #{idx+1} {p['nazwa_pliku']} · {' · '.join(meta)}", expanded=(idx == 0)):
            e1, e2 = st.columns(2)
            with e1:
                new_date = st.text_input("Data (YYYY-MM-DD)", value=p.get("data_paragonu") or "", key=f"date_{idx}")
            with e2:
                new_shop = st.text_input("Sklep", value=p.get("sklep") or "", key=f"shop_{idx}")
            if st.button("💾 Zapisz datę/sklep", key=f"save_meta_{idx}"):
                nd = new_date.strip() or None
                if nd:
                    try:
                        datetime.strptime(nd, "%Y-%m-%d")
                    except ValueError:
                        st.error("Zła data")
                        nd = p.get("data_paragonu")
                st.session_state.paragony_data[idx]["data_paragonu"] = nd
                st.session_state.paragony_data[idx]["sklep"] = new_shop.strip() or None
                save_to_browser()
                st.rerun()

            c1, c2 = st.columns([1, 1.4])
            with c1:
                if p.get("obraz") is not None:
                    st.image(p["obraz"], use_container_width=True)
                else:
                    st.caption("(brak podglądu – dane z pamięci / JSON)")
            with c2:
                if p["dane"]:
                    local_df = pd.DataFrame(p["dane"])
                    local_df["Wartość (PLN)"] = (local_df["Cena"] * local_df["Ilość"]).round(2)
                    st.dataframe(
                        local_df.style.format(
                            {"Cena": "{:.2f}", "Ilość": "{:g}", "Wartość (PLN)": "{:.2f}"}
                        ),
                        use_container_width=True, hide_index=True,
                    )
                    st.markdown(f"**Suma:** **{local_df['Wartość (PLN)'].sum():,.2f} PLN**")

with tab_export:
    st.subheader("Excel (bieżący filtr)")
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_f.drop(columns=["Data_dt"], errors="ignore").to_excel(writer, sheet_name="Zakupy", index=False)
        podsumowanie.to_excel(writer, sheet_name="Kategorie", index=False)
        df_f.groupby("Paragon", as_index=False)["Wartość (PLN)"].sum().to_excel(
            writer, sheet_name="Per Paragon", index=False
        )
    st.download_button(
        "⬇️ Pobierz Excel",
        data=output.getvalue(),
        file_name=f"jarwis_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.markdown("---")
    st.subheader("Kopia zapasowa JSON")
    hist = history_to_serializable(st.session_state.paragony_data)
    st.download_button(
        "⬇️ Eksportuj pełną historię JSON",
        data=json.dumps(hist, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"jarwis_historia_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
        mime="application/json",
        use_container_width=True,
    )
    st.caption(
        "localStorage trzyma dane na tym urządzeniu. JSON na Drive = zapas na wypadek "
        "czyszczenia przeglądarki lub zmiany telefonu."
    )
