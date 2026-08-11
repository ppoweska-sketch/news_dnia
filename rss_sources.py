"""
rss_sources.py
--------------
Rejestr kanałów RSS. Wszystkie źródła są **polskojęzyczne** — także te
z działami zagranicznymi (RMF24 Świat, Euronews po polsku, DW po polsku).
Dzięki temu link „Źródło" pod newsem prowadzi do tekstu, który da się
przeczytać bez tłumaczenia, a model streszcza polski tekst na polski,
zamiast tłumaczyć z angielskiego.

Każdy wpis został sprawdzony na żywo. Kanały, które nie odpowiadają
(PAP, Reuters, Wyborcza, Puls Biznesu, Forsal, Parkiet, Kopalnia Wiedzy,
Onet Świat/Nauka, Interia Świat/Kraj), świadomie pominięto.

Pola:
  region_hint — "Polska", "Świat" albo "mix". To TYLKO podpowiedź. Ostateczny
                podział robi model na podstawie treści newsa: kanał sportowy
                miesza Ekstraklasę z Ligą Mistrzów, a serwis ogólny krajówkę
                z zagranicą.
  topic_hint  — z jakiego działu pochodzi wpis, też tylko jako wskazówka.

Sprawdzenie, czy wszystkie kanały nadal żyją:  python3 check_feeds.py
"""

FEEDS = [
    # ---- Ogólne / polityka: kraj ----
    ("RMF24 Polska",        "https://www.rmf24.pl/fakty/polska/feed",                 "Polska", "ogolne"),
    ("Interia Fakty",       "https://fakty.interia.pl/feed",                          "mix",    "ogolne"),
    ("TVN24",               "https://tvn24.pl/najnowsze.xml",                         "mix",    "ogolne"),
    ("Onet Wiadomości",     "https://wiadomosci.onet.pl/.feed",                       "mix",    "ogolne"),
    ("Polsat News",         "https://www.polsatnews.pl/rss/wszystkie.xml",            "mix",    "ogolne"),

    # ---- Ogólne / polityka: zagranica, po polsku ----
    ("RMF24 Świat",         "https://www.rmf24.pl/fakty/swiat/feed",                  "Świat",  "ogolne"),
    ("Polsat News Świat",   "https://www.polsatnews.pl/rss/swiat.xml",                "Świat",  "ogolne"),
    ("TVN24 Świat",         "https://tvn24.pl/swiat.xml",                             "Świat",  "ogolne"),
    ("Euronews po polsku",  "https://pl.euronews.com/rss",                            "Świat",  "ogolne"),
    ("DW po polsku",        "https://rss.dw.com/rdf/rss-pol-all",                     "Świat",  "ogolne"),

    # ---- Biznes i giełda ----
    ("Bankier",             "https://www.bankier.pl/rss/wiadomosci.xml",              "mix",    "biznes"),
    ("Bankier Giełda",      "https://www.bankier.pl/rss/gielda.xml",                  "mix",    "biznes"),
    ("Interia Biznes",      "https://biznes.interia.pl/feed",                         "mix",    "biznes"),
    ("Money.pl",            "https://www.money.pl/rss/wszystkie",                     "mix",    "biznes"),
    ("Business Insider PL", "https://businessinsider.com.pl/.feed",                   "mix",    "biznes"),

    # ---- Sport (polskie serwisy piszą i o krajowym, i o światowym) ----
    ("Interia Sport",       "https://sport.interia.pl/feed",                          "mix",    "sport"),
    ("TVP Sport",           "https://sport.tvp.pl/rss",                               "mix",    "sport"),
    ("Sportowe Fakty",      "https://sportowefakty.wp.pl/rss.xml",                    "mix",    "sport"),
    ("Przegląd Sportowy",   "https://przegladsportowy.onet.pl/.feed",                 "mix",    "sport"),

    # ---- Nauka i technologia ----
    ("Nauka w Polsce",      "https://naukawpolsce.pl/rss.xml",                        "mix",    "nauka"),
    ("Focus.pl",            "https://www.focus.pl/rss",                               "mix",    "nauka"),
    ("Spider's Web",        "https://spidersweb.pl/feed",                             "mix",    "nauka"),
    ("Antyweb",             "https://antyweb.pl/feed",                                "mix",    "nauka"),
]
