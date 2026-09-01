import io
import os
from google import genai
import pandas as pd
from PIL import Image
import streamlit as st

st.set_page_config(
    page_title="Jarwis - Menedżer Paragonów", page_icon="🧾", layout="centered"
)

st.title("📊 Jarwis - Inteligentny Analizator Paragonów")
st.write(
    "Wrzuć zdjęcie paragonu z Castoramy lub innego sklepu, a Jarwis odczyta"
    " pozycje, dopasuje kategorie i przygotuje Excela!"
)

# Konfiguracja klucza API (można wpisać klucz w Secrets w Streamlit lub podać w panelu bocznym)
st.sidebar.header("🔑 Ustawienia AI")
api_key_input = st.sidebar.text_input(
    "Podaj klucz Google Gemini API", type="password"
)


# Sprawdzenie klucza (ze Streamlit Secrets lub z panelu bocznego)
api_key = api_key_input or st.secrets.get("GEMINI_API_KEY")

uploaded_file = st.file_uploader(
    "Wybierz zdjęcie paragonu...", type=["jpg", "jpeg", "png"]
)

if uploaded_file is not None:
  image = Image.open(uploaded_file)
  st.image(image, caption="Wgrany paragon", use_container_width=True)

  if st.button("🚀 Przetwórz paragon przez Jarwisa"):
    if not api_key:
      st.error(
          "⚠️ Musisz podać klucz Google Gemini API w panelu bocznym po lewej"
          " stronie!"
      )
    else:
      with st.spinner("🤖 Jarwis analizuje Twój paragon... Proszę czekać."):
        try:
          # Inicjalizacja klienta Google GenAI
          client = genai.Client(api_key=api_key)

          # Prompt wymuszający strukturę danych z paragonu
          prompt = """
                    Przeanalizuj to zdjęcie paragonu. Wypisz wszystkie zakupione produkty w formacie JSON (jako lista obiektów).
                    Każdy obiekt musi mieć dokładnie te klucze:
                    - "Produkt": nazwa produktu z paragonu
                    - "Typ": kategoria produktu (np. Narzędzia, Ogród, Chemia, Materiały budowlane, Inne)
                    - "Cena": cena jednostkowa brutto jako liczba (float)
                    - "Ilość": ilość jako liczba całkowita lub zmiennoprzecیینa (float)

                    Zwróć TYLKO czysty ciąg JSON, bez dodatkowego formatowania markdown (bez ```json ... ```), sam JSON.
                    """

          # Wywołanie modelu multimodalnego (Gemini 2.5 Flash / 1.5 Flash)
          response = client.models.generate_content(
              model="gemini-2.5-flash", contents=[image, prompt]
          )

          # Oczyszczenie odpowiedzi z ewentualnych znaczników markdown
          clean_text = (
              response.text.strip()
              .replace("```json", "")
              .replace("```", "")
              .strip()
          )

          import json

          dane_paragonu = json.loads(clean_text)

          df = pd.DataFrame(dane_paragonu)
          df["Wartość (PLN)"] = df["Cena"] * df["Ilość"]

          st.success("✅ Paragon został pomyślnie zanalizowany przez Jarwisa!")

          # Tabela wyników
          st.subheader("🛒 Szczegółowa rozpiska zakupów:")
          st.dataframe(df, use_container_width=True)

          # Podsumowanie
          st.subheader("📈 Podsumowanie wydatków według kategorii:")
          podsumowanie = df.groupby("Typ")["Wartość (PLN)"].sum().reset_index()
          st.bar_chart(podsumowanie.set_index("Typ"))
          st.dataframe(podsumowanie, use_container_width=True)

          # Generowanie pliku Excel
          output = io.BytesIO()
          with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Zakupy", index=False)
            podsumowanie.to_excel(writer, sheet_name="Podsumowanie", index=False)
          excel_data = output.getvalue()

          st.subheader("📥 Pobierz raport")
          st.download_button(
              label="Pobierz plik Excel z podsumowaniem",
              data=excel_data,
              file_name="analiza_paragonu_jarwis.xlsx",
              mime=(
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              ),
          )

        except Exception as e:
          st.error(f"Wystąpił błąd podczas analizy obrazu przez AI: {e}")
