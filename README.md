# Token AI ($TAI)

Warstwa analityczna dla traderow Solany. Aplikacja przyjmuje adres portfela lub adres kontraktu tokena, zapisuje wynik analizy i prezentuje przeslanki do dalszego researchu. Nie stanowi porady inwestycyjnej.

## MVP

- analiza adresu portfela: aktywa, liczba transakcji, styl zachowania oraz przeslanki;
- analiza tokena: koncentracja posiadaczy, płynnosc, ryzyka i przeslanki;
- historia analiz i lista obserwowanych adresow;
- strona internetowa do wprowadzania adresu i przeglądania raportów, korzystająca z API;
- trwale przechowywana historia w SQLite (docelowo PostgreSQL).

Szczegoly zakresu, zespolu i decyzji technicznych znajduja sie w [karcie projektu](docs/karta-projektu.md). Backlog jest w [Jira Token AI](https://zut-team-p5etyzyo.atlassian.net/jira/software/projects/TAI/boards/2/backlog).

Formularz `/analysis` otwiera `/token/{address}`. Raport pokazuje stan ladowania, rzeczywiste dane rynkowe z DEX Screener, brak par lub czytelny blad z mozliwoscia ponowienia. Odswiezenie zachowuje adres w URL i ponownie pobiera snapshot. Raport korzysta z dzialajacego `POST /analyses/token` z TAI-7; osobny `POST /api/token-analyses` pozostaje szkieletem przyszlej kolejki, a nie zrodlem gotowego raportu. Wallet przyjmuje adres, ale nie ma jeszcze raportu aktywnosci. AI, pozostali dostawcy i historia analiz sa planowane. Wykres na stronie glownej jest ilustracja, nie danymi rynkowymi.

## Zespol

| Osoba | Rola | GitHub login |
| --- | --- | --- |
| Jakub Rossa | Lider | [Rosolek11](https://github.com/Rosolek11) |
| Filip Dejer | Tester | do uzupelnienia |
| Jakub Makutynowicz | Developer | [jakub-wq](https://github.com/jakub-wq) |
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

## Walidacja adresow API

`POST /analyses/token` i `POST /analyses/wallet` przyjmuja JSON z polem `address`,
np. `{"address":"So11111111111111111111111111111111111111112"}`.
Adres musi uzywac alfabetu Base58 Solany i po zdekodowaniu miec dokladnie 32 bajty
(32–44 znaki, z uwzglednieniem zer wiodacych zapisanych jako `1`).
Niepoprawny adres, brak pola, `null`, zly typ lub brak poprawnego ciala JSON
zwracaja HTTP `422` z `{"detail":"INVALID_ADDRESS"}` przed rozpoczeciem analizy
i wywolaniami dostawcow. Walidacja sprawdza format; nie potwierdza istnienia konta
ani tego, czy adres nalezy do portfela lub tokena.

## Dane rynkowe tokena

Przykladowe zapytanie (Wrapped SOL):

```bash
curl -X POST http://127.0.0.1:8000/analyses/token \
  -H 'Content-Type: application/json' \
  -d '{"address":"So11111111111111111111111111111111111111112"}'
```

Odpowiedz `201` zawiera `market_data`:

- `pairs`: pary Solany dla podanego tokena, ich adresy, DEX, URL, token bazowy i kwotowany oraz metryki;
- `price_usd`, `liquidity_usd`, `volume_24h_usd`, `price_change_24h_percent`: metryki jednej pary o najwiekszej znanej plynnosci, w ktorej szukany token jest bazowy;
- `primary_pair_address`: adres tej pary (bez sumowania wolumenow i plynnosci roznych par); przy remisie wybierana jest pierwsza para w odpowiedzi dostawcy;
- `source`, `source_url`: nazwa dostawcy i dokladny URL zapytania API;
- `updated_at`: czas pobrania UTC, a nie czas aktualizacji po stronie dostawcy;
- `status`: `ok` lub `no_data`, gdy dostawca zwrocil pusta liste albo `null`.

Brak metryki, `null` i pusty napis pozostaja `null`; rzeczywiste zero pozostaje zerem.
Cena oraz zmiana ceny w kazdej parze dotycza jej tokena bazowego. Pary, w ktorych
szukany token jest kwotowany, sa zwracane, ale nie sa wybierane do podsumowania;
jesli sa jedynymi parami, metryki podsumowania i `primary_pair_address` sa `null`.
Brak znanej plynnosci ma nizszy priorytet niz znane zero.
Wynik przechowuje czas i zrodlo w odpowiedzi; trwaly zapis do bazy jest osobnym etapem.

Adapter korzysta z publicznego endpointu
[`GET /token-pairs/v1/solana/{address}`](https://docs.dexscreener.com/api/reference),
bez klucza API, z timeoutem HTTP 10 s. Awaria HTTP, limit dostawcy lub niepoprawna
odpowiedz zwracaja `502 MARKET_DATA_UNAVAILABLE`, a timeout `504 MARKET_DATA_TIMEOUT`.
Bledy dostawcy nie sa traktowane jako brak par. Porownanie z Birdeye wymaga
osobnego potwierdzenia planu i nie jest uruchamiane przez te integracje.

## Testy

```powershell
python -m pytest
```

`tests/test_market_data.py` uzywa `httpx.MockTransport` i zapisanej odpowiedzi
`tests/fixtures/dexscreener_solana.json`: sprawdza metryki, wybor pary, czas i URL,
brak danych, zera, bledy dostawcy oraz walidacje przed zapytaniem. Testy nie lacza
sie z zewnetrznym API.

Testy zachowania JavaScript (Node.js 24, bez dodatkowych pakietow):

```bash
node --test tests/market_report.test.cjs tests/report_intro.test.cjs
```

Uruchamiaja wspolny kod, formularz i strone raportu z mockami DOM i HTTP: sprawdzaja
walidacje 32 bajtow, nawigacje do `/token/{address}`, ponowne wejscie z URL,
spinner, blokade duplikatow, formatowanie, zera, brak danych, timeouty, bledy
i ponawianie pobierania. Nie zastepuja testu w przegladarce.
Oba zestawy testow sa uruchamiane przez CI.

Wejscie na raport tokena odtwarza pelnoekranowa animacje interfejsu przez 3 sekundy.
Dane sa pobierane rownolegle: szybka odpowiedz nie skraca animacji, a wolniejsza
pozostawia zwykly stan oczekiwania po jej zakonczeniu. Odswiezenie samych danych
przyciskiem nie odtwarza intro. Pierscienie, logo, panele i napisy schodza sie
z krawedzi ekranu, po czym cala warstwa odslania raport. Zgodnie z wymaganiem
pelnego ruchu samo intro ma jawnie wlaczona animacje takze przy systemowej
preferencji ograniczonego ruchu; pozostale widoki nadal ja respektuja.
Osobny test sprawdza granice 2999/3000 ms,
zwolnienie blokady interakcji oraz powrot z pamieci przegladarki.

## Konwencje pracy

- Nie commitujemy bezposrednio do `main`.
- Branch: `feature/<krotki-opis>`, `fix/<krotki-opis>`, `docs/<krotki-opis>`.
- Commity sa zgodne z Conventional Commits, np. `feat: add wallet analysis endpoint`.
- Kazdy Pull Request wymaga jednego review i zielonego pipeline.
- Sekretow, kluczy API i tokenow nie umieszczamy w repozytorium.

Pelne zasady: [docs/zasady-zespolu.md](docs/zasady-zespolu.md).
