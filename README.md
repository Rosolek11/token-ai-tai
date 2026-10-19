# Token AI ($TAI)

Warstwa analityczna dla traderow Solany. Aplikacja przyjmuje adres portfela lub adres kontraktu tokena, zapisuje wynik analizy i prezentuje przeslanki do dalszego researchu. Nie stanowi porady inwestycyjnej.

## MVP

- analiza adresu portfela: aktywa, liczba transakcji, styl zachowania oraz przeslanki;
- analiza tokena: koncentracja posiadaczy, płynnosc, ryzyka i przeslanki;
- historia analiz i lista obserwowanych adresow;
- strona internetowa do wprowadzania adresu i przeglądania raportów, korzystająca z API;
- trwale przechowywana historia w SQLite (docelowo PostgreSQL).

Szczegoly zakresu, zespolu i decyzji technicznych znajduja sie w [karcie projektu](docs/karta-projektu.md). Backlog jest w [Jira Token AI](https://zut-team-p5etyzyo.atlassian.net/jira/software/projects/TAI/boards/2/backlog), a jego lokalna kopia w [docs/backlog.md](docs/backlog.md).

Obecny kod API to szkielet: sprawdza format adresu i zwraca przykladowa odpowiedz. Strona startowa i przelaczany podglad Token/Portfel sa gotowe, ale formularz analizy, pobieranie danych on-chain, integracje z dostawcami i zapis analiz sa dopiero planowane. Wykres na stronie jest ilustracja, nie danymi rynkowymi.

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
python -m uvicorn app.main:app --reload
```

Strona: `http://127.0.0.1:8000/`. Interaktywna dokumentacja API: `http://127.0.0.1:8000/docs`.
`GET /health` sluzy do sprawdzenia serwera. Adres API dla interfejsu mozna ustawic przez `PUBLIC_API_BASE_URL` (pusty oznacza ten sam serwer); publiczny adres jest udostepniany przegladarce przez `GET /api/client-config`.
Opcjonalne klucze dostawcow i AI sa czytane wylacznie ze zmiennych srodowiskowych. Przykladowe nazwy sa w `.env.example`; aplikacja nie laduje pliku `.env` automatycznie. Plik `.env` pozostaje lokalny i nie nalezy dodawac go do Git.

## Testy

```powershell
python -m pytest
```

## Konwencje pracy

- Nie commitujemy bezposrednio do `main`.
- Branch: `feature/<krotki-opis>`, `fix/<krotki-opis>`, `docs/<krotki-opis>`.
- Commity sa zgodne z Conventional Commits, np. `feat: add wallet analysis endpoint`.
- Kazdy Pull Request wymaga jednego review i zielonego pipeline.
- Sekretow, kluczy API i tokenow nie umieszczamy w repozytorium.

Pelne zasady: [docs/zasady-zespolu.md](docs/zasady-zespolu.md).
