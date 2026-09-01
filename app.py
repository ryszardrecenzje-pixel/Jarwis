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

# ──────────────────────────────────────────────
# Konfiguracja strony
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="Jarwis – Menedżer Paragonów",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
    .main-header h1 { margin: 0; font-size: 1.9rem; font-weight: 700; letter-spacing: -0.5px; }
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
        font-weight: 600 !important; padding: 0.6rem 1.4rem !important;
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
        <p>Analizuj paragony • buduj historię wydatków • podsumowania miesięczne, kwartalne i półroczne</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# Stałe
# ──────────────────────────────────────────────
MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
]

HISTORY_VERSION = 1

# ──────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────
if "paragony_data" not in st.session_state:
    st.session_state.paragony_data = []
if "processed_files" not in st.session_state:
    st.session_state.processed_files = set()
if "failed_files" not in st.session_state:
    st.session_state.failed_files = {}

# ──────────────────────────────────────────────
# Pomocnicze – serializacja historii (bez obiektów PIL)
# ──────────────────────────────────────────────
def history_to_serializable(paragony_data):
    """Konwertuje stan sesji do czystego JSON (bez obrazów)."""
    out = []
    for p in paragony_data:
        out.append({
            "nazwa_pliku": p["nazwa_pliku"],
            "data_paragonu": p.get("data_paragonu"),  # YYYY-MM-DD lub None
            "sklep": p.get("sklep"),
            "dane": p["dane"],
            "model": p.get("model"),
            "dodano": p.get("dodano"),  # kiedy dodano do Jarwis
        })
    return {
        "version": HISTORY_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "paragony": out,
    }


def load_history_into_session(payload: dict):
    """Wczytuje historię JSON do session_state (bez obrazów)."""
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
            "obraz": None,  # brak obrazu po imporcie
        }
        st.session_state.paragony_data.append(entry)
        st.session_state.processed_files.add(entry["nazwa_pliku"])


def parse_date_safe(s):
    """Zwraca date lub None."""
    if not s:
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


# ──────────────────────────────────────────────
# Analiza AI
# ──────────────────────────────────────────────
def analyze_receipt(image, api_key: str):
    client = genai.Client(api_key=api_key)

    prompt = """
Jesteś precyzyjnym systemem OCR i analizy paragonów sklepowych (Polska).

Przeanalizuj zdjęcie paragonu i zwróć WYŁĄCZNIE czysty JSON (jeden obiekt) – bez markdown, bez ```json.

Struktura odpowiedzi:
{
  "data_paragonu": "YYYY-MM-DD" lub null,
  "sklep": "nazwa sklepu/sieci lub null",
  "pozycje": [
    {
      "Produkt": "nazwa produktu",
      "Typ": "jedna z: Spożywcze, Napoje, Chemia, Kosmetyki, Narzędzia, Ogród, Materiały budowlane, Elektronika, Odzież, Dom i mieszkanie, Zdrowie, Inne",
      "Cena": 12.99,
      "Ilość": 1
    }
  ]
}

Zasady:
1. data_paragonu – data z nagłówka paragonu w formacie YYYY-MM-DD. Jeśli nieczytelna → null.
2. sklep – nazwa sieci/sklepu jeśli widoczna.
3. Tylko pozycje produktów (ignoruj sumy, VAT, NIP, stopki).
4. Brak ilości → 1. Ceny z kropką. Niepewna kategoria → "Inne".
5. Zwróć tylko JSON obiektu, nic więcej.
"""

    last_error = None
    for model_name in MODELS:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[image, prompt],
                )
                raw = response.text.strip()
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
                raw = raw.strip()

                data = json.loads(raw)
                if not isinstance(data, dict):
                    # fallback: stara lista
                    if isinstance(data, list):
                        data = {"data_paragonu": None, "sklep": None, "pozycje": data}
                    else:
                        raise ValueError("Oczekiwano obiektu JSON")

                pozycje = data.get("pozycje") or data.get("items") or []
                if not isinstance(pozycje, list):
                    pozycje = []

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
                    # prosta walidacja
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
                is_overload = (
                    "503" in last_error
                    or "UNAVAILABLE" in last_error
                    or "high demand" in last_error.lower()
                    or "overloaded" in last_error.lower()
                )
                if is_overload:
                    time.sleep(2 * (attempt + 1))
                    continue
                break

    raise RuntimeError(last_error or "Nie udało się przeanalizować paragonu")


