#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
slim_data.py - robi z DUZYCH plikow (stats_test.csv + matches_test.csv) male,
gotowe do apki: TOP N zawodnikow po PM Index (z KAZDEGO wojewodztwa) + ich mecze.

Jak dziala (bez kombinowania):
  - Twoj SWIEZY eksport z SQL rozpoznawany jest po kolumnach, ktorych slim nie ma
    (processed_ids / m_overall_score). Taki plik zostaje przemianowany na
    full_stats.csv / full_matches.csv (master, duzy) - NADPISUJAC stary master.
    Dzieki temu nowy eksport zawsze wygrywa (koniec "starego mastera").
  - Skrypt liczy PM Index na pelnych danych, wybiera TOP N z KAZDEGO wojewodztwa
    (domyslnie 250 -> dla 4 woj. ok. 1000) i zapisuje MALE stats_test.csv /
    matches_test.csv - te ladujesz do apki.

Opcje:
  --top 250            ile z kazdego wojewodztwa (domyslnie 250)
  --globalny           zamiast per-wojewodztwo: globalny top N
  --bez-dziewczynek    wyklucz zawodniczki (po imieniu; jak w raporcie dziewczynek)

Uzycie:
  python slim_data.py --bez-dziewczynek
  python slim_data.py --top 300 --bez-dziewczynek
"""
import argparse
import gzip
import os
import shutil
import sys
import types

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
import app           # noqa: E402

GZIP_ABOVE_MB = 90
ENCODINGS = ("utf-8", "cp1250", "latin-1")

# kolumny obecne w SUROWYM eksporcie z SQL, ktore slim usuwa -> sygnal "swiezy eksport"
SENTINELS_STATS = {"processed_ids", "created_at", "overall_score"}
SENTINELS_MATCHES = {"m_overall_score", "m_season_score"}

DROP_COLS = {
    "processed_ids", "created_at", "updated_at",
    "m_overall_score", "m_season_score",
    "global_last_overall_score", "global_last_season_score", "global_last_match_date",
    "overall_score", "season_score", "last_match_in_play",
}

# --- wykluczanie dziewczynek (ta sama logika, co w raporcie "dziewczynki") ---
# imie zenskie = konczy sie na "-a" (minus meskie wyjatki) LUB jest na jawnej liscie.
MALE_A_EXCEPTIONS = {
    "kuba", "jakuba", "barnaba", "bonawentura", "kosma", "jarema",
    "sasha", "sasza", "misha", "ilya", "illia", "illya", "ilia", "ilariia", "ilarii",
    "mykyta", "mikita", "kuzma", "kuźma", "danila", "danyla", "oleksa", "seva", "diaa",
    "joshua", "joschka", "luka", "nikita",
    "wojtyła", "wojtyla", "pluta", "kudzia", "kumela", "baca", "maksymalna",
}
FEMALE_EXTRA = {
    "noemi", "noémi", "noemie", "abigail", "ingrid", "rachel", "dolores",
    "carmen", "ester", "esther", "miriam", "sarai", "ruth", "liv", "fay",
}

def _is_female(firstname):
    n = str(firstname or "").strip().lower()
    if not n:
        return False
    if n in FEMALE_EXTRA:
        return True
    if n in MALE_A_EXCEPTIONS:
        return False
    return n.endswith("a")


def rd_raw(path):
    for enc in ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc, sep=None, engine="python",
                               dtype=str, keep_default_na=False)
        except Exception:
            continue
    raise RuntimeError(f"Nie udalo sie wczytac {path}")


def _peek_header(path):
    for enc in ENCODINGS:
        try:
            with open(path, encoding=enc) as f:
                line = f.readline()
            sep = ";" if line.count(";") > line.count(",") else ","
            return {c.strip().strip('"') for c in line.rstrip("\r\n").split(sep)}
        except Exception:
            continue
    return set()


def _ensure_master(test_path, full_path, kind, sentinels):
    """full_*.csv = master. Swiezy pelny eksport z SQL (ma kolumny-sentinele) NADPISUJE master."""
    if os.path.exists(test_path) and (sentinels & _peek_header(test_path)):
        if os.path.exists(full_path):
            os.remove(full_path)
        os.replace(test_path, full_path)
        print(f"  {kind}: swiezy eksport {os.path.basename(test_path)} -> master {os.path.basename(full_path)} (odswiezono)")
        return full_path
    if os.path.exists(full_path):
        print(f"  {kind}: uzywam master {os.path.basename(full_path)}")
        return full_path
    if os.path.exists(test_path):
        print(f"  {kind}: uzywam {os.path.basename(test_path)} (brak mastera)")
        return test_path
    return None


def _write(df, path):
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
    ap.add_argument("--globalny", action="store_true", help="zamiast per-wojewodztwo: globalny top N")
    ap.add_argument("--bez-dziewczynek", dest="bez_dziewczynek", action="store_true",
                    help="wyklucz zawodniczki (po imieniu)")
    ap.add_argument("--teamy", default="teamy_kluby_25_26.csv")
    ap.add_argument("--stats", default="full_stats.csv")
    ap.add_argument("--matches", default="full_matches.csv")
    ap.add_argument("--test-stats", default="stats_test.csv")
    ap.add_argument("--test-matches", default="matches_test.csv")
    a = ap.parse_args()

    print("Przygotowuje master (full_*.csv)…")
    src_s = _ensure_master(a.test_stats, a.stats, "stats", SENTINELS_STATS)
    src_m = _ensure_master(a.test_matches, a.matches, "matches", SENTINELS_MATCHES)
    if not src_s or not src_m:
        print("BLAD: brak danych zrodlowych. Wrzuc stats_test.csv i matches_test.csv (eksport z SQL) i uruchom ponownie.")
        sys.exit(1)

    print(f"Wczytuje pelne dane: {src_s} + {src_m}")
    stats, matches = app.load_data(src_s, src_m, a.teamy)
    print(f"  stats {stats.shape}, matches {matches.shape}")

    # imiona zenskie -> zbior player_id do wykluczenia (z mastera stats)
    fem_ids = set()
    if a.bez_dziewczynek:
        sr0 = rd_raw(src_s)
        if "firstname" in sr0.columns:
            fem_ids = set(sr0.loc[sr0["firstname"].map(_is_female), "player_id"].astype(str))
        print(f"  bez dziewczynek: wykryto {len(fem_ids)} zawodniczek po imieniu")

    print("Licze PM Index na pelnym zbiorze…")
    d = app.build(stats, matches).sort_values("PM_Index", ascending=False).reset_index(drop=True)
    if fem_ids:
        before = len(d)
        d = d[~d["player_id"].astype(str).isin(fem_ids)]
        print(f"  usunieto dziewczynki z rankingu: {before - len(d)} (zostaje {len(d)})")

    has_reg = "region_name" in d.columns and d["region_name"].astype(str).str.strip().replace("nan", "").ne("").any()
    if a.globalny or not has_reg:
        sel = d.head(int(a.top))
        print(f"  graczy ogolem: {len(d)} | wybieram top {len(sel)} (globalnie)")
    else:
        sel = d.groupby("region_name", sort=True, group_keys=False).head(int(a.top))
        print(f"  graczy ogolem: {len(d)} | top {a.top} z KAZDEGO wojewodztwa -> lacznie {len(sel)}")
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