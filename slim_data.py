#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
slim_data.py - robi z DUZYCH plikow (stats_test.csv + matches_test.csv) male,
gotowe do apki: TOP N zawodnikow po PM Index + ich mecze.

Jak dziala (bez kombinowania):
  - Twoje duze pliki stats_test.csv / matches_test.csv zostaja RAZ przemianowane
    na full_stats.csv / full_matches.csv  (to jest odtad Twoj master - duzy).
  - Skrypt liczy PM Index na pelnych danych, wybiera TOP N z KAZDEGO wojewodztwa
    (domyslnie 250 -> dla 4 woj. ok. 1000) i zapisuje MALE stats_test.csv /
    matches_test.csv - te ladujesz do apki. Dzieki temu WSZYSTKIE wojewodztwa sa
    w wyniku (globalny top N potrafi wywalic slabsze regiony).

Odswiezenie po nowym eksporcie z SQL:
  - nadpisz full_stats.csv / full_matches.csv nowym eksportem i uruchom ponownie,
    albo usun full_*.csv, wrzuc nowy eksport jako *_test.csv i uruchom.

Uzycie:
  python slim_data.py              # top 250 z kazdego wojewodztwa
  python slim_data.py --top 400    # inna liczba na wojewodztwo
  python slim_data.py --globalny --top 1000   # stary tryb: globalny top N
"""
import argparse
import gzip
import os
import shutil
import sys
import types

# --- stub streamlit, zeby policzyc app.build poza Streamlitem ---
_st = types.ModuleType("streamlit")
def _cache_data(*a, **k):
    if a and callable(a[0]):
        return a[0]
    def deco(f):
        return f
    return deco
_st.cache_data = _cache_data
_st.secrets = {}
sys.modules.setdefault("streamlit", _st)

import pandas as pd  # noqa: E402
import app           # noqa: E402  (app.py musi byc w tym samym folderze)

GZIP_ABOVE_MB = 90            # gdyby wyjscie bylo > limitu GitHub, spakuj do .csv.gz
ENCODINGS = ("utf-8", "cp1250", "latin-1")

# balast: ciezkie, nieuzywane przez aplikacje kolumny. Reszte ZOSTAWIAMY nietknieta
# (m.in. est_birth_year, age_at_match, league_name, minutes, gra_ze_starszymi,
#  senior_minutes, in_selected_play - potrzebne do PM Index i znacznikow/CLJ).
DROP_COLS = {
    "processed_ids", "created_at", "updated_at",
    "m_overall_score", "m_season_score",
    "global_last_overall_score", "global_last_season_score", "global_last_match_date",
    "overall_score", "season_score", "last_match_in_play",
}


def rd_raw(path):
    """Surowe wczytanie 1:1 (tekst), wiele kodowan - bez psucia wartosci."""
    for enc in ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc, sep=None, engine="python",
                               dtype=str, keep_default_na=False)
        except Exception:
            continue
    raise RuntimeError(f"Nie udalo sie wczytac {path}")


def _ensure_master(test_path, full_path, kind):
    """full_*.csv = master (duzy). Jesli go nie ma, przemianuj *_test.csv -> full_*."""
    if not os.path.exists(full_path):
        if os.path.exists(test_path):
            os.replace(test_path, full_path)
            print(f"  {kind}: {os.path.basename(test_path)} -> {os.path.basename(full_path)} (master)")
        else:
            return None
    else:
        print(f"  {kind}: uzywam master {os.path.basename(full_path)}")
    return full_path


def _write(df, path):
    """Zapisz CSV; jesli > limitu, spakuj do .csv.gz (aplikacja czyta .gz sama)."""
    df.to_csv(path, index=False, encoding="utf-8")
    mb = os.path.getsize(path) / 1e6
    if mb > GZIP_ABOVE_MB:
        gz = path + ".gz"
        with open(path, "rb") as fi, gzip.open(gz, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        os.remove(path)
        print(f"  {os.path.basename(gz)}: {os.path.getsize(gz)/1e6:.1f} MB (spakowany) - do apki/repo TEN plik")
        return
    print(f"  {os.path.basename(path)}: {mb:.1f} MB | {len(df)} wierszy")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=250,
                    help="ilu najlepszych z KAZDEGO wojewodztwa (domyslnie 250; dla 4 woj. ~1000)")
    ap.add_argument("--globalny", action="store_true",
                    help="zamiast per-wojewodztwo: zwykly globalny top N")
    ap.add_argument("--teamy", default="teamy_kluby_25_26.csv")
    ap.add_argument("--stats", default="full_stats.csv", help="master stats (duzy)")
    ap.add_argument("--matches", default="full_matches.csv", help="master matches (duzy)")
    ap.add_argument("--test-stats", default="stats_test.csv", help="wyjscie stats (do apki)")
    ap.add_argument("--test-matches", default="matches_test.csv", help="wyjscie matches (do apki)")
    a = ap.parse_args()

    print("Przygotowuje master (full_*.csv)…")
    src_s = _ensure_master(a.test_stats, a.stats, "stats")
    src_m = _ensure_master(a.test_matches, a.matches, "matches")
    if not src_s or not src_m:
        print("BLAD: brak danych zrodlowych. Wrzuc do folderu stats_test.csv i matches_test.csv "
              "(albo full_stats.csv / full_matches.csv) i uruchom ponownie.")
        sys.exit(1)

    print(f"Wczytuje pelne dane: {src_s} + {src_m}")
    stats, matches = app.load_data(src_s, src_m, a.teamy)
    print(f"  stats {stats.shape}, matches {matches.shape}")

    print("Licze PM Index na pelnym zbiorze…")
    d = app.build(stats, matches).sort_values("PM_Index", ascending=False).reset_index(drop=True)
    has_reg = "region_name" in d.columns and d["region_name"].astype(str).str.strip().replace("nan", "").ne("").any()
    if a.globalny or not has_reg:
        sel = d.head(int(a.top))
        print(f"  graczy ogolem: {len(d)} | wybieram top {len(sel)} (globalnie)")
    else:
        # TOP N z KAZDEGO wojewodztwa - gwarantuje, ze wszystkie regiony sa w wyniku
        sel = d.groupby("region_name", sort=True, group_keys=False).head(int(a.top))
        print(f"  graczy ogolem: {len(d)} | wybieram top {a.top} z KAZDEGO wojewodztwa -> lacznie {len(sel)}")
    if "region_name" in sel.columns:
        print(f"  rozklad wybranych: {sel['region_name'].astype(str).value_counts().to_dict()}")
    top_ids = set(sel["player_id"].astype(str))

    print("Przycinam mecze do wybranych zawodnikow i zapisuje…")
    sr, mr = rd_raw(src_s), rd_raw(src_m)
    sr["player_id"] = sr["player_id"].astype(str)
    mr["player_id"] = mr["player_id"].astype(str)
    ss = sr[sr["player_id"].isin(top_ids)].drop(columns=[c for c in DROP_COLS if c in sr.columns])
    ms = mr[mr["player_id"].isin(top_ids)].drop(columns=[c for c in DROP_COLS if c in mr.columns])
    _write(ss, a.test_stats)
    _write(ms, a.test_matches)

    print("Gotowe. Do apki zaladuj:", os.path.basename(a.test_stats), "+", os.path.basename(a.test_matches))


if __name__ == "__main__":
    main()