# ──────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────
with st.sidebar:
    st.header("🔑 Ustawienia AI")
    api_key_input = st.text_input(
        "Klucz Google Gemini API",
        type="password",
        help="Lub Secrets → GEMINI_API_KEY",
    )
    api_key = api_key_input or st.secrets.get("GEMINI_API_KEY")

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
                if st.button("✕", key=f"del_{idx}", help="Usuń"):
                    st.session_state.paragony_data.pop(idx)
                    st.session_state.processed_files = {
                        item["nazwa_pliku"] for item in st.session_state.paragony_data
                    }
                    st.rerun()
        if st.button("🧹 Wyczyść sesję", use_container_width=True):
            st.session_state.paragony_data = []
            st.session_state.processed_files = set()
            st.session_state.failed_files = {}
            st.rerun()
    else:
        st.info("Brak paragonów w sesji.")

    st.divider()
    st.subheader("💾 Historia (telefon / komputer)")

    # EKSPORT JSON
    if st.session_state.paragony_data:
        hist = history_to_serializable(st.session_state.paragony_data)
        hist_bytes = json.dumps(hist, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            "⬇️ Eksportuj historię (JSON)",
            data=hist_bytes,
            file_name=f"jarwis_historia_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True,
            help="Zapisz ten plik w Google Drive / Plikach na telefonie. Potem możesz go wczytać.",
        )

    # IMPORT JSON
    hist_file = st.file_uploader(
        "Wczytaj historię (JSON)",
        type=["json"],
        key="history_uploader",
        help="Wcześniej wyeksportowany plik jarwis_historia_*.json",
    )
    if hist_file is not None:
        try:
            payload = json.load(hist_file)
            if "paragony" not in payload:
                st.error("To nie wygląda na plik historii Jarwis.")
            else:
                n = len(payload["paragony"])
                if st.button(f"📥 Załaduj {n} paragonów z pliku", use_container_width=True):
                    load_history_into_session(payload)
                    st.success(f"Wczytano {n} paragonów.")
                    st.rerun()
        except Exception as e:
            st.error(f"Błąd odczytu JSON: {e}")

    st.caption("Faza 3 (Google Drive) – w przygotowaniu. Na razie trzymaj JSON w Drive/Plikach.")

    st.divider()
    st.caption("Fallback modeli:")
    for m in MODELS:
        st.caption(f"• {m}")

# ──────────────────────────────────────────────
# Upload nowych paragonów
# ──────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "📷 Wybierz zdjęcie(a) paragonu (JPG / PNG)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

if uploaded_files:
    if not api_key:
        st.error("⚠️ Brak klucza API. Wpisz go w panelu bocznym lub w Secrets.")
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
                    status.update(label=f"❌ Błąd otwarcia", state="error")
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
                    status.update(label=f"❌ Błąd", state="error")
                    st.error(f"**{uploaded_file.name}**\n\n```\n{e}\n```\n\nKliknij Ponów poniżej.")

if st.session_state.get("failed_files"):
    st.warning("Niektóre pliki nie zostały przetworzone:")
    for fname in list(st.session_state.failed_files.keys()):
        c1, c2 = st.columns([4, 1])
        c1.caption(f"❌ {fname}")
        if c2.button("🔄 Ponów", key=f"retry_{fname}"):
            st.session_state.processed_files.discard(fname)
            st.session_state.failed_files.pop(fname, None)
            st.rerun()

# ──────────────────────────────────────────────
# Brak danych
# ──────────────────────────────────────────────
if not st.session_state.paragony_data:
    st.info("👆 Wrzuć zdjęcia paragonów lub **wczytaj historię JSON** z panelu bocznego.")
    st.markdown("""
    **Jak budować historię na telefonie (Faza 1–2):**
    1. Analizujesz paragony jak zwykle.
    2. W sidebarze klikasz **Eksportuj historię (JSON)** i zapisujesz plik w Google Drive / Plikach.
    3. Przy kolejnej wizycie wrzucasz ten plik przez **Wczytaj historię**.
    4. Możesz dokładać nowe paragony i znowu eksportować (nadpisz stary plik).

    **Faza 3** (automatyczny zapis na Google Drive) – wkrótce.
    """)
    st.stop()

