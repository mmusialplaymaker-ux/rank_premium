"""
config.py
─────────
Centralna konfiguracja narzędzia do generowania rankingów.

Tutaj ustawiasz WSZYSTKO, co zmieniasz na co dzień:
  • połączenie z bazą (przez .env — patrz niżej)
  • który sezon
  • którą ligę / play chcesz wyrankować
  • ile pozycji w rankingu (TOP N)
  • ilu max zawodników z jednego klubu
  • próg kwalifikacji (min. liczba meczów)
  • bramkarze: polowi / bramkarze / oba
  • okresy do rankingu progresu

UWAGA dot. połączenia:
  Hasło NIE jest w tym pliku. Trzymaj je w pliku .env obok (patrz .env.example),
  albo wpisz tymczasowo w sekcji DB poniżej. Połączenie idzie przez SSH —
  jeśli tunelujesz port lokalnie, ustaw DB_HOST=localhost i odpowiedni DB_PORT.
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ══════════════════════════════════════════════════════════════════════════════
# POŁĄCZENIE Z BAZĄ
# ══════════════════════════════════════════════════════════════════════════════
# Najlepiej trzymać w .env (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD).
# Jeśli łączysz się przez tunel SSH, zwykle host = localhost, a port = ten,
# na który przekierowałeś (np. 5433, jak w build_pro_paths.py).

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = os.getenv("DB_PORT", "5433")
DB_NAME     = os.getenv("DB_NAME", "")
DB_USER     = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")


# ══════════════════════════════════════════════════════════════════════════════
# SEZON
# ══════════════════════════════════════════════════════════════════════════════
# UUID sezonu z tabeli (ten sam, którego używasz w rankingi_top10.sql).

SEASON_ID = "e9d66181-d03e-4bb3-b889-4da848f4831d"  # 25/26


# ══════════════════════════════════════════════════════════════════════════════
# CO RANKUJEMY — poziom grupowania
# ══════════════════════════════════════════════════════════════════════════════
# RANK_BY decyduje, czy ranking jest po KATEGORII (league.name, np. "3 liga")
# czy po KONKRETNEJ GRUPIE (play.name, np. "3 liga grupa 1").
#
#   "league" → grupuje i rankuje w obrębie league.name
#   "play"   → grupuje i rankuje w obrębie play.name
#
# To odpowiada różnicy między Twoimi dwoma oryginalnymi skryptami:
# rankingi_top10.sql (po lidze) vs rankingi_all.sql (po play).

RANK_BY = "league"   # "league" albo "play"

# Które ligi/grupy brać. Filtrowanie zawsze odbywa się po league_id na poziomie
# SQL (bo pm_player_match_score ma league_id, nie play_id bezpośrednio w filtrze
# WHERE — choć play_id też tam jest i go używamy do grupowania).
#
# Wypełnij sekcję odpowiednią do tego, jak chcesz wskazać zakres:
#
#   • Najczęściej: podajesz konkretne LEAGUE_IDS (UUID z leagues._id).
#   • Gdy RANK_BY="play": dodatkowo możesz zawęzić do konkretnych PLAY_IDS
#     (UUID z plays._id) — wtedy ranking obejmie tylko te grupy.
#   • Opcjonalnie: REGION_IDS (UUID z regions._id / województwo) — jeśli chcesz
#     wziąć wszystkie ligi danego regionu bez wypisywania ich UUID. Wymaga, by
#     tabela leagues miała kolumnę region_id (patrz uwaga niżej).
#
# Pusta lista [] = brak filtra po tym wymiarze.
LEAGUE_IDS = [
    "c164ca31-22e4-43fc-9e30-4f3bcc2b7d72",  # IV liga
    "a0583713-115c-4aa5-90f2-140f6eaece15",  # V liga
    "c5afdf4b-b449-4ef3-acf5-dded47fc5f58",  # okręgówka
]

# Opcjonalne zawężenie do konkretnych grup (play). Działa razem z RANK_BY="play".
# Jeśli puste [] — bierzemy wszystkie play w wybranych ligach.
PLAY_IDS = []

# Opcjonalne: zamiast wypisywać LEAGUE_IDS, możesz podać REGION_IDS, a narzędzie
# samo pobierze ligi tego regionu (SELECT _id FROM leagues WHERE region_id IN (...)).
# UWAGA: zadziała tylko jeśli w tabeli leagues istnieje kolumna region_id.
# Jeśli REGION_IDS jest niepuste, ma PIERWSZEŃSTWO nad LEAGUE_IDS.
REGION_IDS = ["fd118a32-2558-437c-a1d6-76a1f862e13d"]


# ══════════════════════════════════════════════════════════════════════════════
# PARAMETRY RANKINGU
# ══════════════════════════════════════════════════════════════════════════════

# Ile pozycji w finalnym rankingu (TOP N). Np. 10 albo 30.
TOP_N = 50

# Ilu maksymalnie zawodników z jednego klubu może wejść do rankingu.
# None = bez limitu (ranking ogólny).
# 2    = max 2 z klubu (jak w Twoim rankingi_top10.sql).
MAX_PER_CLUB = 5

# Po czym liczymy "klub" przy limicie MAX_PER_CLUB:
#   "club" → po clubs._id (prawdziwy klub; teams.club_id → clubs._id)  [DOMYŚLNE]
#   "team" → po teams._id (drużyna; tak działał Twój oryginalny skrypt)
#
# UWAGA: w rankingi_top10.sql limit był faktycznie po nazwie drużyny (team),
# nie po klubie. Tutaj domyślnie poprawiamy to na "club" — jeśli chcesz
# zachować stare zachowanie, zmień na "team".
CLUB_LEVEL = "club"   # "club" albo "team"

# Próg kwalifikacji: minimalna liczba meczów (z policzonym score).
# Zależnie od kontekstu:
#   • ranking miesięczny / po kolejce → niski próg (np. 2-3)
#   • ranking za rundę               → np. 5
#   • ranking za cały sezon          → np. 10
MIN_MECZE = 5

# Kogo rankujemy:
#   "outfield" → tylko zawodnicy z pola (is_keeper = false)
#   "keeper"   → tylko bramkarze (is_keeper = true)
#   "both"     → generuje OBA osobne rankingi (dwa zestawy arkuszy)
PLAYER_GROUP = "both"   # "outfield" / "keeper" / "both"


# ══════════════════════════════════════════════════════════════════════════════
# PROGRES — porównanie dwóch okresów
# ══════════════════════════════════════════════════════════════════════════════
# Ranking progresu liczy średni score w dwóch okresach (A i B) i ich różnicę.
# Daty w formacie 'YYYY-MM-DD'. Okres A to zwykle WCZEŚNIEJSZY (np. jesień),
# okres B to PÓŹNIEJSZY (np. wiosna). Progres = avg_B - avg_A.
#
# Przykłady:
#   • listopad vs marzec:  A=(2025-11-01, 2025-11-30), B=(2026-03-01, 2026-03-31)
#   • runda jesienna vs wiosenna: A=(2025-08-01, 2025-12-31), B=(2026-02-01, 2026-06-30)
#
# Ustaw GENERATE_PROGRES=False jeśli nie chcesz arkusza progresu.

GENERATE_PROGRES = True

PROGRES_OKRES_A = ("2025-08-01", "2025-12-31")   # wcześniejszy
PROGRES_OKRES_B = ("2026-02-01", "2026-06-30")   # późniejszy

# Minimalna liczba meczów W KAŻDYM z okresów, żeby progres był wiarygodny.
PROGRES_MIN_MECZE = 3


# ══════════════════════════════════════════════════════════════════════════════
# WYGLĄD EXCELA  (spójne z build_reports.py)
# ══════════════════════════════════════════════════════════════════════════════

XLSX_FONT_NAME   = "Arial"
COLOR_HEADER_BG  = "2F5597"   # granat nagłówka
COLOR_HEADER_TXT = "FFFFFF"
COLOR_TOP3_BG    = "FFF2CC"   # delikatne podświetlenie TOP 3

OUTPUT_DIR = "data"           # tu lądują pliki .xlsx


# ══════════════════════════════════════════════════════════════════════════════
# POMOCNICZE
# ══════════════════════════════════════════════════════════════════════════════

def sql_in_clause(values):
    """Zamienia listę UUID-ów na bezpieczny fragment IN ('a','b',...)."""
    if not values:
        return "NULL"
    cleaned = [str(v).replace("'", "''") for v in values]
    return ", ".join(f"'{v}'" for v in cleaned)
