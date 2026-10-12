# Zasady zespolu

## Definition of Done

Zadanie jest ukonczone, gdy ma kryteria akceptacji, implementacje na osobnym branchu, testy adekwatne do zmiany, zaktualizowana dokumentacje (jezeli potrzebna), zielony pipeline oraz zaakceptowany Pull Request.

## Review i komunikacja

- Kazdy PR ma opis: co zmienia, jak zostal przetestowany i link do zadania Jira.
- Co najmniej jedna osoba poza autorem zatwierdza PR.
- Blokady i decyzje techniczne komunikujemy na uzgodnionym kanale zespolowym.
- Spotkanie robocze odbywa sie raz w tygodniu; lider aktualizuje status Sprintu.

## AI

AI moze pomagac w analizie, szkielecie kodu i testach, ale autor PR odpowiada za zrozumienie, bezpieczenstwo i poprawne dzialanie zmian. Do promptow nie wklejamy sekretow, danych prywatnych ani kluczy API. Kod wygenerowany przez AI przechodzi normalne review i testy.

## Konwencje

- Branch: `feature/`, `fix/`, `docs/`, `test/`, `chore/`.
- Commit: Conventional Commits, np. `test: cover invalid wallet address`.
- Jeden logiczny temat na Pull Request.