# ──────────────────────────────────────────────
# Budowa DataFrame
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
# FILTRY OKRESU
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
        index=0,
    )

today = date.today()

def quarter_start(d: date) -> date:
    q = (d.month - 1) // 3
    return date(d.year, q * 3 + 1, 1)

def half_start(d: date) -> date:
    return date(d.year, 1 if d.month <= 6 else 7, 1)

start_d, end_d = None, None
if period == "Bieżący miesiąc":
    start_d = date(today.year, today.month, 1)
    end_d = today
elif period == "Poprzedni miesiąc":
    first_this = date(today.year, today.month, 1)
    end_d = first_this - timedelta(days=1)
    start_d = date(end_d.year, end_d.month, 1)
elif period == "Bieżący kwartał":
    start_d = quarter_start(today)
    end_d = today
elif period == "Poprzedni kwartał":
    qs = quarter_start(today)
    end_d = qs - timedelta(days=1)
    start_d = quarter_start(end_d)
elif period == "Bieżące półrocze":
    start_d = half_start(today)
    end_d = today
elif period == "Ostatnie 6 miesięcy":
    # przybliżenie
    m = today.month - 6
    y = today.year
    if m <= 0:
        m += 12
        y -= 1
    start_d = date(y, m, 1)
    end_d = today
elif period == "Bieżący rok":
    start_d = date(today.year, 1, 1)
    end_d = today
elif period == "Własny zakres":
    with fc2:
        start_d = st.date_input("Od", value=today - timedelta(days=90))
    with fc3:
        end_d = st.date_input("Do", value=today)

# Filtrowanie
df_f = df.copy()
if start_d and end_d:
    mask = (df_f["Data_dt"].dt.date >= start_d) & (df_f["Data_dt"].dt.date <= end_d)
    # paragony bez daty – pokazuj tylko przy "Cała historia"
    df_f = df_f[mask]
    st.caption(f"Filtr: **{start_d}** → **{end_d}** · pozycji: {len(df_f)}")
else:
    st.caption(f"Cała historia · pozycji: {len(df_f)}")

if df_f.empty:
    st.warning("Brak pozycji w wybranym okresie. Sprawdź daty na paragonach lub wybierz „Cała historia”.")
    st.stop()

# ──────────────────────────────────────────────
# Metryki
# ──────────────────────────────────────────────
total_spend = df_f["Wartość (PLN)"].sum()
total_items = len(df_f)
receipts_in_period = df_f["Paragon"].nunique()
avg_receipt = total_spend / receipts_in_period if receipts_in_period else 0
unique_cat = df_f["Typ"].nunique()

