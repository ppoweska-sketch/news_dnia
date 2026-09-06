# Codzienny przegląd wiadomości → GitHub Pages

Skrypt generuje przegląd newsów (23 polskojęzyczne kanały RSS + Gemini API),
renderuje go jako mobile-first HTML i publikuje na GitHub Pages, nadpisując
poprzednią wersję strony. Uruchamiany rano w dni robocze przez **GitHub
Actions** — zero własnej maszyny, zero PAT-a, zero utrzymania, zero opłat
(publiczne repo + darmowy poziom Gemini Flash).

5 sekcji × Polska/Świat × 5 newsów = 50 newsów dziennie. Sekcje: Ogólne
wydarzenia, Polityka, Biznes i giełda, Sport, Nauka.

---

## 🤖 Instrukcje dla Claude Code — przeczytaj to najpierw

Jeśli konfigurujesz ten projekt jako agent: wykonaj sekcje 1–3 **po kolei**,
weryfikując wynik po każdym kroku. Sekcje 4+ to dokumentacja referencyjna.

**Ten projekt sam jest repozytorium z GitHub Pages** — nie potrzeba osobnego
repo "ze stroną" ani drugiej maszyny. `.github/workflows/daily-news.yml`
klonuje repo, generuje `docs/index.html`, commituje i pushuje — wszystko
wewnątrz jednego uruchomienia Actions, z wbudowanym `GITHUB_TOKEN` (repo
musi być publiczne, żeby Actions było darmowe i bez limitu minut).

**Zapytaj użytkownika tylko o jedno:**

| Sekret | Co to jest | Kto to tworzy |
|---|---|---|
| `GEMINI_API_KEY` | darmowy klucz z aistudio.google.com/apikey | użytkownik wkleja gotowy do GitHub Secrets — **Ty nie widzisz jego wartości i nie prosisz o wklejenie na czacie** |

Nic więcej — bez PAT-a, bez `GITHUB_OWNER`/`GITHUB_REPO`, bez `.env` na
serwerze (ten plik istnieje tylko do testów lokalnych, patrz sekcja 5).

**Checklista:**
- [ ] Repo jest publiczne (Settings → General → Danger Zone, jeśli trzeba zmienić)
- [ ] Sekret `GEMINI_API_KEY` dodany w Settings → Secrets and variables → Actions
- [ ] GitHub Pages włączone: Settings → Pages → Source = „Deploy from a branch”, Branch = `main` / `docs`
- [ ] Workflow uruchomiony ręcznie (Actions → Codzienny przegląd wiadomości → Run workflow) i zakończony na zielono
- [ ] `docs/index.html` pojawił się w repo po uruchomieniu
- [ ] Strona Pages pokazuje dzisiejszą datę (może minąć do minuty na zbudowanie)

Jeśli którykolwiek krok się nie powiedzie — **zatrzymaj się i pokaż
użytkownikowi log z zakładki Actions**, zamiast zgadywać dalej.

---

## 1. Włącz GitHub Pages

Ustawienia repo → **Pages** → Source: „Deploy from a branch” → Branch:
`main`, katalog `/docs`. Workflow zapisuje wygenerowaną stronę właśnie do
`docs/`, żeby nie mieszać jej z kodem w korzeniu repo. Katalog `docs/`
pojawi się na liście dopiero po pierwszym udanym przebiegu workflow — jeśli
go nie widać teraz, wróć do tego kroku po sekcji 3.

## 2. Dodaj sekret

Ustawienia repo → **Secrets and variables → Actions → New repository
secret**:

- Name: `GEMINI_API_KEY`
- Value: darmowy klucz z **aistudio.google.com/apikey** (zaczyna się od `AI...`)

To jedyny sekret, jakiego potrzebuje workflow.

## 3. Uruchom i zweryfikuj

Zakładka **Actions** → „Codzienny przegląd wiadomości” → **Run workflow**
(przycisk po prawej) → uruchamia się natychmiast, nie trzeba czekać do rana.

Sprawdź w tej kolejności:

