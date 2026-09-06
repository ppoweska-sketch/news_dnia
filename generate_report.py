#!/usr/bin/env python3
"""
generate_report.py
-------------------
Codziennie (uruchamiane z GitHub Actions) generuje przegląd najważniejszych
wiadomości (Polska/Świat x 5 kategorii x 5+5), renderuje mobile-first HTML
i publikuje na GitHub Pages, nadpisując poprzednią wersję strony.

Zbieranie newsów: kanały RSS (rss_collect.py) zbierają ~900 kandydatów za
darmo, dwuetapowo przez Gemini API — etap 1 wybiera z nich 50, etap 2 pisze
raport z pełnych treści artykułów. Linki źródłowe pochodzą z RSS-a, więc nie
da się ich zmyślić.

Dostawca modelu: Google Gemini (nie Anthropic) — model Flash ma darmowy
poziom wystarczający na dwa wywołania dziennie, więc codzienne uruchomienie
nie generuje żadnych opłat. Patrz GEMINI_MODEL w .env.example.

Wymaga pliku .env obok skryptu (patrz .env.example).
"""

import os
import sys
import subprocess
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel
from google import genai
from google.genai import types
import markdown as md

# --------------------------------------------------------------------------
# Konfiguracja / logowanie
# --------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "generate_report.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("daily-news-report")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_OWNER = os.environ.get("GITHUB_OWNER")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
REPO_DIR = os.environ.get("REPO_DIR")  # lokalna ścieżka do sklonowanego repo z Pages
# Nazwy modeli Gemini zmieniają się regularnie — jeśli ta przestanie działać
# (błąd "model not found"), sprawdź aktualną listę na
# https://ai.google.dev/gemini-api/docs/models i podmień tu albo w .env.
# Model musi być z rodziny Flash/Flash-Lite, żeby łapać się na darmowy
# poziom — modele Pro są płatne od kwietnia 2026.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_TOKENS = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "16000"))
# Budżet "myślenia" modelu w tokenach; 0 = wyłączone. Ten pipeline robi
# klasyfikację i streszczanie z gotowych materiałów, nie złożone rozumowanie
# — wyłączone myślenie jest tańsze i szybsze bez utraty jakości. Jeśli
# GEMINI_THINKING_BUDGET jest puste, w ogóle nie wysyłamy tego parametru
# (przydatne, gdyby wybrany model go nie obsługiwał).
THINKING_BUDGET = os.environ.get("GEMINI_THINKING_BUDGET", "0")

# strftime nie zna polskich nazw miesięcy bez ustawionego locale, którego
# nie ma gwarancji na świeżym serwerze — więc mapujemy je ręcznie.
POLISH_MONTHS = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia",
}


def polish_date(dt: datetime) -> str:
    return f"{dt.day} {POLISH_MONTHS[dt.month]} {dt.year}"


# Kolejność sekcji w raporcie. Używane przez oba tryby zbierania newsów.
CATEGORIES = ["Ogólne wydarzenia", "Polityka", "Biznes i giełda", "Sport", "Nauka"]
REGIONS = ["Polska", "Świat"]
PER_BUCKET = 5          # ile newsów na (kategoria, region)
MIN_PER_BUCKET = 3      # poniżej tego uznajemy raport za wybrakowany

# W GitHub Actions repo jest już sklonowane i uwierzytelnione przez
# actions/checkout, więc nie potrzebujemy ani tokena, ani ownera/repo —
# wystarczy zwykły `git push` na istniejącym remote.
IN_ACTIONS = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"

REQUIRED_VARS = {
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "REPO_DIR": REPO_DIR,
}
if not IN_ACTIONS:
    REQUIRED_VARS.update({
        "GITHUB_TOKEN": GITHUB_TOKEN,
        "GITHUB_OWNER": GITHUB_OWNER,
        "GITHUB_REPO": GITHUB_REPO,
    })

missing = [k for k, v in REQUIRED_VARS.items() if not v]
if missing:
    log.error(f"Brakuje zmiennych w .env: {', '.join(missing)}")
    sys.exit(1)

REPO_DIR = Path(REPO_DIR)
# Katalog, do którego trafia index.html. Domyślnie korzeń repo; w Actions
# ustawiamy "docs", żeby wygenerowana strona nie mieszała się z kodem.
SITE_DIR = REPO_DIR / os.environ.get("SITE_SUBDIR", "").strip("/") \
    if os.environ.get("SITE_SUBDIR", "").strip("/") else REPO_DIR