c1, c2, c3, c4, c5 = st.columns(5)
for col, label, value, unit in [
    (c1, "Suma wydatków", f"{total_spend:,.2f}", "PLN"),
    (c2, "Pozycje", str(total_items), "produktów"),
    (c3, "Paragony", str(receipts_in_period), "szt."),
    (c4, "Średnio / paragon", f"{avg_receipt:,.2f}", "PLN"),
    (c5, "Kategorie", str(unique_cat), "różnych"),
]:
    with col:
        st.markdown(
            f"""<div class="metric-card">
            <div class="label">{label}</div>
            <div class="value">{value}</div>
            <div class="unit">{unit}</div>
            </div>""",
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# Zakładki
# ──────────────────────────────────────────────
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
            showlegend=False, margin=dict(t=20, b=40, l=40, r=20), height=400,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            xaxis_title="", yaxis_title="PLN", coloraxis_showscale=False,
        )
        fig_bar.update_traces(textposition="outside", marker_line_width=0)
        st.plotly_chart(fig_bar, use_container_width=True)

        fig_pie = px.pie(
            podsumowanie, values="Wartość (PLN)", names="Typ", hole=0.45,
            color_discrete_sequence=px.colors.sequential.Teal,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        fig_pie.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=360, showlegend=False)
        st.plotly_chart(fig_pie, use_container_width=True)

        # trend miesięczny jeśli są daty
        if df_f["Data_dt"].notna().any():
            st.subheader("Trend miesięczny")
            monthly = (
                df_f.dropna(subset=["Data_dt"])
                .assign(Miesiąc=lambda x: x["Data_dt"].dt.to_period("M").astype(str))
                .groupby("Miesiąc", as_index=False)["Wartość (PLN)"].sum()
                .sort_values("Miesiąc")
            )
            if len(monthly) > 1:
                fig_m = px.line(monthly, x="Miesiąc", y="Wartość (PLN)", markers=True)
                fig_m.update_layout(height=320, margin=dict(t=20, b=40, l=40, r=20))
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
    st.subheader("Pozycje w wybranym okresie")
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

    show_cols = ["Data", "Sklep", "Produkt", "Typ", "Cena", "Ilość", "Wartość (PLN)", "Paragon"]
    show_cols = [c for c in show_cols if c in filtered.columns]
    st.dataframe(
        filtered[show_cols].style.format(
            {"Cena": "{:.2f}", "Ilość": "{:g}", "Wartość (PLN)": "{:.2f}"},
            na_rep="—",
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
        if p.get("model"):
            meta.append(p["model"])
        title = f"🧾 #{idx+1} {p['nazwa_pliku']}  ·  {' · '.join(meta)}"
        with st.expander(title, expanded=(idx == 0)):
            # edycja daty / sklepu
            e1, e2 = st.columns(2)
            with e1:
                new_date = st.text_input(
                    "Data (YYYY-MM-DD)",
                    value=p.get("data_paragonu") or "",
                    key=f"date_{idx}",
                )
            with e2:
                new_shop = st.text_input(
                    "Sklep",
                    value=p.get("sklep") or "",
                    key=f"shop_{idx}",
                )
            if st.button("💾 Zapisz datę/sklep", key=f"save_meta_{idx}"):
                nd = new_date.strip() or None
                if nd:
                    try:
                        datetime.strptime(nd, "%Y-%m-%d")
                    except ValueError:
                        st.error("Zła data – użyj YYYY-MM-DD")
                        nd = p.get("data_paragonu")
                st.session_state.paragony_data[idx]["data_paragonu"] = nd
                st.session_state.paragony_data[idx]["sklep"] = new_shop.strip() or None
                st.rerun()

            c1, c2 = st.columns([1, 1.4])
            with c1:
                if p.get("obraz") is not None:
                    st.image(p["obraz"], use_container_width=True)
                else:
                    st.caption("(brak podglądu – wczytano z historii JSON)")
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
                else:
                    st.info("Brak pozycji.")

with tab_export:
    st.subheader("Eksport Excel (przefiltrowany okres)")
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        export_df = df_f.drop(columns=["Data_dt"], errors="ignore")
        export_df.to_excel(writer, sheet_name="Zakupy", index=False)
        podsumowanie.to_excel(writer, sheet_name="Kategorie", index=False)
        per_r = (
            df_f.groupby("Paragon", as_index=False)["Wartość (PLN)"]
            .sum()
            .sort_values("Wartość (PLN)", ascending=False)
        )
        per_r.to_excel(writer, sheet_name="Per Paragon", index=False)
    st.download_button(
        "⬇️ Pobierz Excel (bieżący filtr)",
        data=output.getvalue(),
        file_name=f"jarwis_{period.replace(' ', '_').lower()}_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.markdown("---")
    st.subheader("Pełna historia JSON (do telefonu / Drive)")
    st.markdown(
        "Zapisz ten plik w **Google Drive** lub **Plikach** na telefonie. "
        "Przy następnej sesji wczytaj go z sidebara – zachowasz całe podsumowania kwartalne i półroczne."
    )
    hist = history_to_serializable(st.session_state.paragony_data)
    st.download_button(
        "⬇️ Eksportuj pełną historię JSON",
        data=json.dumps(hist, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"jarwis_historia_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
        mime="application/json",
        use_container_width=True,
    )

    st.markdown("---")
    st.info(
        "**Faza 3 (wkrótce):** automatyczne logowanie Google + zapis historii prosto do Twojego folderu na Drive. "
        "Na razie najwygodniej: eksport JSON → zapisz w Drive → przy kolejnym użyciu wczytaj z sidebara."
    )
