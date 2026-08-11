# Codzienny przegląd wiadomości → GitHub Pages

Skrypt generuje przegląd newsów (23 polskojęzyczne kanały RSS + Claude API),
renderuje go jako mobile-first HTML i publikuje na GitHub Pages, nadpisując
poprzednią wersję strony. Uruchamiany codziennie przez **GitHub Actions** —
zero własnej maszyny, zero PAT-a, zero utrzymania.

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
| `ANTHROPIC_API_KEY` | klucz z console.anthropic.com | użytkownik wkleja gotowy do GitHub Secrets — **Ty nie widzisz jego wartości i nie prosisz o wklejenie na czacie** |

Nic więcej — bez PAT-a, bez `GITHUB_OWNER`/`GITHUB_REPO`, bez `.env` na
serwerze (ten plik istnieje tylko do testów lokalnych, patrz sekcja 5).

**Checklista:**
- [ ] Repo jest publiczne (Settings → General → Danger Zone, jeśli trzeba zmienić)
- [ ] Sekret `ANTHROPIC_API_KEY` dodany w Settings → Secrets and variables → Actions
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
`docs/`, żeby nie mieszać jej z kodem w korzeniu repo.

## 2. Dodaj sekret

Ustawienia repo → **Secrets and variables → Actions → New repository
secret**:

- Name: `ANTHROPIC_API_KEY`
- Value: klucz z console.anthropic.com (`sk-ant-...`)

To jedyny sekret, jakiego potrzebuje workflow.

## 3. Uruchom i zweryfikuj

Zakładka **Actions** → „Codzienny przegląd wiadomości” → **Run workflow**
(przycisk po prawej) → uruchamia się natychmiast, nie trzeba czekać do 8:05.

Sprawdź w tej kolejności:

1. Przebieg w zakładce Actions kończy się na zielono.
2. Krok „Wygeneruj i opublikuj raport” w logu pokazuje `stop_reason=end_turn`
   i brak `ERROR`.
3. W repo pojawił się (lub zmienił) plik `docs/index.html` — nowy commit od
   „Daily News Bot”.
4. Strona pod adresem Pages (Settings → Pages pokazuje URL) pokazuje
   dzisiejszą datę w nagłówku. Może minąć do minuty, zanim Pages zbuduje
   nową wersję.

Jeśli krok 4 pokazuje starą treść mimo zielonego przebiegu — to zwykle
czas budowania Pages, nie błąd skryptu. Odśwież za minutę.

## 4. Harmonogram

Workflow ma **dwa** wpisy `cron`, bo GitHub Actions liczy czas wyłącznie w
UTC i nie zna named timezone — jeden trafia w 8:05 czasu letniego, drugi w
8:05 czasu zimowego. Krok „Sprawdź porę dnia” sprawdza aktualną godzinę w
Warszawie i po zmianie czasu automatycznie wybiera właściwy wpis — nic nie
trzeba przełączać ręcznie przy zmianie czasu.

GitHub nie gwarantuje uruchomienia co do minuty — przy dużym obciążeniu
platformy zdarza się opóźnienie rzędu kilkudziesięciu minut. Dla raportu
porannego to nieistotne.

## 5. Test lokalny (opcjonalnie)

Do debugowania skryptu bez czekania na Actions. Ten tryb **nie jest** tym,
czego używa produkcja — Actions ma własną konfigurację w `.yml`.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
chmod 600 .env
nano .env    # uzupełnij ANTHROPIC_API_KEY; REPO_DIR na ścieżkę tego repo
             # (bez GITHUB_TOKEN/OWNER/REPO w Actions, ale lokalnie
             # skrypt commituje i pushuje jak zwykłe repo git — potrzebny
             # jest zwykły dostęp `git push` skonfigurowany w tym katalogu)

