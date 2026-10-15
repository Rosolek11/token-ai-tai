# Token AI ($TAI)

Warstwa analityczna dla traderow Solany. Aplikacja przyjmuje adres portfela lub adres kontraktu tokena, zapisuje wynik analizy i prezentuje przeslanki do dalszego researchu. Nie stanowi porady inwestycyjnej.

## MVP

- analiza adresu portfela: aktywa, liczba transakcji, styl zachowania oraz przeslanki;
- analiza tokena: koncentracja posiadaczy, płynnosc, ryzyka i przeslanki;
- historia analiz i lista obserwowanych adresow;
- strona internetowa do wprowadzania adresu i przeglądania raportów, korzystająca z API;
- trwale przechowywana historia w SQLite (docelowo PostgreSQL).

Szczegoly zakresu, zespolu i decyzji technicznych znajduja sie w [karcie projektu](docs/karta-projektu.md). Backlog jest w [Jira Token AI](https://zut-team-p5etyzyo.atlassian.net/jira/software/projects/TAI/boards/2/backlog), a jego lokalna kopia w [docs/backlog.md](docs/backlog.md).

Obecny kod API to szkielet Sprintu 0: sprawdza format adresu i zwraca przykladowa odpowiedz. Nie pobiera jeszcze danych on-chain ani nie zapisuje analiz. Funkcje opisane powyzej stanowia plan MVP.

## Zespol

| Osoba | Rola | GitHub login |
| --- | --- | --- |
| Jakub Rossa | Lider | [Rosolek11](https://github.com/Rosolek11) |
| Filip Dejer | Tester | do uzupelnienia |
| Jakub Makutynowicz | Developer | do uzupelnienia |
| Michal Maszalo | Developer | do uzupelnienia |

Kazda osoba dopisuje swoj login GitHub w osobnym branchu i otwiera Pull Request do `main`. Instrukcja: [docs/onboarding-github.md](docs/onboarding-github.md).

## Szybki start

Wymagany jest Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Interaktywna dokumentacja API: `http://127.0.0.1:8000/docs`.

## Testy

```powershell
pytest
```

## Konwencje pracy

- Nie commitujemy bezposrednio do `main`.
- Branch: `feature/<krotki-opis>`, `fix/<krotki-opis>`, `docs/<krotki-opis>`.
- Commity sa zgodne z Conventional Commits, np. `feat: add wallet analysis endpoint`.
- Kazdy Pull Request wymaga jednego review i zielonego pipeline.
- Sekretow, kluczy API i tokenow nie umieszczamy w repozytorium.

Pelne zasady: [docs/zasady-zespolu.md](docs/zasady-zespolu.md).
