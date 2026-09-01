import io
import json
import os
import time
from google import genai
import pandas as pd
from PIL import Image
import streamlit as st

st.set_page_config(
    page_title="Jarwis - Menedżer Paragonów", page_icon="🧾", layout="centered"
)

st.title("📊 Jarwis - Inteligentny Analizator Paragonów")
st.write(
    "Wrzuć jedno lub wiele zdjęć paragonów. Jarwis automatycznie odczyta"
    " pozycje, zsumuje wydatki i przygotuje dla Ciebie plik Excel!"
)

# Konfiguracja klucza API (ze Secrets lub panelu bocznego)
st.sidebar.header("🔑 Ustawienia AI")
api_key_input = st.sidebar.text_input(
    "Podaj klucz Google Gemini API", type="password"
)
api_key = api_key_input or st.secrets.get("GEMINI_API_KEY")

# Inicjalizacja stanu sesji do przechowywania historii przetworzonych paragonów
if "paragony_data" not in st.session_state:
  st.session_state.paragony_data = []

if "processed_files" not in st.session_state:
  st.session_state.processed_files = set()

# Panel boczny z zarządzaniem wgranymi paragonami
st.sidebar.subheader("📂 Twoje paragony w sesji")
if st.session_state.paragony_data:
  for idx, p in enumerate(st.session_state.paragony_data):
    col_sb1, col_sb2 = st.sidebar.columns([3, 1])
    col_sb1.text(f"Paragon {idx+1}: {p['nazwa_pliku']}")
    if col_sb2.button("❌", key=f"del_{idx}", help="Usuń ten paragon"):
      st.session_state.paragony_data.pop(idx)
      st.session_state.processed_files = {
          item["nazwa_pliku"] for item in st.session_state.paragony_data
      }
      st.rerun()

  if st.sidebar.button("🧹 Wyczyść wszystkie paragony"):
    st.session_state.paragony_data = []
    st.session_state.processed_files = set()
    st.rerun()
else:
  st.sidebar.info("Brak wgranych paragonów.")

# 1. Wgrywanie wielu plików naraz
uploaded_files = st.file_uploader(
    "Wybierz zdjęcie(a) paragonu...",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

if uploaded_files:
  if not api_key:
    st.error(
        "⚠️ Brak klucza API! Wpisz go w sekcji Secrets w Streamlit Cloud lub w"
        " panelu bocznym."
    )
  else:
    for uploaded_file in uploaded_files:
      if uploaded_file.name not in st.session_state.processed_files:
        with st.spinner(
            f"🤖 Jarwis automatycznie analizuje plik: {uploaded_file.name}..."
        ):
          sukces_analizy = False
          ostatni_blad = ""

          # Pętle powtórzeń (obsługa chwilowego przeciążenia serwerów 503)
          image = Image.open(uploaded_file)
          client = genai.Client(api_key=api_key)

          prompt = """
                        Przeanalizuj to zdjęcie paragonu. Wypisz wszystkie zakupione produkty w formacie JSON (jako lista obiektów).
                        Każdy obiekt musi mieć dokładnie te klucze:
                        - "Produkt": nazwa produktu z paragonu
                        - "Typ": kategoria produktu (np. Narzędzia, Ogród, Chemia, Materiały budowlane, Spożywcze, Inne)
                        - "Cena": cena jednostkowa brutto jako liczba (float)
                        - "Ilość": ilość jako liczba całkowita lub zmiennoprzecinkowa (float)

                        Zwróć TYLKO czysty ciąg JSON, bez dodatkowego formatowania markdown (bez ```json ... ```), sam JSON.
                        """

          for proba in range(3):  # 3 próby połączenia
            try:
              response = client.models.generate_content(
                  model="gemini-3.6-flash", contents=[image, prompt]
              )

              clean_text = (
                  response.text.strip()
                  .replace("```json", "")
                  .replace("```", "")
                  .strip()
              )
              items = json.loads(clean_text)

              st.session_state.paragony_data.append({
                  "nazwa_pliku": uploaded_file.name,
                  "obraz": image,
                  "dane": items,
              })
              st.session_state.processed_files.add(uploaded_file.name)
              sukces_analizy = True
              break
            except Exception as e:
              ostatni_blad = str(e)
              if "503" in str(e) or "Unavailable" in str(e):
                time.sleep(2)  # odczekaj 2 sekundy przed ponowną próbą
              else:
                break  # inny błąd, przerwij próby

          if not sukces_analizy:
            st.error(
                f"Wystąpił błąd podczas analizy pliku {uploaded_file.name}:"
                f" {ostatni_blad}"
            )
            if st.button(
                f"🔄 Spróbuj ponownie przetworzyć {uploaded_file.name}",
                key=f"retry_{uploaded_file.name}",
            ):
              # Usunięciem z zablokowanych, aby spróbował ponownie
              st.rerun()

# Wyświetlanie wyników, tabel i wykresów
if st.session_state.paragony_data:
  st.success("✅ Wszystkie paragony zostały pomyślnie przetworzone!")

  wszystkie_pozycje = []
  for p in st.session_state.paragony_data:
    for item in p["dane"]:
      item_copy = item.copy()
      item_copy["Paragon Źródłowy"] = p["nazwa_pliku"]
      wszystkie_pozycje.append(item_copy)

  df = pd.DataFrame(wszystkie_pozycje)
  df["Wartość (PLN)"] = df["Cena"] * df["Ilość"]

  st.subheader("🛒 Łączna szczegółowa rozpiska zakupów:")
  st.dataframe(df, use_container_width=True)

  st.subheader("📈 Podsumowanie wydatków według kategorii:")
  podsumowanie = df.groupby("Typ")["Wartość (PLN)"].sum().reset_index()
  st.bar_chart(podsumowanie.set_index("Typ"))
  st.dataframe(podsumowanie, use_container_width=True)

  # Generowanie pliku Excel
  output = io.BytesIO()
  with pd.ExcelWriter(output, engine="openpyxl") as writer:
    df.to_excel(writer, sheet_name="Wszystkie Zakupy", index=False)
    podsumowanie.to_excel(writer, sheet_name="Podsumowanie Kategorii", index=False)
  excel_data = output.getvalue()

  st.subheader("📥 Pobierz raport zbiorczy")
  st.download_button(
      label="Pobierz plik Excel z podsumowaniem wszystkich zakupów",
      data=excel_data,
      file_name="jarwis_podsumowanie_paragonow.xlsx",
      mime=(
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      ),
  )