python3 check_feeds.py       # kontrola kanałów RSS
python3 generate_report.py   # pełny przebieg — commituje i pushuje!
```

**Uwaga:** lokalne uruchomienie robi prawdziwy `git push` do `main`, tak
samo jak Actions. Jeśli chcesz tylko zobaczyć wynik bez publikacji,
zakomentuj wywołanie `publish_to_github(html_content)` w `main()` na czas
testu.

## 6. Skąd biorą się newsy — dwa tryby

Przełącznik `NEWS_SOURCE` (w `.env` lokalnie, w `env:` workflow-a w Actions).

### `rss` (domyślny)

23 polskojęzyczne kanały RSS (lista w `rss_sources.py`) dają ok. 900 wpisów
dziennie, po odsianiu starszych niż 36 h i duplikatów zostaje ~480 kandydatów.
Dalej dwa etapy:

1. **Wybór** — model dostaje kompaktową listę kandydatów i zwraca 50 indeksów
   przypisanych do (sekcja, region), w wymuszonym formacie JSON.
2. **Pisanie** — dla wybranych 50 pobieramy pełną treść artykułu
   (`trafilatura`) i model pisze z niej raport.

Dlaczego tak:

- **Linki nie mogą być zmyślone** — URL przychodzi z RSS-a, model go tylko
  przepisuje.
- **Wszystko po polsku**, łącznie z zagranicą (RMF24 Świat, Euronews i DW po
  polsku), więc klikając „Źródło" trafiasz na tekst do przeczytania, a nie na
  angielski oryginał.
- **Zero opłat za wyszukiwanie** i kilkukrotnie mniej tokenów wejścia.

Region (Polska/Świat) ustala model z **treści** newsa, nie z działu serwisu —
polski serwis sportowy pisze i o Ekstraklasie, i o Lidze Mistrzów.

Kanały RSS umierają po cichu (serwis zmienia adres). Workflow uruchamia
`check_feeds.py` przy każdym przebiegu (`continue-on-error`, więc padnięty
kanał nie przerywa raportu) — wynik widać w logu kroku „Sprawdź kanały RSS”.

### `claude_search`

Model sam szuka przez narzędzie `web_search`. Szersze pokrycie tematów, ale
kilkadziesiąt płatnych wyszukiwań i wielokrotnie większe zużycie tokenów
wejścia (każde wznowienie po `pause_turn` wysyła całą historię ponownie).

## 7. Jak to działa

1. Actions klonuje repo (`actions/checkout`) i instaluje zależności.
2. Skrypt zbiera newsy (RSS albo `web_search` — patrz sekcja 6) i pisze
   raport w Markdownie: 5 kategorii × Polska/Świat × 5 newsów, razem 50,
   z linkiem źródłowym pod każdym.
3. Markdown jest konwertowany na jeden plik `docs/index.html` z wbudowanym
   CSS (bez zewnętrznych zależności), zoptymalizowany pod telefon:
   responsywna szerokość, tryb ciemny, karty-newsy, szybka nawigacja po
   kategoriach.
4. Plik nadpisuje poprzedni `docs/index.html`, skrypt robi `git add`,
   `git commit`, `git push` na uwierzytelnieniu, które ustawił
   `actions/checkout` — żaden token nie jest budowany ręcznie ani widoczny
   w logach.
5. Jeśli generowanie treści się nie powiedzie (błąd API, zbyt krótka
   odpowiedź, przekroczony limit tokenów), skrypt **nie dotyka** repo —
   poprzednia wersja strony zostaje online, a przebieg Actions kończy się
   na czerwono z komunikatem błędu w logu.

## 8. Koszty i limity

W trybie `rss` (domyślnym) koszt to głównie tekst raportu — nie ma opłat
za wyszukiwanie. Trzy pokrętła kosztu, wszystkie w `env:` workflow-a:

- `ANTHROPIC_EFFORT` (`low`/`medium`/`high`/`xhigh`/`max`) — głębokość
  rozumowania modelu. Domyślnie `medium`, dla przeglądu newsów wystarcza.
- `ANTHROPIC_MAX_TOKENS` — górny limit; obejmuje myślenie modelu **oraz**
  tekst raportu. Za niski = raport urwany w połowie (skrypt to wykryje
  i przerwie, nie publikując niepełnej strony).
- Liczba newsów na sekcję (`PER_BUCKET` w `generate_report.py`) — mniej
  newsów to mniej tokenów wejścia (krótsza treść artykułów) i wyjścia.

W trybie `claude_search` dochodzi opłata za każde wyszukiwanie `web_search`
— sprawdź cennik na https://docs.claude.com. `ANTHROPIC_MAX_SEARCHES` w
`.env`/`env:` to twardy limit na uruchomienie.

GitHub Actions samo w sobie jest darmowe dla publicznego repo (bez limitu
minut miesięcznie).

## 9. Typowe błędy i diagnoza (dla Claude Code)

| Objaw | Najbardziej prawdopodobna przyczyna | Co sprawdzić |
|---|---|---|
| Krok „Wygeneruj i opublikuj raport” kończy się `Brakuje zmiennych w .env` | brak sekretu `ANTHROPIC_API_KEY` w Settings → Secrets and variables → Actions, albo literówka w jego nazwie | zakładka Secrets w ustawieniach repo — nazwa musi być dokładnie `ANTHROPIC_API_KEY` |
| `RuntimeError: Polecenie nie powiodło się: git push ...` | repo prywatne bez uprawnień workflow, albo brak `permissions: contents: write` w pliku `.yml` | sprawdź `permissions:` na górze `daily-news.yml`; sprawdź czy repo jest publiczne |
| Workflow w ogóle się nie uruchamia o czasie | Actions bywa opóźnione przy dużym obciążeniu GitHuba; zaplanowane workflow usypiają po 60 dniach bez commitów do repo (u nas nie powinno wystąpić, bo codzienny commit to resetuje) | zakładka Actions → historia uruchomień; „Run workflow” ręcznie jako test |
| Oba wpisy cron generują raport tego samego dnia | krok „Sprawdź porę dnia” nie zadziałał poprawnie | sprawdź log tego kroku — powinien pokazać godzinę w Warszawie i zdecydować `uruchom=tak`/`nie` tylko dla jednego z dwóch przebiegów |
| Odpowiedź modelu "podejrzanie krótka" | za mało kandydatów RSS (padło dużo kanałów) albo za niski `ANTHROPIC_MAX_TOKENS` | log kroku „Sprawdź kanały RSS”; zwiększ `ANTHROPIC_MAX_TOKENS` w `env:` |
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
