"""
rss_collect.py
--------------
Zbiera kandydatów na newsy z kanałów RSS i (dla wybranych) pobiera pełną
treść artykułu.

Dlaczego dwa etapy: RSS daje tytuł i zajawkę, a raport wymaga opisu na
5-10 zdań. Model najpierw wybiera z ~900 kandydatów te 50, które trafią do
raportu, i dopiero dla nich ściągamy pełny tekst — pobranie 900 stron byłoby
marnotrawstwem, a pisanie z samej zajawki kończy się laniem wody.
"""

import html
import logging
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser
import requests

from rss_sources import FEEDS

log = logging.getLogger("daily-news-report")

FEED_TIMEOUT = 15
ARTICLE_TIMEOUT = 20
# Runner GitHuba ma 16 GB RAM, więc 8 wątków jest bezpieczne. Na współdzielonej
# maszynie bez swapu (np. obok bota tradingowego) zjedź do 3-4 przez RSS_WORKERS
# — lxml trzyma całe drzewo dokumentu, więc szczyt zużycia rośnie z liczbą wątków.
ARTICLE_WORKERS = int(os.environ.get("RSS_WORKERS", "8"))
# Ucinamy artykuł, bo do napisania kilku zdań streszczenia wystarczy początek,
# a pełne teksty 50 artykułów niepotrzebnie rozdmuchałyby prompt.
ARTICLE_MAX_CHARS = 5000
USER_AGENT = "Mozilla/5.0 (compatible; daily-news-report/1.0)"


@dataclass
class Candidate:
    idx: int
    title: str
    summary: str
    url: str
    source: str
    region_hint: str
    topic_hint: str
    published: datetime | None
    full_text: str = field(default="")

    def age_label(self) -> str:
        if self.published is None:
            return "?"
        hours = (datetime.now(timezone.utc) - self.published).total_seconds() / 3600
        return f"{hours:.0f}h"


def _clean(text: str, limit: int) -> str:
    """Zajawki w RSS bywają HTML-em — zdejmujemy tagi i encje."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _normalize_title(title: str) -> str:
    """Klucz do wykrywania duplikatów: bez znaków diakrytycznych,
    interpunkcji i wielkości liter — ta sama depesza PAP przedrukowana
    w trzech serwisach ma zwykle niemal identyczny tytuł."""
    t = unicodedata.normalize("NFKD", title.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:70]


def _entry_time(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        value = getattr(entry, attr, None)
        if value:
            try:
                return datetime.fromtimestamp(mktime(value), tz=timezone.utc)
            except (ValueError, OverflowError, TypeError):
                continue
    return None


def fetch_feed_bytes(url: str) -> bytes:
    """Pobiera kanał przez requests, a nie przez feedparser.

    Dwa powody: feedparser.parse(url) nie przyjmuje timeoutu (jeden zawieszony
    serwer zawiesiłby całe uruchomienie), a jego urllib korzysta na macOS
    z pustego magazynu certyfikatów — requests używa certifi i działa
    tak samo na Macu i na Ubuntu.
    """
    resp = requests.get(
        url,
        timeout=FEED_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"},
    )
    resp.raise_for_status()
    return resp.content


def collect_candidates(max_age_hours: int = 36, per_feed_cap: int = 25) -> list[Candidate]:
    """Pobiera wszystkie kanały równolegle, odsiewa stare wpisy i duplikaty."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    def fetch(feed):
        name, url, region_hint, topic_hint = feed
        try:
            parsed = feedparser.parse(fetch_feed_bytes(url))
            if not parsed.entries:
                log.warning(f"Kanał {name}: brak wpisów (pominięty)")
                return name, []
            return name, [
                (entry, name, region_hint, topic_hint) for entry in parsed.entries
            ]
        except Exception as exc:  # kanał padł — reszta raportu ma się nie wywalić
            log.warning(f"Kanał {name}: błąd pobierania ({exc}) — pominięty")
            return name, []

    raw: list[tuple] = []
    ok_feeds = 0
    with ThreadPoolExecutor(max_workers=ARTICLE_WORKERS) as pool:
        for name, entries in pool.map(fetch, FEEDS):
            if entries:
                ok_feeds += 1
            raw.extend(entries[:per_feed_cap])

    if ok_feeds < len(FEEDS) // 2:
        raise RuntimeError(
            f"Odpowiedziało tylko {ok_feeds} z {len(FEEDS)} kanałów RSS — "
            "prawdopodobnie problem z siecią. Przerywam, żeby nie opublikować "
            "raportu z garstki źródeł."
        )

    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    candidates: list[Candidate] = []
    skipped_old = skipped_dup = 0

    for entry, source, region_hint, topic_hint in raw:
        url = (getattr(entry, "link", "") or "").strip()
        title = _clean(getattr(entry, "title", ""), 200)
        if not url or not title:
            continue

        published = _entry_time(entry)
        if published is not None and published < cutoff:
            skipped_old += 1
            continue

        key = _normalize_title(title)
        if url in seen_urls or key in seen_titles:
            skipped_dup += 1
            continue
        seen_urls.add(url)
        seen_titles.add(key)

        candidates.append(
            Candidate(
                idx=len(candidates),
                title=title,
                summary=_clean(getattr(entry, "summary", ""), 300),
                url=url,
                source=source,
                region_hint=region_hint,
                topic_hint=topic_hint,
                published=published,
            )
        )

    log.info(
        f"RSS: {ok_feeds}/{len(FEEDS)} kanałów, {len(candidates)} kandydatów "
        f"(odrzucono {skipped_old} starszych niż {max_age_hours}h, "
        f"{skipped_dup} duplikatów)"
    )
    if len(candidates) < 60:
        raise RuntimeError(
            f"Za mało kandydatów ({len(candidates)}) na raport z 50 newsów."
        )
    return candidates