# --------------------------------------------------------------------------
# Klient Gemini — mały wspólny helper na finish_reason (dwa etapy go używają)
# --------------------------------------------------------------------------

def _gemini_client() -> genai.Client:
    return genai.Client(api_key=GEMINI_API_KEY)


def _thinking_config() -> types.ThinkingConfig | None:
    """None = nie wysyłaj parametru wcale (model użyje własnego domyślnego
    zachowania) — przydatne, gdyby wybrany model nie obsługiwał tego pola."""
    if THINKING_BUDGET == "":
        return None
    return types.ThinkingConfig(thinking_budget=int(THINKING_BUDGET))


def _finish_reason_name(response) -> str:
    """finish_reason bywa enumem albo stringiem zależnie od wersji SDK —
    sprowadzamy do jednej postaci do porównań i logów."""
    try:
        reason = response.candidates[0].finish_reason
    except (IndexError, AttributeError):
        return "BRAK_KANDYDATA"
    return getattr(reason, "name", str(reason))


# --------------------------------------------------------------------------
# Etap 1 (wybór newsów) i etap 2 (pisanie raportu)
# --------------------------------------------------------------------------

SELECT_SYSTEM_PROMPT = """Jesteś redaktorem wydania. Dostajesz listę \
kandydatów na newsy zebranych dzisiaj z kanałów RSS polskich i światowych \
mediów. Twoim zadaniem jest wybrać najważniejsze i przypisać je do sekcji \
wydania. Nie piszesz jeszcze treści — tylko wybierasz.

Kryteria wyboru:
- Waga i świeżość — wydarzenia dnia, nie evergreeny i nie poradniki.
- Różnorodność — nie wybieraj kilku wariantów tej samej historii.
- Odrzucaj materiały sponsorowane, plotki, quizy, konkursy i czyste \
zapowiedzi programów telewizyjnych.

Wszystkie źródła są polskojęzyczne, także te opisujące zagranicę. Dane \
w nawiasie przy kandydacie (dział serwisu) to WYŁĄCZNIE podpowiedź — sekcję \
i region przypisujesz na podstawie rzeczywistej treści newsa:
- "Polska" = wydarzenie dzieje się w Polsce albo dotyczy przede wszystkim \
Polski i Polaków.
- "Świat" = wydarzenie zagraniczne bez bezpośredniego polskiego wątku.
Polski serwis sportowy pisze i o Ekstraklasie, i o Lidze Mistrzów — decyduje \
to, czego news dotyczy, a nie skąd pochodzi."""


class Pick(BaseModel):
    idx: int
    category: Literal["Ogólne wydarzenia", "Polityka", "Biznes i giełda", "Sport", "Nauka"]
    region: Literal["Polska", "Świat"]


class Picks(BaseModel):
    picks: list[Pick]


