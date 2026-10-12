# Onboarding: GitHub zamiast GitLaba

## Co wykonuje lider po zalozeniu repozytorium

1. Tworzy prywatne repozytorium GitHub `token-ai-tai` i dodaje pozostalych czlonkow jako collaborators.
2. Dodaje prowadzacego jako collaborator, gdy tylko otrzyma jego login GitHub.
3. W **Settings -> Branches -> Add branch protection rule** tworzy regule dla `main`:
   - Require a pull request before merging;
   - Require 1 approval;
   - Require status checks to pass before merging: `test`;
   - Require branches to be up to date before merging;
   - Do not allow force pushes;
   - Include administrators.
4. W **Settings -> Secrets and variables -> Actions** dodaje przyszle sekrety (np. `TELEGRAM_BOT_TOKEN`, klucz dostawcy danych). Nigdy nie dodaje ich do plikow ani issue.

## Co wykonuje kazdy czlonek zespolu

1. Zaklada konto GitHub, dodaje klucz SSH i ustawia prawdziwe dane:

```powershell
git config --global user.name "Imie Nazwisko"
git config --global user.email "email_uzywany_w_GitHub"
```

2. Klonuje repozytorium przez SSH, tworzy branch `docs/add-<login>`, wpisuje login w tabeli README i otwiera Pull Request.
3. Przechodzi code review i scala PR dopiero po zielonym CI.

Nie przekazuj haseł ani tokenów w czacie. GitHub zapyta o autoryzacje w bezpiecznym oknie przegladarki lub przez GitHub CLI.
