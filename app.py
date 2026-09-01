import io
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Menedżer Wydatków", page_icon="🧾", layout="centered"
)

st.title("📊 Menedżer Wydatków")
st.write(
    "Wrzuć zdjęcie paragonu, a aplikacja podzieli zakupy na kategorie,"
    " podsumuje wydatki i wygeneruje plik Excel!"
)

# 1. Wgrywanie pliku przez użytkownika
uploaded_file = st.file_uploader(
    "Wybierz zdjęcie paragonu...", type=["jpg", "jpeg", "png"]
)

if uploaded_file is not None:
  # Wyświetlenie wgranego zdjęcia
  st.image(
      uploaded_file, caption="Wgrany paragon", use_container_width=True
  )

  if st.button("🚀 Przetwórz paragon"):
    with st.spinner(
        "Analizuję paragon i wyciągam dane... (trwa przetwarzanie)"
    ):
      # --- TUTAJ W PRZYSZŁOŚCI MOŻESZ PODŁĄCZYĆ PRAWDZIWE API AI (np. Google Gemini) ---
      # Na ten moment używamy danych symulowanych, które idealnie pokazują działanie aplikacji
      dane_symulowane = [
          {
              "Produkt": "Mleko 3.2% 1l",
              "Typ": "Spożywcze",
              "Cena": 4.50,
              "Ilość": 2,
          },
          {
              "Produkt": "Chleb razowy",
              "Typ": "Spożywcze",
              "Cena": 6.00,
              "Ilość": 1,
          },
          {
              "Produkt": "Płyn do naczyń",
              "Typ": "Chemia",
              "Cena": 9.99,
              "Ilość": 1,
          },
          {
              "Produkt": "Kawa rozpuszczalna",
              "Typ": "Spożywcze",
              "Cena": 24.99,
              "Ilość": 1,
          },
          {
              "Produkt": "Bateria AA 4szt.",
              "Typ": "Różne",
              "Cena": 12.50,
              "Ilość": 1,
          },
      ]

      df = pd.DataFrame(dane_symulowane)
      df["Wartość (PLN)"] = df["Cena"] * df["Ilość"]

    # 2. Prezentacja wyników w tabeli
    st.success("Paragon został przetworzony pomyślnie!")
    st.subheader("🛒 Szczegółowa rozpiska zakupów:")
    st.dataframe(df, use_container_width=True)

    # 3. Podsumowanie kosztów według typów
    st.subheader("📈 Podsumowanie wydatków według kategorii:")
    podsumowanie = df.groupby("Typ")["Wartość (PLN)"].sum().reset_index()

    # Wykres słupkowy w Streamlit
    st.bar_chart(podsumowanie.set_index("Typ"))
    st.dataframe(podsumowanie, use_container_width=True)

    # 4. Generowanie pliku Excel w pamięci (używający openpyxl z requirements.txt)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
      df.to_excel(writer, sheet_name="Zakupy", index=False)
      podsumowanie.to_excel(writer, sheet_name="Podsumowanie", index=False)
    excel_data = output.getvalue()

    # 5. Przycisk do pobrania pliku Excel
    st.subheader("📥 Pobierz raport")
    st.download_button(
        label="Pobierz plik Excel z podsumowaniem",
        data=excel_data,
        file_name="analiza_paragonu_jarwis.xlsx",
        mime=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