def select_news(client, candidates) -> dict[tuple[str, str], list]:
    """Etap 1 — model wybiera newsy i rozkłada je na (kategoria, region)."""
    from rss_collect import candidates_digest

    wanted = len(CATEGORIES) * len(REGIONS) * PER_BUCKET
    prompt = f"""Dzisiejsza data: {polish_date(datetime.now())}.

Poniżej {len(candidates)} kandydatów na newsy. Wybierz dokładnie \
{PER_BUCKET} do każdej pary (sekcja, region) — razem {wanted} newsów.

Sekcje: {", ".join(CATEGORIES)}
Regiony: {", ".join(REGIONS)}

Zasady:
- Każdy indeks może wystąpić tylko raz w całym wyborze.
- Region ustal z treści newsa, nie z działu serwisu.
- Zwróć wyłącznie numery indeksów w podanym formacie, bez komentarza.

KANDYDACI:
{candidates_digest(candidates)}"""

    log.info(f"Etap 1: wybór {wanted} newsów z {len(candidates)} kandydatów (model={GEMINI_MODEL})...")
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SELECT_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=Picks,
            max_output_tokens=12000,
            thinking_config=_thinking_config(),
        ),
    )

    reason = _finish_reason_name(response)
    if reason == "MAX_TOKENS":
        raise RuntimeError("Etap 1 przekroczył limit tokenów — zwiększ max_output_tokens.")
    if reason not in ("STOP", "BRAK_KANDYDATA"):
        # BRAK_KANDYDATA = brak response.candidates — obsłużone niżej przez
        # brak response.parsed. Każdy inny nietypowy powód (SAFETY, RECITATION,
        # ...) traktujemy jako błąd, żeby nie próbować parsować pustki.
        raise RuntimeError(f"Etap 1: model zakończył z nietypowym powodem: {reason}")

    picks_obj: Picks | None = getattr(response, "parsed", None)
    if picks_obj is None:
        if not response.text:
            raise RuntimeError("Etap 1 nie zwrócił żadnej treści.")
        try:
            picks_obj = Picks.model_validate_json(response.text)
        except Exception as exc:
            raise RuntimeError(f"Etap 1: odpowiedź nie jest poprawnym JSON-em wyboru: {exc}")

    by_idx = {c.idx: c for c in candidates}
    buckets: dict[tuple[str, str], list] = {
        (cat, reg): [] for cat in CATEGORIES for reg in REGIONS
    }
    used: set[int] = set()

    for pick in picks_obj.picks:
        cand = by_idx.get(pick.idx)
        if cand is None or pick.idx in used:
            continue  # halucynowany lub zdublowany indeks — pomijamy
        # Regionu nie weryfikujemy względem kanału: źródła są polskojęzyczne,
        # więc "Polska"/"Świat" wynika z treści newsa, a nie z tego, skąd pochodzi.
        bucket = buckets[(pick.category, pick.region)]
        if len(bucket) >= PER_BUCKET:
            continue
        bucket.append(cand)
        used.add(pick.idx)

    thin = [f"{cat}/{reg} ({len(v)})" for (cat, reg), v in buckets.items()
            if len(v) < MIN_PER_BUCKET]
    if thin:
        raise RuntimeError(
            "Za mało newsów w sekcjach: " + ", ".join(thin) +
            f". Sprawdź, czy kanały RSS dla tych tematów działają (python3 check_feeds.py)."
        )

    total = sum(len(v) for v in buckets.values())
    short = [f"{cat}/{reg} ({len(v)})" for (cat, reg), v in buckets.items()
             if len(v) < PER_BUCKET]
    if short:
        log.warning(f"Sekcje poniżej {PER_BUCKET} newsów: {', '.join(short)}")
    log.info(f"Etap 1: wybrano {total} newsów.")
    return buckets


WRITE_SYSTEM_PROMPT = """Jesteś redaktorem tworzącym codzienny skrót newsów \
w stylu aplikacji Infopiguła. Piszesz precyzyjnie, rzeczowo, bez lania wody, \
w języku polskim.

Dostajesz gotowy zestaw newsów wraz z treścią artykułów źródłowych. \
Opisujesz WYŁĄCZNIE to, co jest w dostarczonych materiałach — nigdy nie \
dodajesz faktów spoza nich i nigdy nie zmieniasz podanych adresów źródeł. \
Jeśli materiał jest ubogi, piszesz krócej, zamiast zmyślać szczegóły.

Piszesz streszczenie własnymi słowami — relacjonujesz fakty, nie \
przepisujesz sformułowań źródła. Dotyczy to szczególnie tytułu: zawsze \
układasz go sam, jako zdanie opisujące istotę newsa. Nigdy nie kopiujesz \
ani nie parafrazujesz blisko nagłówka z materiału źródłowego (`--- {źródło} | \
{tytuł źródłowy}`) — ten tytuł to tylko informacja, o czym jest news, a nie \
wzór do naśladowania czy skopiowania."""


def build_write_prompt(buckets: dict[tuple[str, str], list]) -> str:
    today = polish_date(datetime.now())
    parts = [
        f"Dzisiejsza data to {today}. Napisz przegląd wiadomości w formacie "
        f"Markdown.\n\n"
        "STRUKTURA (dokładnie taka, nic więcej):\n"
        f"- Nagłówek H1 z datą.\n"
        f"- Sekcje (H2) w kolejności: {', '.join(CATEGORIES)}.\n"
        "- W każdej sekcji podsekcje (H3): \"Polska\" i \"Świat\".\n"
        "- Każdy news: pogrubiony tytuł (1 zdanie) NAPISANY PRZEZ CIEBIE — nigdy "
        "nie kopiuj ani nie parafrazuj blisko nagłówka podanego przy materiale "
        "źródłowym — a potem opis 5-10 zdań własnymi słowami i osobna linia "
        "z linkiem w formacie: `Źródło: <URL>`.\n"
        "- Użyj DOKŁADNIE tych newsów i tych adresów źródeł, które podano "
        "niżej — nie dodawaj własnych, nie pomijaj żadnego, nie zmieniaj URL-i.\n"
        "- Pisz zwięźle, unikaj powtórzeń między newsami.\n"
        "- Nie dodawaj wstępu ani podsumowania na końcu.\n\n"
        "MATERIAŁY:\n"
    ]

    for cat in CATEGORIES:
        for reg in REGIONS:
            items = buckets.get((cat, reg), [])
            if not items:
                continue
            parts.append(f"\n=== {cat} / {reg} ===\n")
            for c in items:
                body = c.full_text or c.summary or "(brak treści — opisz z tytułu)"
                parts.append(
                    f"\n--- {c.source} | {c.title}\n"
                    f"Źródło: {c.url}\n"
                    f"Treść: {body}\n"
                )
    return "".join(parts)


