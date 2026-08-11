#!/usr/bin/env python3
"""
check_feeds.py
--------------
Sprawdza, czy wszystkie kanały z rss_sources.py nadal odpowiadają.
Kanały RSS potrafią umrzeć po cichu — serwis zmienia adres, a Ty przez
tydzień nie masz sportu w raporcie i nie wiesz dlaczego.

    python3 check_feeds.py

Kod wyjścia 1, gdy którykolwiek kanał nie działa — nadaje się do crona
z powiadomieniem.
"""

import sys
from concurrent.futures import ThreadPoolExecutor

import feedparser

from rss_collect import fetch_feed_bytes
from rss_sources import FEEDS


def check(feed):
    name, url, region_hint, topic_hint = feed
    try:
        parsed = feedparser.parse(fetch_feed_bytes(url))
        return name, region_hint, topic_hint, len(parsed.entries), None
    except Exception as exc:
        return name, region_hint, topic_hint, 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, FEEDS))

    broken = []
    for name, region_hint, topic_hint, count, err in results:
        if count > 0:
            print(f"  OK    {name:<22} {region_hint:<7} {topic_hint:<7} {count:>3} wpisów")
        else:
            broken.append(name)
            print(f"  PADŁ  {name:<22} {region_hint:<7} {topic_hint:<7}   0  {err or 'brak wpisów'}")

    total = sum(c for _, _, _, c, _ in results)
    print(f"\n{len(FEEDS) - len(broken)}/{len(FEEDS)} kanałów działa, {total} wpisów łącznie.")

    if broken:
        print(f"\nDo naprawy w rss_sources.py: {', '.join(broken)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
