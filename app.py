import pandas as pd
import streamlit as st

st.title("📊 Inteligentny Menedżer Paragonów")
st.write(
    "Wrzuć zdjęcie paragonu, a aplikacja podzieli zakupy na kategorie i wygeneruje plik Excel!"
)

# 1. Wgrywanie pliku
uploaded_file = st.file_uploader(
    "Wybierz zdjęcie paragonu...", type=["jpg", "jpeg", "png"]
)

if uploaded_file is not None:
  # Wyświetlenie zdjęcia
  st.image(
      uploaded_file, caption="Wgrany paragon", use_container_width=True
  )

  if st.button("Przetwórz paragon"):
    with st.spinner("Analizuję paragon... (tutaj działa AI/OCR)"):
      # --- TUTAJ NASTĘPUJE INTEGRACJA Z AI / OCR ---
      # Symulujemy wynik, jaki zwraca np. model AI:
      dane_symulowane = [
          {
              "Produkt": "Mleko 3.2%",
              "Typ": "Spożywcze",
              "Cena": 4.50,
              "Ilość": 2,
          },
          {"Produkt": "Chleb razowy", "Typ": "Spożywcze", "Cena": 6.00, "Ilość": 1},
          {
              "Produkt": "Płyn do naczyń",
              "Typ": "Chemia",
              "Cena": 9.99,
              "Ilość": 1,
          },
      ]

      df = pd.DataFrame(dane_symulowane)
      df["Wartość"] = df["Cena"] * df["Ilość"]

    # 2. Prezentacja wyników w tabeli
    st.success("Paragon został przetworzony pomyślnie!")
    st.subheader("Rozpiska zakupów:")
    st.dataframe(df)

    # 3. Podsumowanie kosztów
    st.subheader("Podsumowanie według typów:")
    podsumowanie = df.groupby("Typ")["Wartość"].sum().reset_index()
    st.bar_chart(podsumowanie.set_index("Typ"))
    st.dataframe(podsumowanie)

    # 4. Generowanie pliku Excel
    @st.cache_data
    def convert_df_to_excel(df_data, summary_data):
      # Można zapisać do pliku Excel z wieloma arkuszami
      output = pd.ExcelWriter("podsumowanie_zakupów.xlsx", engine="openpyxl")
      df_data.to_excel(output, sheet_name="Zakupy", index=False)
      summary_data.to_excel(output, sheet_name="Podsumowanie", index=False)
      output.close()
      with open("podsumowanie_zakupów.xlsx", "rb") as f:
        return f.read()

    excel_file = convert_df_to_excel(df, podsumowanie)

    st.download_button(
        label="📥 Pobierz raport Excel",
        data=excel_file,
        file_name="paragon_analiza.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