def generate_markdown_report() -> str:
    """RSS zbiera kandydatów, Gemini wybiera (etap 1) i pisze (etap 2)."""
    from rss_collect import collect_candidates, fetch_article_texts

    client = _gemini_client()

    candidates = collect_candidates()
    buckets = select_news(client, candidates)

    selected = [c for items in buckets.values() for c in items]
    log.info(f"Etap 2: pobieram treść {len(selected)} artykułów...")
    fetch_article_texts(selected)

    log.info(f"Etap 2: piszę raport (model={GEMINI_MODEL})...")
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=build_write_prompt(buckets),
        config=types.GenerateContentConfig(
            system_instruction=WRITE_SYSTEM_PROMPT,
            max_output_tokens=MAX_TOKENS,
            thinking_config=_thinking_config(),
        ),
    )

    reason = _finish_reason_name(response)
    usage = getattr(response, "usage_metadata", None)
    log.info(
        f"Etap 2: finish_reason={reason}, "
        f"tokeny wy={getattr(usage, 'candidates_token_count', '?')}, "
        f"we={getattr(usage, 'prompt_token_count', '?')}"
    )

    if reason == "MAX_TOKENS":
        raise RuntimeError(
            f"Model wyczerpał limit {MAX_TOKENS} tokenów — raport jest ucięty. "
            "Zwiększ GEMINI_MAX_OUTPUT_TOKENS w .env."
        )
    if reason not in ("STOP", "BRAK_KANDYDATA"):
        raise RuntimeError(f"Etap 2: model zakończył z nietypowym powodem: {reason}")

    full_text = (response.text or "").strip()

    if not full_text or len(full_text) < 500:
        raise RuntimeError("Odpowiedź modelu jest podejrzanie krótka lub pusta.")

    return full_text


# --------------------------------------------------------------------------
# Render HTML (mobile-first)
# --------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Przegląd wiadomości — {date_human}</title>
<meta name="description" content="Codzienny skrót najważniejszych wiadomości: Polska i Świat.">
<meta name="robots" content="noindex, nofollow">
<style>
  :root {{
    color-scheme: light dark;
    --bg: #ffffff;
    --fg: #1a1a1a;
    --muted: #6b6b6b;
    --accent: #b3261e;
    --card-bg: #f7f7f7;
    --border: #e5e5e5;
    --link: #0b5fff;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #121212;
      --fg: #f0f0f0;
      --muted: #a0a0a0;
      --accent: #ff6b60;
      --card-bg: #1c1c1c;
      --border: #2a2a2a;
      --link: #6ea8ff;
    }}
  }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-text-size-adjust: 100%; }}
  body {{
    margin: 0;
    padding: 0 0 3rem 0;
    background: var(--bg);
    color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.55;
    font-size: 17px;
  }}
  header {{
    padding: max(1.25rem, env(safe-area-inset-top)) 1.25rem 1rem 1.25rem;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    background: var(--bg);
    z-index: 10;
  }}
  header h1 {{
    margin: 0 0 .25rem 0;
    font-size: 1.35rem;
  }}
  header .subtitle {{
    color: var(--muted);
    font-size: .9rem;
  }}
  nav.chips {{
    display: flex;
    gap: .5rem;
    overflow-x: auto;
    padding: .75rem 1.25rem 0 1.25rem;
    -webkit-overflow-scrolling: touch;
  }}
  nav.chips a {{
    flex: 0 0 auto;
    padding: .4rem .85rem;
    border-radius: 999px;
    background: var(--card-bg);
    border: 1px solid var(--border);
    color: var(--fg);
    text-decoration: none;
    font-size: .85rem;
    white-space: nowrap;
  }}
  main {{
    padding: .5rem 1.25rem 0 1.25rem;
    max-width: 640px;
    margin: 0 auto;
  }}
  h2 {{
    margin-top: 2.2rem;
    font-size: 1.4rem;
    border-bottom: 2px solid var(--accent);
    padding-bottom: .3rem;
  }}
  h3 {{
    margin-top: 1.4rem;
    font-size: 1.05rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .04em;
  }}
  article.news {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: .9rem 1rem;
    margin: .75rem 0;
  }}
  article.news p {{ margin: .4rem 0; }}
  article.news strong {{ font-size: 1.02rem; }}
  article.news a.source {{
    display: inline-block;
    margin-top: .5rem;
    font-size: .85rem;
    color: var(--link);
    text-decoration: none;
    word-break: break-word;
  }}
  a {{ color: var(--link); }}
  footer {{
    max-width: 640px;
    margin: 2.5rem auto 0 auto;
    padding: 0 1.25rem;
    color: var(--muted);
    font-size: .8rem;
    text-align: center;
  }}