1. Przebieg w zakładce Actions kończy się na zielono.
2. Krok „Wygeneruj i opublikuj raport” w logu pokazuje `finish_reason=STOP`
   dla obu etapów i brak `ERROR`.
3. W repo pojawił się (lub zmienił) plik `docs/index.html` — nowy commit od
   „Daily News Bot”.
4. Strona pod adresem Pages (Settings → Pages pokazuje URL) pokazuje
   dzisiejszą datę w nagłówku. Może minąć do minuty, zanim Pages zbuduje
   nową wersję.

Jeśli krok 4 pokazuje starą treść mimo zielonego przebiegu — to zwykle
czas budowania Pages, nie błąd skryptu. Odśwież za minutę.

## 4. Harmonogram: rano, dni robocze

Jeden wpis `cron`: `50 4 * * 1-5` (4:50 UTC, poniedziałek–piątek). Dwie
rzeczy, o których trzeba wiedzieć:

- **GitHub Actions opóźnia zaplanowane uruchomienia**, czasem o kilka
  godzin — zaobserwowane (sierpień 2026): konsekwentnie 3,5–4,5h. Godzina
  cronu jest tak dobrana, żeby mimo tego opóźnienia raport realnie powstawał
  ok. 8:30–10:30 czasu warszawskiego. To szacunek z kilku dni obserwacji,
  nie gwarancja — jeśli po tygodniu raport systematycznie wychodzi poza to
  okno, skoryguj godzinę w pliku `.yml` na podstawie faktycznych czasów
  uruchomień (zakładka Actions pokazuje dokładny `created_at` każdego
  przebiegu).
- **Celowo bez wpisu zapasowego później w dniu.** Jeśli poranny przebieg
  faktycznie zawiedzie (nie tylko się opóźni), raport czeka do jutra — nie
  ma sensu generować popołudniowego "dogonienia", którego użytkownik i tak
  nie przeczyta o właściwej porze.

Krok „Sprawdź, czy raport dziś już powstał” nie pilnuje godziny — sprawdza
datę ostatniego commita do `docs/index.html` (czas warszawski) i generuje
tylko wtedy, gdy dzisiejszego jeszcze nie ma. Dzięki temu opóźnienia
GitHuba nie blokują niczego: raport powstanie o dowolnej porze, jeśli
tylko jeszcze go dziś nie było. Osobny, niezależny sprawdzian dnia tygodnia
w tym samym kroku chroni przed wygenerowaniem w weekend, nawet gdyby
piątkowe opóźnienie kiedyś wjechało w sobotę.

`workflow_dispatch` (ręczne „Run workflow”) omija oba te warunki — działa
o dowolnej porze i w dowolny dzień, do testów.

## 5. Test lokalny (opcjonalnie)

Do debugowania skryptu bez czekania na Actions. Ten tryb **nie jest** tym,
czego używa produkcja — Actions ma własną konfigurację w `.yml`.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
chmod 600 .env
nano .env    # uzupełnij GEMINI_API_KEY; REPO_DIR na ścieżkę tego repo
             # (lokalnie skrypt commituje i pushuje jak zwykłe repo git —
             # potrzebny jest zwykły dostęp `git push` skonfigurowany
             # w tym katalogu; w Actions to nie jest potrzebne, bo
             # actions/checkout ustawia uwierzytelnienie samo)

