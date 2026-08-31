import ollama
import openpyxl
import pyautogui
import time
import os
import json
import csv
from pathlib import Path
from openpyxl import Workbook

# ================== KONFIGURACJA ==================
MODEL = "qwen2.5:7b"          # zmień na swój model jeśli chcesz
pyautogui.FAILSAFE = True     # przesuń mysz w lewy górny róg = natychmiastowy stop
pyautogui.PAUSE = 0.3         # mała przerwa między akcjami
# ==================================================

SYSTEM_PROMPT = """
Jesteś lokalnym asystentem automatyzacji na Windows.
Odpowiadasz WYŁĄCZNIE poprawnym JSON-em w formacie:

{
  "actions": [
    {"type": "nazwa_akcji", ...parametry...},
    ...
  ]
}

Dostępne akcje:

1. read_file
   {"type": "read_file", "path": "pełna_ścieżka_do_pliku"}

2. create_excel
   {"type": "create_excel", "path": "ścieżka.xlsx", "data": [["nagłówek1", "nagłówek2"], ["wartość1", "wartość2"]]}

3. type_text
   {"type": "type_text", "text": "tekst do wpisania"}

4. click
   {"type": "click", "x": 100, "y": 200}

5. hotkey
   {"type": "hotkey", "keys": ["ctrl", "c"]}

6. open_app
   {"type": "open_app", "name": "excel"}   # możliwe: excel, notepad, explorer, chrome

7. wait
   {"type": "wait", "seconds": 1.5}

8. done
   {"type": "done", "message": "Zadanie wykonane"}

Zasady:
- Zawsze zwracaj tylko JSON, bez żadnego dodatkowego tekstu.
- Jeśli nie wiesz jak coś zrobić – użyj akcji done z komunikatem.
- Ścieżki podawaj w formacie Windows (np. C:\\\\Users\\\\Nazwa\\\\Desktop\\\\plik.csv)
"""

def execute_action(action: dict) -> str:
    t = action.get("type")

    try:
        if t == "read_file":
            path = action["path"]
            if not os.path.exists(path):
                return f"Błąd: plik nie istnieje → {path}"

            # Obsługa CSV
            if path.lower().endswith(".csv"):
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                return f"CSV wczytany ({len(rows)} wierszy):\n{rows[:10]}..."  # pokazujemy tylko początek

            # Zwykły tekst
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return f"Plik wczytany ({len(content)} znaków):\n{content[:500]}..."

        elif t == "create_excel":
            path = action["path"]
            data = action.get("data", [])

            wb = Workbook()
            ws = wb.active
            ws.title = "Dane"

            for row in data:
                ws.append(row)

            # Tworzymy folder jeśli nie istnieje
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            wb.save(path)
            return f"Utworzono Excel: {path}"

        elif t == "type_text":
            text = action.get("text", "")
            pyautogui.write(text, interval=0.02)
            return f"Wpisano tekst ({len(text)} znaków)"

        elif t == "click":
            x = int(action["x"])
            y = int(action["y"])
            pyautogui.click(x, y)
            return f"Kliknięto w ({x}, {y})"

        elif t == "hotkey":
            keys = action.get("keys", [])
            pyautogui.hotkey(*keys)
            return f"Wysłano skrót: {' + '.join(keys)}"

        elif t == "open_app":
            name = action.get("name", "").lower()
            apps = {
                "excel": "excel",
                "notepad": "notepad",
                "explorer": "explorer",
                "chrome": "chrome",
                "calc": "calc",
            }
            if name in apps:
                os.system(f"start {apps[name]}")
                time.sleep(1.5)
                return f"Otwarto: {name}"
            return f"Nie znam aplikacji: {name}"

        elif t == "wait":
            seconds = float(action.get("seconds", 1))
            time.sleep(seconds)
            return f"Czekałem {seconds}s"

        elif t == "done":
            return action.get("message", "Gotowe")

        else:
            return f"Nieznana akcja: {t}"

    except Exception as e:
        return f"Błąd przy akcji {t}: {str(e)}"


def main():
    print("=" * 60)
    print("  Lokalny Jarvis (Windows) – komendy tekstowe")
    print("  Wpisz 'exit' żeby wyjść")
    print("  FAILSAFE: przesuń mysz w lewy górny róg = STOP")
    print("=" * 60)

    while True:
        user_input = input("\nTy > ").strip()
        if user_input.lower() in ["exit", "quit", "wyjście"]:
            print("Koniec.")
            break

        if not user_input:
            continue

        print("Myślę...")

        try:
            response = ollama.chat(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_input}
                ],
                format="json",
                options={"temperature": 0.2}
            )

            content = response["message"]["content"]
            print("\nModel zwrócił:")
            print(content)

            data = json.loads(content)
            actions = data.get("actions", [])

            if not actions:
                print("Brak akcji do wykonania.")
                continue

            print("\nWykonuję akcje:")
            for i, action in enumerate(actions, 1):
                result = execute_action(action)
                print(f"  {i}. {result}")

        except json.JSONDecodeError:
            print("Model nie zwrócił poprawnego JSON-a. Spróbuj przeformułować komendę.")
        except Exception as e:
            print(f"Błąd: {e}")


if __name__ == "__main__":
    main()
