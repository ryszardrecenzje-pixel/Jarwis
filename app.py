import io
import json
import re
import time
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
# Niestandardowy CSS
# ──────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .main-header {
        background: linear-gradient(135deg, #1e3a5f 0%, #0f766e 100%);
        padding: 1.5rem 2rem;
        border-radius: 16px;
        color: white;
        margin-bottom: 1.5rem;
        box-shadow: 0 8px 24px rgba(15, 118, 110, 0.25);
    }

    .main-header h1 {
        margin: 0;
        font-size: 1.9rem;
        font-weight: 700;
        letter-spacing: -0.5px;
    }

    .main-header p {
        margin: 0.4rem 0 0 0;
        opacity: 0.9;
        font-size: 1rem;
    }

    .metric-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.1rem 1.3rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        text-align: center;
        height: 100%;
    }

    .metric-card .label {
        font-size: 0.8rem;
        color: #64748b;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.4px;
        margin-bottom: 0.3rem;
    }

    .metric-card .value {
        font-size: 1.6rem;
        font-weight: 700;
        color: #0f172a;
    }

    .metric-card .unit {
        font-size: 0.9rem;
        color: #64748b;
        font-weight: 500;
    }

    .stDownloadButton > button {
        background: linear-gradient(135deg, #0f766e, #0d9488) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        padding: 0.6rem 1.4rem !important;
        transition: all 0.2s ease !important;
    }

    .stDownloadButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 16px rgba(15, 118, 110, 0.3) !important;
    }

    div[data-testid="stSidebar"] {
        background: #f8fafc;
        border-right: 1px solid #e2e8f0;
    }

    .receipt-badge {
        display: inline-block;
        background: #ecfdf5;
        color: #065f46;
        padding: 0.2rem 0.6rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-bottom: 0.3rem;
    }

    .stDataFrame {
        border-radius: 10px;
        overflow: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# Nagłówek
# ──────────────────────────────────────────────
st.markdown(
    """
    <div class="main-header">
        <h1>🧾 Jarwis – Inteligentny Analizator Paragonów</h1>
        <p>Wrzuć zdjęcia paragonów. AI odczyta pozycje, skategoryzuje wydatki i przygotuje gotowy raport Excel.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# Modele – kolejność fallback (od najnowszego)
# ──────────────────────────────────────────────
MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
]

# ──────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────
with st.sidebar:
    st.header("🔑 Ustawienia AI")
    api_key_input = st.text_input(
        "Klucz Google Gemini API",
        type="password",
        help="Możesz też dodać go w Secrets jako GEMINI_API_KEY",
    )
    api_key = api_key_input or st.secrets.get("GEMINI_API_KEY")

    st.divider()
    st.subheader("📂 Paragony w sesji")

    if "paragony_data" not in st.session_state:
        st.session_state.paragony_data = []
    if "processed_files" not in st.session_state:
        st.session_state.processed_files = set()
    if "failed_files" not in st.session_state:
        st.session_state.failed_files = {}

    if st.session_state.paragony_data:
        for idx, p in enumerate(st.session_state.paragony_data):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(
                    f"<span class='receipt-badge'>#{idx+1}</span>  "
                    f"<small>{p['nazwa_pliku']}</small>",
                    unsafe_allow_html=True,
                )
            with col2:
                if st.button("✕", key=f"del_{idx}", help="Usuń ten paragon"):
                    st.session_state.paragony_data.pop(idx)
                    st.session_state.processed_files = {
                        item["nazwa_pliku"] for item in st.session_state.paragony_data
                    }
                    st.rerun()

        st.markdown("---")
        if st.button("🧹 Wyczyść wszystkie", use_container_width=True):
            st.session_state.paragony_data = []
            st.session_state.processed_files = set()
            st.session_state.failed_files = {}
            st.rerun()
    else:
        st.info("Brak wgranych paragonów.")

    st.divider()
    st.caption("Modele (kolejność fallback):")
    for m in MODELS:
        st.caption(f"• {m}")
    st.caption("Jarwis • Streamlit + Gemini")

# ──────────────────────────────────────────────
# Upload
# ──────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "📷 Wybierz zdjęcie(a) paragonu (JPG / PNG)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
    help="Możesz wrzucić kilka paragonów naraz",
)

# ──────────────────────────────────────────────
# Funkcja analizy z fallbackiem modeli
# ──────────────────────────────────────────────
def analyze_receipt(image, api_key: str):
    """Próbuje kolejno modele z listy MODELS. Zwraca listę pozycji lub rzuca wyjątek."""
    client = genai.Client(api_key=api_key)

    prompt = """
Jesteś precyzyjnym systemem OCR i analizy paragonów sklepowych (Polska).

Przeanalizuj zdjęcie paragonu i wypisz WSZYSTKIE zakupione produkty.

Zwróć WYŁĄCZNIE czysty JSON (lista obiektów) – bez markdown, bez ```json, bez komentarzy.

Każdy obiekt musi mieć dokładnie te klucze:
- "Produkt": dokładna nazwa produktu z paragonu (string)
- "Typ": jedna z kategorii: "Spożywcze", "Napoje", "Chemia", "Kosmetyki", "Narzędzia", "Ogród", "Materiały budowlane", "Elektronika", "Odzież", "Dom i mieszkanie", "Zdrowie", "Inne"
- "Cena": cena jednostkowa brutto jako liczba (float), np. 12.99
- "Ilość": ilość jako liczba (int lub float), np. 1 lub 0.5

Zasady:
1. Ignoruj nagłówki, stopki, sumy, VAT, daty, numery NIP itp. – tylko pozycje produktów.
2. Jeśli ilość nie jest podana – przyjmij 1.
3. Ceny zawsze z kropką dziesiętną.
4. Jeśli nie jesteś pewien kategorii – użyj "Inne".
5. Zwróć tylko listę, nawet jeśli jest pusta: []
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

                items = json.loads(raw)
                if not isinstance(items, list):
                    raise ValueError("Odpowiedź nie jest listą JSON")

                cleaned = []
                for it in items:
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

                    cleaned.append(
                        {
                            "Produkt": produkt,
                            "Typ": typ,
                            "Cena": round(cena, 2),
                            "Ilość": ilosc,
                        }
                    )

                return cleaned, model_name

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
                else:
                    break

    raise RuntimeError(last_error or "Nie udało się przeanalizować paragonu")


# ──────────────────────────────────────────────
# Przetwarzanie nowych plików
# ──────────────────────────────────────────────
if uploaded_files:
    if not api_key:
        st.error(
            "⚠️ Brak klucza API. Wpisz go w panelu bocznym lub dodaj do Secrets jako `GEMINI_API_KEY`."
        )
    else:
        for uploaded_file in uploaded_files:
            if uploaded_file.name in st.session_state.processed_files:
                continue

            with st.status(
                f"🤖 Jarwis analizuje: **{uploaded_file.name}**...", expanded=True
            ) as status:
                try:
                    image = Image.open(uploaded_file)
                    if image.mode != "RGB":
                        image = image.convert("RGB")
                except Exception as e:
                    status.update(label=f"❌ Błąd otwarcia: {uploaded_file.name}", state="error")
                    st.error(f"Nie udało się otworzyć obrazu: {e}")
                    continue

                try:
                    cleaned, used_model = analyze_receipt(image, api_key)

                    st.session_state.paragony_data.append(
                        {
                            "nazwa_pliku": uploaded_file.name,
                            "obraz": image,
                            "dane": cleaned,
                            "model": used_model,
                        }
                    )
                    st.session_state.processed_files.add(uploaded_file.name)
                    st.session_state.failed_files.pop(uploaded_file.name, None)

                    status.update(
                        label=f"✅ Gotowe: {uploaded_file.name} ({len(cleaned)} pozycji) • model: {used_model}",
                        state="complete",
                    )

                except Exception as e:
                    err_msg = str(e)
                    st.session_state.failed_files[uploaded_file.name] = err_msg
                    status.update(label=f"❌ Błąd: {uploaded_file.name}", state="error")
                    st.error(
                        f"**Nie udało się przeanalizować pliku** `{uploaded_file.name}`\n\n"
                        f"```\n{err_msg}\n```\n\n"
                        "Model był przeciążony (503) lub wystąpił inny błąd. "
                        "Kliknij **Spróbuj ponownie** poniżej."
                    )

# ──────────────────────────────────────────────
# Przyciski ponowienia dla nieudanych plików
# ──────────────────────────────────────────────
if st.session_state.get("failed_files"):
    st.warning("Niektóre pliki nie zostały przetworzone. Możesz spróbować ponownie:")
    for fname, err in list(st.session_state.failed_files.items()):
        col_a, col_b = st.columns([4, 1])
        with col_a:
            st.caption(f"❌ {fname}")
        with col_b:
            if st.button("🔄 Ponów", key=f"retry_{fname}"):
                st.session_state.processed_files.discard(fname)
                st.session_state.failed_files.pop(fname, None)
                st.rerun()

# ──────────────────────────────────────────────
# Wyniki
# ──────────────────────────────────────────────
if not st.session_state.paragony_data:
    st.info("👆 Wrzuć pierwsze zdjęcie paragonu, aby rozpocząć analizę.")
    st.stop()

wszystkie_pozycje = []
for p in st.session_state.paragony_data:
    for item in p["dane"]:
        row = item.copy()
        row["Paragon"] = p["nazwa_pliku"]
        wszystkie_pozycje.append(row)

df = pd.DataFrame(wszystkie_pozycje)

if df.empty:
    st.warning("Nie znaleziono żadnych pozycji na wgranych paragonach.")
    st.stop()

df["Wartość (PLN)"] = (df["Cena"] * df["Ilość"]).round(2)

total_spend = df["Wartość (PLN)"].sum()
total_items = len(df)
total_receipts = len(st.session_state.paragony_data)
avg_per_receipt = total_spend / total_receipts if total_receipts else 0
unique_categories = df["Typ"].nunique()

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="label">Suma wydatków</div>
            <div class="value">{total_spend:,.2f}</div>
            <div class="unit">PLN</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="label">Pozycje</div>
            <div class="value">{total_items}</div>
            <div class="unit">produktów</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with col3:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="label">Paragony</div>
            <div class="value">{total_receipts}</div>
            <div class="unit">szt.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with col4:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="label">Średnio / paragon</div>
            <div class="value">{avg_per_receipt:,.2f}</div>
            <div class="unit">PLN</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with col5:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="label">Kategorie</div>
            <div class="value">{unique_categories}</div>
            <div class="unit">różnych</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

tab_overview, tab_details, tab_receipts, tab_export = st.tabs(
    ["📊 Podsumowanie", "🛒 Szczegóły zakupów", "🧾 Poszczególne paragony", "📥 Eksport"]
)

with tab_overview:
    podsumowanie = (
        df.groupby("Typ", as_index=False)["Wartość (PLN)"]
        .sum()
        .sort_values("Wartość (PLN)", ascending=False)
    )

    col_chart, col_table = st.columns([1.6, 1])

    with col_chart:
        st.subheader("Wydatki według kategorii")

        fig_bar = px.bar(
            podsumowanie,
            x="Typ",
            y="Wartość (PLN)",
            color="Wartość (PLN)",
            color_continuous_scale=["#99f6e4", "#0f766e"],
            text_auto=".2f",
            labels={"Typ": "Kategoria", "Wartość (PLN)": "Suma (PLN)"},
        )
        fig_bar.update_layout(
            showlegend=False,
            margin=dict(t=20, b=40, l=40, r=20),
            height=420,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            xaxis_title="",
            yaxis_title="PLN",
            coloraxis_showscale=False,
            font=dict(family="Inter", size=13),
        )
        fig_bar.update_traces(
            textposition="outside",
            marker_line_width=0,
            hovertemplate="<b>%{x}</b><br>%{y:.2f} PLN<extra></extra>",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        fig_pie = px.pie(
            podsumowanie,
            values="Wartość (PLN)",
            names="Typ",
            hole=0.45,
            color_discrete_sequence=px.colors.sequential.Teal,
        )
        fig_pie.update_traces(
            textposition="inside",
            textinfo="percent+label",
            hovertemplate="<b>%{label}</b><br>%{value:.2f} PLN<br>%{percent}<extra></extra>",
        )
        fig_pie.update_layout(
            margin=dict(t=20, b=20, l=20, r=20),
            height=380,
            showlegend=False,
            font=dict(family="Inter", size=12),
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_table:
        st.subheader("Tabela kategorii")
        st.dataframe(
            podsumowanie.style.format({"Wartość (PLN)": "{:.2f}"}),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("---")
        st.subheader("Top 5 najdroższych pozycji")
        top5 = df.nlargest(5, "Wartość (PLN)")[
            ["Produkt", "Typ", "Wartość (PLN)", "Paragon"]
        ]
        st.dataframe(
            top5.style.format({"Wartość (PLN)": "{:.2f}"}),
            use_container_width=True,
            hide_index=True,
        )

with tab_details:
    st.subheader("Wszystkie pozycje z paragonów")

    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        filter_cat = st.multiselect(
            "Filtruj kategorię",
            options=sorted(df["Typ"].unique()),
            default=None,
        )
    with fcol2:
        filter_receipt = st.multiselect(
            "Filtruj paragon",
            options=sorted(df["Paragon"].unique()),
            default=None,
        )
    with fcol3:
        sort_by = st.selectbox(
            "Sortuj według",
            ["Wartość (PLN) ↓", "Wartość (PLN) ↑", "Produkt A-Z", "Kategoria"],
        )

    filtered = df.copy()
    if filter_cat:
        filtered = filtered[filtered["Typ"].isin(filter_cat)]
    if filter_receipt:
        filtered = filtered[filtered["Paragon"].isin(filter_receipt)]

    if sort_by == "Wartość (PLN) ↓":
        filtered = filtered.sort_values("Wartość (PLN)", ascending=False)
    elif sort_by == "Wartość (PLN) ↑":
        filtered = filtered.sort_values("Wartość (PLN)", ascending=True)
    elif sort_by == "Produkt A-Z":
        filtered = filtered.sort_values("Produkt")
    else:
        filtered = filtered.sort_values("Typ")

    st.dataframe(
        filtered[
            ["Produkt", "Typ", "Cena", "Ilość", "Wartość (PLN)", "Paragon"]
        ].style.format(
            {"Cena": "{:.2f}", "Ilość": "{:g}", "Wartość (PLN)": "{:.2f}"}
        ),
        use_container_width=True,
        hide_index=True,
        height=480,
    )

with tab_receipts:
    for idx, p in enumerate(st.session_state.paragony_data):
        model_info = p.get("model", "?")
        with st.expander(
            f"🧾 Paragon {idx+1}: {p['nazwa_pliku']}  •  {len(p['dane'])} pozycji  •  {model_info}",
            expanded=(idx == 0),
        ):
            c1, c2 = st.columns([1, 1.4])
            with c1:
                st.image(p["obraz"], caption=p["nazwa_pliku"], use_container_width=True)
            with c2:
                if p["dane"]:
                    local_df = pd.DataFrame(p["dane"])
                    local_df["Wartość (PLN)"] = (
                        local_df["Cena"] * local_df["Ilość"]
                    ).round(2)
                    st.dataframe(
                        local_df.style.format(
                            {
                                "Cena": "{:.2f}",
                                "Ilość": "{:g}",
                                "Wartość (PLN)": "{:.2f}",
                            }
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.markdown(
                        f"**Suma tego paragonu:** "
                        f"**{local_df['Wartość (PLN)'].sum():,.2f} PLN**"
                    )
                else:
                    st.info("Brak rozpoznanych pozycji.")

with tab_export:
    st.subheader("Pobierz raport Excel")

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Wszystkie Zakupy", index=False)
        podsumowanie.to_excel(writer, sheet_name="Podsumowanie Kategorii", index=False)

        per_receipt = (
            df.groupby("Paragon", as_index=False)["Wartość (PLN)"]
            .sum()
            .sort_values("Wartość (PLN)", ascending=False)
        )
        per_receipt.to_excel(writer, sheet_name="Per Paragon", index=False)

    excel_data = output.getvalue()

    st.download_button(
        label="⬇️ Pobierz pełny raport Excel",
        data=excel_data,
        file_name="jarwis_podsumowanie_paragonow.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.markdown("---")
    st.caption(
        "Raport zawiera 3 arkusze: wszystkie pozycje, podsumowanie kategorii oraz sumy per paragon."
    )