python3 check_feeds.py       # kontrola kanałów RSS
python3 generate_report.py   # pełny przebieg — commituje i pushuje!
```

**Uwaga:** lokalne uruchomienie robi prawdziwy `git push` do `main`, tak
samo jak Actions. Jeśli chcesz tylko zobaczyć wynik bez publikacji,
zakomentuj wywołanie `publish_to_github(html_content)` w `main()` na czas
testu.

## 6. Skąd biorą się newsy

23 polskojęzyczne kanały RSS (lista w `rss_sources.py`) dają ok. 900 wpisów
dziennie, po odsianiu starszych niż 36 h i duplikatów zostaje ~480
kandydatów. Dalej dwa etapy, oba przez Gemini API:

1. **Wybór** (`select_news`) — model dostaje kompaktową listę kandydatów
   i zwraca 50 indeksów przypisanych do (sekcja, region), w wymuszonym
   formacie JSON (`response_schema` z modelem Pydantic — Gemini gwarantuje
   zgodność ze schematem, nie trzeba parsować luźnego tekstu).
2. **Pisanie** — dla wybranych 50 pobieramy pełną treść artykułu
   (`trafilatura`) i model pisze z niej raport zwykłym tekstem (Markdown).

Dlaczego tak:

- **Linki nie mogą być zmyślone** — URL przychodzi z RSS-a, model go tylko
  przepisuje.
- **Wszystko po polsku**, łącznie z zagranicą (RMF24 Świat, Euronews i DW po
  polsku), więc klikając „Źródło" trafiasz na tekst do przeczytania, a nie na
  angielski oryginał.
- **Zero opłat** — RSS jest darmowy, a dwa wywołania dziennie mieszczą się
  z dużym zapasem w darmowym poziomie Gemini Flash.
- **Tytuły są zawsze redakcją modelu, nie kopią nagłówka źródła** — prompt
  wprost tego zabrania (patrz `WRITE_SYSTEM_PROMPT` w `generate_report.py`),
  co ogranicza ryzyko związane z prawami autorskimi do nagłówków prasowych.

Region (Polska/Świat) ustala model z **treści** newsa, nie z działu serwisu —
polski serwis sportowy pisze i o Ekstraklasie, i o Lidze Mistrzów.

Kanały RSS umierają po cichu (serwis zmienia adres). Workflow uruchamia
`check_feeds.py` przy każdym przebiegu (`continue-on-error`, więc padnięty
kanał nie przerywa raportu) — wynik widać w logu kroku „Sprawdź kanały RSS”.

## 7. Jak to działa

1. Actions klonuje repo (`actions/checkout`) i instaluje zależności.
2. Skrypt zbiera newsy z RSS i pisze raport w Markdownie: 5 kategorii ×
   Polska/Świat × 5 newsów, razem 50, z linkiem źródłowym pod każdym
   (sekcja 6 wyżej).
3. Markdown jest konwertowany na jeden plik `docs/index.html` z wbudowanym
   CSS (bez zewnętrznych zależności), zoptymalizowany pod telefon:
   responsywna szerokość, tryb ciemny, karty-newsy, szybka nawigacja po
   kategoriach. Strona ma `<meta name="robots" content="noindex, nofollow">`
   i towarzyszący `robots.txt` — to streszczenie cudzych treści, nie ma być
   indeksowane przez wyszukiwarki.
4. Plik nadpisuje poprzedni `docs/index.html`, skrypt robi `git add`,
   `git commit`, `git push` na uwierzytelnieniu, które ustawił
   `actions/checkout` — żaden token nie jest budowany ręcznie ani widoczny
   w logach. Jeśli push zostanie odrzucony (ktoś inny wypchnął coś w
   międzyczasie), skrypt sam robi `fetch` + `rebase` i próbuje ponownie
   (do 3 razy).
5. Jeśli generowanie treści się nie powiedzie (błąd API, zbyt krótka
   odpowiedź, przekroczony limit tokenów, zablokowana odpowiedź), skrypt
   **nie dotyka** repo — poprzednia wersja strony zostaje online, a przebieg
   Actions kończy się na czerwono z komunikatem błędu w logu.

## 8. Koszty i limity

Domyślny model to `gemini-3.6-flash` — rodzina Flash ma darmowy poziom
(Pro jest płatne od kwietnia 2026). Dwa wywołania dziennie mieszczą się w
nim z dużym zapasem; sprawdź aktualne limity na
https://ai.google.dev/gemini-api/docs/rate-limits, bo się zmieniają.

Pokrętła w `env:` workflow-a (i w `.env` lokalnie):

- `GEMINI_MODEL` — nazwy modeli zmieniają się regularnie; jeśli workflow
  zacznie kończyć się błędem „model not found”, sprawdź aktualną listę na
  https://ai.google.dev/gemini-api/docs/models i podmień tu.
- `GEMINI_MAX_OUTPUT_TOKENS` — górny limit tekstu raportu. Za niski = raport
  urwany w połowie (skrypt to wykryje i przerwie, nie publikując niepełnej
  strony).
- `GEMINI_THINKING_BUDGET` — domyślnie `0` (wyłączone myślenie). Zadanie to
  klasyfikacja i streszczanie z gotowych materiałów, nie złożone
  rozumowanie, więc wyłączone myślenie jest tańsze i szybsze bez utraty
  jakości. Zostaw puste, jeśli wybrany model nie obsługuje tego parametru.
- Liczba newsów na sekcję (`PER_BUCKET` w `generate_report.py`) — mniej
  newsów to mniej tokenów wejścia (krótsza treść artykułów) i wyjścia.

GitHub Actions samo w sobie jest darmowe dla publicznego repo (bez limitu
minut miesięcznie).

## 9. Typowe błędy i diagnoza (dla Claude Code)

| Objaw | Najbardziej prawdopodobna przyczyna | Co sprawdzić |
|---|---|---|
| Krok „Wygeneruj i opublikuj raport” kończy się `Brakuje zmiennych w .env` | brak sekretu `GEMINI_API_KEY` w Settings → Secrets and variables → Actions, albo literówka w jego nazwie | zakładka Secrets w ustawieniach repo — nazwa musi być dokładnie `GEMINI_API_KEY` |
| Błąd wspominający „model not found” albo 404 z Gemini | nazwa modelu w `GEMINI_MODEL` przestała istnieć (Google zmienia nazwy) | https://ai.google.dev/gemini-api/docs/models — podmień na aktualną nazwę z rodziny Flash/Flash-Lite |
| `RuntimeError: Polecenie nie powiodło się: git push ...` | repo prywatne bez uprawnień workflow, albo brak `permissions: contents: write` w pliku `.yml` | sprawdź `permissions:` na górze `daily-news.yml`; sprawdź czy repo jest publiczne |
| Workflow kończy krok „Sprawdź, czy raport dziś już powstał” z `uruchom=nie`, mimo że strona jest nieaktualna | krok poprawnie wykrył, że dzisiejszy raport już istnieje (patrz `git log -1 -- docs/index.html`) — albo dziś weekend | log tego kroku pokazuje dokładnie dzisiejszą datę, dzień tygodnia i datę ostatniego raportu |
| Workflow w ogóle się nie uruchamia o czasie | Actions bywa opóźnione przy dużym obciążeniu GitHuba (patrz sekcja 4); zaplanowane workflow usypiają po 60 dniach bez commitów do repo (u nas nie powinno wystąpić, bo codzienny commit to resetuje) | zakładka Actions → historia uruchomień, porównaj `created_at` z nominalną godziną cronu; „Run workflow” ręcznie jako test |
| Odpowiedź modelu "podejrzanie krótka" albo `finish_reason` inny niż `STOP` | za mało kandydatów RSS (padło dużo kanałów), za niski `GEMINI_MAX_OUTPUT_TOKENS`, albo model zablokował odpowiedź (SAFETY/RECITATION) | log kroku „Sprawdź kanały RSS”; log pokazuje dokładny `finish_reason` |
| Pages pokazuje 404 zamiast strony | GitHub Pages nie jest ustawione na branch/folder, do którego pushuje skrypt | Settings → Pages: Branch = `main`, katalog = `/docs` |

Jeśli błąd nie pasuje do żadnego z powyższych — pokaż użytkownikowi pełny
log z zakładki Actions zamiast próbować naprawić go na ślepo.

## 10. Rozszerzenia na później (opcjonalnie)

- Archiwum poprzednich raportów jako podstrony (`/archiwum/2026-08-11.html`)
  zamiast całkowitego nadpisywania.
- Powiadomienie (mail/Slack) gdy przebieg Actions się nie powiedzie —
  GitHub sam wysyła e-mail przy czerwonym przebiegu, jeśli nie wyłączono
  tego w ustawieniach powiadomień konta.
- Osobny plik `feed.xml` (RSS), żeby czytać raport w czytniku RSS.