</style>
</head>
<body>
<header>
  <h1>📰 Przegląd wiadomości</h1>
  <div class="subtitle">{date_human} · zaktualizowano {time_human}</div>
</header>
<nav class="chips">
  <a href="#ogolne">Ogólne</a>
  <a href="#polityka">Polityka</a>
  <a href="#biznes">Biznes i giełda</a>
  <a href="#sport">Sport</a>
  <a href="#nauka">Nauka</a>
</nav>
<main>
{content}
</main>
<footer>
  Generowane automatycznie rano w dni robocze przez model AI na podstawie
  wskazanych źródeł. To streszczenie, nie oryginalna treść dziennikarska —
  pełne artykuły znajdziesz pod linkami „🔗 Źródło” przy każdym newsie.
  Treść może zawierać błędy — zawsze sprawdzaj źródła. Strona prywatna,
  nieindeksowana przez wyszukiwarki.
</footer>
</body>
</html>
"""

SECTION_IDS = {
    "Ogólne wydarzenia": "ogolne",
    "Polityka": "polityka",
    "Biznes i giełda": "biznes",
    "Sport": "sport",
    "Nauka": "nauka",
}


def markdown_to_html_body(markdown_text: str) -> str:
    """Konwertuje markdown na HTML i wstawia id="" do sekcji H2 dla nawigacji,
    oraz owija każdy news (H3->kolejny H3/H2) w <article class="news">."""
    # Konwersja bazowa
    html_body = md.markdown(markdown_text, extensions=["extra", "sane_lists"])

    # Dodaj kotwice do H2 na podstawie treści nagłówka
    for title, anchor in SECTION_IDS.items():
        html_body = html_body.replace(f"<h2>{title}</h2>", f'<h2 id="{anchor}">{title}</h2>')

    # Owinięcie pojedynczych newsów w <article> — prosta heurystyka:
    # dzielimy po <p><strong> (początek newsa) i domykamy przed kolejnym.
    import re

    parts = re.split(r"(?=<p><strong>)", html_body)
    wrapped = []
    for part in parts:
        if part.strip().startswith("<p><strong>"):
            # Jeśli w środku pojawia się kolejny h2/h3, wytnij go poza article
            m = re.search(r"(<h[23][^>]*>.*)", part, flags=re.S)
            if m:
                inner = part[: m.start()]
                rest = part[m.start():]
                wrapped.append(f'<article class="news">{inner}</article>{rest}')
            else:
                wrapped.append(f'<article class="news">{part}</article>')
        else:
            wrapped.append(part)
    html_body = "".join(wrapped)

    # Stylizacja linków źródłowych: "Źródło: URL" -> ładny link
    html_body = re.sub(
        r"Źródło:\s*(https?://[^\s<]+)",
        r'<a class="source" href="\1" target="_blank" rel="noopener">🔗 Źródło</a>',
        html_body,
    )

    return html_body


def render_html(markdown_text: str) -> str:
    now = datetime.now()
    date_human = polish_date(now)
    time_human = now.strftime("%H:%M")
    body = markdown_to_html_body(markdown_text)
    return HTML_TEMPLATE.format(date_human=date_human, time_human=time_human, content=body)


# --------------------------------------------------------------------------
# Git: publikacja na GitHub Pages
# --------------------------------------------------------------------------

def _redact(cmd: list[str]) -> str:
    """URL pusha zawiera token — nie może trafić do logu ani do konsoli CI."""
    safe = []
    for part in cmd:
        if "@github.com" in part and "//" in part:
            scheme, _, rest = part.partition("//")
            safe.append(f"{scheme}//***@{rest.partition('@')[2]}")
        else:
            safe.append(part)
    return " ".join(safe)


def run(cmd: list[str], cwd: Path, env: dict | None = None):
    log.info(f"$ {_redact(cmd)}")
    result = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        log.error(f"Błąd polecenia: {result.stderr.strip()}")
        raise RuntimeError(f"Polecenie nie powiodło się: {_redact(cmd)}")
    if result.stdout.strip():
        log.info(result.stdout.strip())
    return result


def publish_to_github(html_content: str):
    if not REPO_DIR.exists():
        raise RuntimeError(
            f"Katalog repo {REPO_DIR} nie istnieje. W Actions to oznacza problem "
            "z krokiem actions/checkout; lokalnie sprawdź REPO_DIR w .env."
        )

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    index_path = SITE_DIR / "index.html"
    index_path.write_text(html_content, encoding="utf-8")
    log.info(f"Zapisano {index_path} ({len(html_content)} znaków).")

    # Strona jest streszczeniem cudzych treści, nie ma być indeksowana ani
    # znajdowana przez wyszukiwarki — <meta robots> w index.html to główna
    # bariera, robots.txt to druga, niezależna warstwa tego samego zamiaru.
    robots_path = SITE_DIR / "robots.txt"
    robots_path.write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")

    # W Actions jesteśmy już na właściwej gałęzi (detached/checkout robi to
    # za nas), a `git checkout` mogłoby porzucić stan roboczy.
    if not IN_ACTIONS:
        run(["git", "checkout", GITHUB_BRANCH], cwd=REPO_DIR)
    run(["git", "add", "-A"], cwd=REPO_DIR)

    # Sprawdź czy są zmiany
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO_DIR, capture_output=True, text=True
    )
    if not status.stdout.strip():
        log.info("Brak zmian — pomijam commit/push.")
        return

    commit_msg = f"Raport {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    run(["git", "commit", "-m", commit_msg], cwd=REPO_DIR)

    if IN_ACTIONS:
        # Uwierzytelnienie ustawił actions/checkout — token nigdy nie
        # przechodzi przez ten skrypt ani przez jego logi.
        push_cmd = ["git", "push", "origin", f"HEAD:{GITHUB_BRANCH}"]
    else:
        # Poza Actions budujemy URL z tokenem tylko na czas tego jednego
        # polecenia — nie zapisujemy go w .git/config.
        remote_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_OWNER}/{GITHUB_REPO}.git"
        push_cmd = ["git", "push", remote_url, f"HEAD:{GITHUB_BRANCH}"]

    # Push może zostać odrzucony (non-fast-forward), jeśli ktoś wypchnął coś
    # do gałęzi między checkoutem tego przebiegu a tym momentem — np. ręczny
    # commit użytkownika w trakcie działania harmonogramu. Nasz jedyny lokalny
    # commit to plik index.html, więc rebase na świeży fetch prawie zawsze się
    # powiedzie bez konfliktu; próbujemy dwa razy, zanim się poddamy.
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            run(push_cmd, cwd=REPO_DIR)
            break
        except RuntimeError:
            if attempt == max_attempts:
                raise
            log.warning(
                f"Push odrzucony (próba {attempt}/{max_attempts}) — "
                "ktoś inny wypchnął zmiany w międzyczasie. Robię fetch + rebase i próbuję ponownie."
            )
            run(["git", "fetch", "origin", GITHUB_BRANCH], cwd=REPO_DIR)
            run(["git", "rebase", f"origin/{GITHUB_BRANCH}"], cwd=REPO_DIR)

    log.info("Opublikowano na GitHub Pages.")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    try:
        markdown_text = generate_markdown_report()
    except Exception as e:
        log.exception(f"Generowanie raportu nie powiodło się, strona pozostaje bez zmian: {e}")
        sys.exit(1)

    # Zapisz surowy markdown do logów/archiwum (nie do repo — na potrzeby debugowania)
    archive_dir = SCRIPT_DIR / "archive"
    archive_dir.mkdir(exist_ok=True)
    archive_path = archive_dir / f"{datetime.now().strftime('%Y-%m-%d')}.md"
    archive_path.write_text(markdown_text, encoding="utf-8")

    html_content = render_html(markdown_text)

    try:
        publish_to_github(html_content)
    except Exception as e:
        log.exception(f"Publikacja na GitHub nie powiodła się: {e}")
        sys.exit(1)

    log.info("Gotowe.")


if __name__ == "__main__":
    main()