def fetch_article_texts(candidates: list[Candidate]) -> None:
    """Uzupełnia `full_text` dla podanych kandydatów (w miejscu).

    Trafilatura jest opcjonalna — bez niej lecimy na samych zajawkach z RSS,
    tylko raport będzie płytszy. Nie przerywamy z tego powodu.
    """
    try:
        import trafilatura
        # Trafilatura trzyma pulę 1 połączenia, a my pobieramy w 8 wątkach —
        # sypie wtedy ostrzeżeniami "Connection pool is full". Nic nie psują
        # (połączenie jest po prostu zamykane), ale zaśmiecają log crona.
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
        logging.getLogger("trafilatura").setLevel(logging.ERROR)
    except ImportError:
        log.warning(
            "Brak trafilatury — piszę z zajawek RSS zamiast z pełnych artykułów. "
            "Zainstaluj: pip install trafilatura"
        )
        return

    def grab(cand: Candidate) -> None:
        try:
            downloaded = trafilatura.fetch_url(cand.url)
            if not downloaded:
                return
            text = trafilatura.extract(
                downloaded, include_comments=False, include_tables=False
            )
            if text:
                cand.full_text = re.sub(r"\s+", " ", text).strip()[:ARTICLE_MAX_CHARS]
        except Exception as exc:
            log.debug(f"Nie pobrano treści z {cand.url}: {exc}")

    with ThreadPoolExecutor(max_workers=ARTICLE_WORKERS) as pool:
        list(pool.map(grab, candidates))

    got = sum(1 for c in candidates if c.full_text)
    log.info(f"Pobrano pełną treść dla {got}/{len(candidates)} artykułów.")


def candidates_digest(candidates: list[Candidate]) -> str:
    """Kompaktowa lista dla modelu na etapie wyboru — jedna linia na news."""
    lines = []
    for c in candidates:
        lines.append(
            f"[{c.idx}] ({c.source}, dział: {c.topic_hint}/{c.region_hint}, "
            f"{c.age_label()}) {c.title} — {c.summary}"
        )
    return "\n".join(lines)
