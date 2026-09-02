# -*- coding: utf-8 -*-
"""
ranking_lnp.py — PM progress rank: premium + top-szczeble (Ekstraklasa/1L/2L/CLJ) jako benchmark.

WEJŚCIE (obok skryptu): premium_pilkarze_lnp.csv, logo.png, *teamy_kluby*.csv
WYJŚCIE: data/ranking/ranking.html (interaktywny), ranking_latest.csv

URUCHOMIENIE (tunel SSH do LNP):
    python ranking_lnp.py                      # premium + top 500 referencyjnych
    python ranking_lnp.py --ref-top 0          # tylko premium
    python ranking_lnp.py --ref-top 800 --ref-od 2025-07-01
    python ranking_lnp.py --data-do 2026-09-02 --dni 7
"""
import argparse, bisect, csv, json, os, sys
from datetime import date, timedelta

try:
    import psycopg2
except ImportError:
    sys.exit("Brak psycopg2. Zainstaluj:  pip install psycopg2-binary")

HERE = os.path.dirname(os.path.abspath(__file__))
TOP_MULT = 100.0  # score*100 do wyświetlania
KOBIECE = ("kobiet", "kobieca", "kobiety", "juniorek", "juniorka", "juniorki", "dziewcz", "u-18 k", "u18 k")


def _is_women(name):
    n = (name or "").lower()
    return any(w in n for w in KOBIECE)


def _to_date(v):
    from datetime import datetime, date as _d
    if v is None: return None
    if isinstance(v, datetime): return v.date()
    if isinstance(v, _d): return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
        try: return datetime.strptime(s[:19] if len(s) >= 19 else s, fmt).date()
        except ValueError: continue
    try: return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError: return None


def s100(v):
    try: return round(float(v) * TOP_MULT, 1)
    except Exception: return None


# ───────── wejście premium ─────────
def wczytaj_premium(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        cols = {c.lower(): c for c in (rd.fieldnames or [])}
        c_lnp = cols.get("player_lnp") or cols.get("mapper_new")
        c_name, c_uid, c_url = cols.get("player_name"), cols.get("user_id"), cols.get("profile_url")
        if not c_lnp: sys.exit(f"CSV bez player_lnp. Nagłówki: {rd.fieldnames}")
        out, seen = [], set()
        for r in rd:
            u = (r.get(c_lnp) or "").strip()
            if not u or u in seen: continue
            seen.add(u)
            out.append({"player_lnp": u,
                        "player_name": (r.get(c_name) or "").strip() if c_name else "",
                        "user_id": (r.get(c_uid) or "").strip() if c_uid else "",
                        "profile_url": (r.get(c_url) or "").strip() if c_url else ""})
    return out


# ───────── LNP ─────────
_CONF = None
def _read_conf():
    global _CONF
    if _CONF is not None:
        return _CONF
    _CONF = {}
    cands = []
    for d in (HERE, os.getcwd()):
        cands += [os.path.join(d, "secrets.toml"), os.path.join(d, "lnp.toml"),
                  os.path.join(d, "lnp_config.txt"), os.path.join(d, ".streamlit", "secrets.toml")]
    for p in cands:
        if os.path.exists(p):
            try:
                for line in open(p, encoding="utf-8-sig"):
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("[") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    _CONF.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            except Exception:
                pass
    return _CONF


def _param(key, prompt, default=None, secret=False):
    v = os.environ.get(key)
    if v:
        return str(v)
    conf = _read_conf()
    if key in conf and conf[key]:
        return str(conf[key])
    import getpass
    return getpass.getpass(f"{prompt}: ") if secret else (input(f"{prompt}{f' [{default}]' if default else ''}: ").strip() or (default or ""))


def connect_lnp():
    kw = dict(host=_param("PGHOST", "LNP Host", "localhost"), port=_param("PGPORT", "LNP Port", "5433"),
              dbname=_param("PGDATABASE", "LNP Baza"), user=_param("PGUSER", "LNP Użytkownik"),
              password=_param("PGPASSWORD", "LNP Hasło", secret=True))
    print(f"\n[LNP] łączę {kw['user']}@{kw['host']}:{kw['port']}/{kw['dbname']} ...")
    try:
        c = psycopg2.connect(client_encoding="UTF8", **kw); print("  OK"); return c
    except Exception as e:
        sys.exit(f"[LNP] błąd połączenia: {e}\nSprawdź tunel SSH i dane.")


def _kolumny(lnp, tab):
    cur = lnp.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (tab,))
    s = {r[0] for r in cur.fetchall()}; cur.close(); return s


def _notin(col, ids):
    if not ids:
        return ""
    inv = ",".join("'" + str(x).replace("'", "") + "'" for x in ids)
    return f" AND {col} NOT IN ({inv})"


def load_maps(path=None):
    import glob
    if not path:
        cands = glob.glob(os.path.join(HERE, "*teamy_kluby*.csv")) + glob.glob(os.path.join(HERE, "*teams*.csv"))
        path = cands[0] if cands else None
    tm, cm = {}, {}
    if not path or not os.path.exists(path): return tm, cm
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f); cols = {c.lower(): c for c in (rd.fieldnames or [])}
        c_tid, c_cid = cols.get("team_id"), cols.get("club_id")
        c_tn = cols.get("final_team_name") or cols.get("final_name")
        c_cn = cols.get("final_club_name") or cols.get("club_name")
        for r in rd:
            tid = (r.get(c_tid) or "").strip() if c_tid else ""
            cid = (r.get(c_cid) or "").strip() if c_cid else ""
            tn = (r.get(c_tn) or "").strip() if c_tn else ""
            cn = (r.get(c_cn) or "").strip() if c_cn else ""
            if tid and tn: tm[tid] = tn
            if cid and cn and cid not in cm: cm[cid] = cn
    return tm, cm


def load_slownik(path=None):
    """Zbiór play_id do ODRZUCENIA: kobiece + wykluczone (baraże/7x7). Ze slownik_rozgrywek.csv."""
    import glob
    if not path:
        c = glob.glob(os.path.join(HERE, "*slownik_rozgrywek*.csv")) + glob.glob(os.path.join(HERE, "*rozgryw*.csv"))
        path = c[0] if c else None
    bad = set()
    if not path or not os.path.exists(path):
        return bad
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f); cols = {c.lower(): c for c in (rd.fieldnames or [])}
        c_pid = cols.get("play_id"); c_pn = cols.get("play_name"); c_kn = cols.get("kanon_nazwa")
        c_wy = cols.get("wykluczone"); c_kat = cols.get("kategoria")
        for r in rd:
            pid = (r.get(c_pid) or "").strip() if c_pid else ""
            if not pid:
                continue
            nm = ((r.get(c_pn) or "") + " " + (r.get(c_kn) or "") + " " + (r.get(c_kat) or ""))
            wy = (r.get(c_wy) or "").strip().lower() if c_wy else ""
            if _is_women(nm) or wy in ("true", "1", "tak"):
                bad.add(pid)
    return bad


def pobierz_ligi(lnp):
    """(all {id:name}, top {id:name}, cup {ids}) — cup = Puchar Polski / nie-ligowe."""
    cols = _kolumny(lnp, "leagues")
    catsel = "category" if "category" in cols else "NULL"
    cur = lnp.cursor(); cur.execute(f"SELECT _id, name, {catsel} FROM leagues"); rows = cur.fetchall(); cur.close()
    allm = {r[0]: (r[1] or "") for r in rows}
    cup = set()
    for _id, name, cat in rows:
        n = (name or "").lower(); c = (cat or "").lower()
        if "puchar" in n or c in ("cup", "cups", "puchar", "puchary"):
            cup.add(_id)
    def is_top(nm):
        n = (nm or "").lower()
        if _is_women(nm) or "futsal" in n or "puchar" in n: return False
        if "ekstraklasa" in n: return True
        if n.strip() in ("pierwsza liga", "druga liga", "i liga", "ii liga"): return True
        if n.startswith("clj") or "centralna liga junior" in n: return True
        return False
    top = {i: nm for i, nm in allm.items() if is_top(nm) and i not in cup}
    return allm, top, cup


def _score_rows(lnp, where, params_ids=None, ids=None, exclude=None):
    """Zwraca {pid:{curr,prev}} z pm_player_match_score wg WHERE (2 ostatnie mecze, bez pucharów)."""
    cols = _kolumny(lnp, "pm_player_match_score")
    pid = "player_id"; oc = "match_date" if "match_date" in cols else "created_at"
    ov = "overall_score" if "overall_score" in cols else "NULL"
    se = "season_score" if "season_score" in cols else "NULL"
    ag = "age" if "age" in cols else "NULL"
    lg = "league_id" if "league_id" in cols else "NULL"
    pl = "play_id" if "play_id" in cols else "NULL"
    exc = _notin("league_id", exclude) if "league_id" in cols else ""
    res = {}
    cur = lnp.cursor()
    def run(extra):
        cur.execute(f"""
          SELECT pid,overall,season,age,lid,plid,mdate,rn FROM (
            SELECT {pid}::text pid,{ov} overall,{se} season,{ag} age,{lg} lid,{pl} plid,{oc} mdate,
                   ROW_NUMBER() OVER (PARTITION BY {pid} ORDER BY {oc} DESC NULLS LAST) rn
            FROM pm_player_match_score WHERE {extra}{exc}
          ) t WHERE rn<=2""")
        for p, overall, season, age, lid, plid, mdate, rn in cur.fetchall():
            d = res.setdefault(p, {"curr": None, "prev": None})
            d["curr" if rn == 1 else "prev"] = {"overall": overall, "season": season, "age": age,
                                                "league_id": lid, "play_id": plid, "mdate": _to_date(mdate)}
    if ids is not None:
        B = 800; idl = sorted({x for x in ids if x})
        for i in range(0, len(idl), B):
            inids = ",".join("'" + s.replace("'", "") + "'" for s in idl[i:i + B])
            run(f"{pid}::text IN ({inids})")
    else:
        run(where)
    cur.close()
    return res


def pobierz_top(lnp, top_ids, cutoff, limit):
    """Referencyjni: 2 ostatnie mecze w top-ligach od cutoff; przytnij do `limit` po curr overall."""
    if not top_ids or limit <= 0:
        return {}
    in_l = ",".join("'" + x + "'" for x in top_ids)
    where = f"league_id IN ({in_l}) AND match_date >= '{cutoff}'"
    res = _score_rows(lnp, where)
    # przytnij do top `limit` po curr.overall
    scored = [(p, d) for p, d in res.items() if d["curr"] and d["curr"].get("overall") is not None]
    scored.sort(key=lambda kv: kv[1]["curr"]["overall"], reverse=True)
    return dict(scored[:limit])


def pobierz_nazwiska(lnp, ids):
    cols = _kolumny(lnp, "players")
    if not cols:
        print("  ⚠ brak tabeli players"); return {}
    idc = "_id" if "_id" in cols else ("id" if "id" in cols else None)
    namesql = None
    for a, b in [("first_name", "last_name"), ("firstname", "lastname"), ("imie", "nazwisko"),
                 ("given_name", "family_name"), ("name_first", "name_last"), ("first", "last"),
                 ("firstName", "lastName")]:
        if a in cols and b in cols:
            namesql = f"TRIM(COALESCE({a},'')||' '||COALESCE({b},''))"; break
    if not namesql:
        for s in ["name", "full_name", "player_name", "display_name", "fullname", "nazwa", "imie_nazwisko", "fullName"]:
            if s in cols:
                namesql = s; break
    if not idc or not namesql:
        print(f"  ⚠ players: nie rozpoznałem kolumn nazwiska. KOLUMNY = {sorted(cols)}")
        return {}
    out = {}; cur = lnp.cursor(); B = 800; idl = sorted({x for x in ids if x})
    for i in range(0, len(idl), B):
        inids = ",".join("'" + s.replace("'", "") + "'" for s in idl[i:i + B])
        cur.execute(f"SELECT {idc}::text, {namesql} FROM players WHERE {idc}::text IN ({inids})")
        for pid, nm in cur.fetchall():
            if nm and str(nm).strip():
                out[pid] = str(nm).strip()
    cur.close()
    print(f"  nazwiska: rozwiązano {len(out)} (kolumna: {namesql})")
    return out


def pobierz_team(lnp, ids, exclude=None):
    cols = _kolumny(lnp, "pm_player_match_stats")
    if not cols: return {}
    dc = next((c for c in ("match_date", "date", "created_at") if c in cols), None)
    oc = dc or ("id" if "id" in cols else None)
    ht, hc = "team_id" in cols, "club_id" in cols
    if not oc or not (ht or hc): return {}
    tsel = "m.team_id::text" if ht else "NULL"; csel = "m.club_id::text" if hc else "NULL"
    cj = "LEFT JOIN clubs c ON c._id = m.club_id" if hc else ""; cn = "c.name" if hc else "NULL"
    dsel = f"m.{dc}" if dc else "NULL"
    exc = _notin("m.league_id", exclude) if "league_id" in cols else ""
    we = ("m.team_id IS NOT NULL OR m.club_id IS NOT NULL" if (ht and hc) else ("m.team_id IS NOT NULL" if ht else "m.club_id IS NOT NULL"))
    out = {}; cur = lnp.cursor(); B = 800; idl = sorted({x for x in ids if x})
    for i in range(0, len(idl), B):
        inids = ",".join("'" + s.replace("'", "") + "'" for s in idl[i:i + B])
        cur.execute(f"""SELECT DISTINCT ON (m.player_id) m.player_id::text,{tsel},{csel},{cn},{dsel}
                        FROM pm_player_match_stats m {cj}
                        WHERE m.player_id::text IN ({inids}) AND ({we}){exc}
                        ORDER BY m.player_id, m.{oc} DESC NULLS LAST""")
        for pid, tid, cid, cname, md in cur.fetchall(): out[pid] = (tid, cid, cname, _to_date(md))
    cur.close(); return out


def _bucket(age):
    if age is None: return None
    if age <= 17: return "u17"
    if age <= 19: return "1819"
    return "20"


def pobierz_populacje(lnp, season_id, exclude=None):
    """Populacja sezonu: ostatni mecz LIGOWY każdego gracza -> (overall, season, league_id, play_id, age)."""
    cols = _kolumny(lnp, "pm_player_match_score")
    oc = "match_date" if "match_date" in cols else "created_at"
    lg = "league_id" if "league_id" in cols else "NULL"
    pl = "play_id" if "play_id" in cols else "NULL"
    ag = "age" if "age" in cols else "NULL"
    exc = _notin("league_id", exclude) if "league_id" in cols else ""
    cur = lnp.cursor()
    cur.execute(f"""
      SELECT overall, season, lid, plid, age FROM (
        SELECT overall_score overall, season_score season, {lg} lid, {pl} plid, {ag} age,
               ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY {oc} DESC NULLS LAST) rn
        FROM pm_player_match_score WHERE season_id = %s{exc}
      ) t WHERE rn = 1
    """, (season_id,))
    rows = cur.fetchall()
    cur.close()
    return rows


def zbuduj_rozklady(pop_raw, allmap, bad_plays):
    """Zwraca sortowane listy score (overall/season) per grupa: all / liga / bucket / liga×bucket."""
    A = {"ov": {"all": [], "lg": {}, "age": {}, "lgage": {}},
         "se": {"all": [], "lg": {}, "age": {}, "lgage": {}}}
    for ov, se, lid, plid, age in pop_raw:
        lig = allmap.get(lid)
        if _is_women(lig) or (plid in bad_plays):
            continue
        try:
            bk = _bucket(int(age)) if age is not None else None
        except Exception:
            bk = None
        for m, x in (("ov", ov), ("se", se)):
            if x is None:
                continue
            A[m]["all"].append(x)
            if lid: A[m]["lg"].setdefault(lid, []).append(x)
            if bk: A[m]["age"].setdefault(bk, []).append(x)
            if lid and bk: A[m]["lgage"].setdefault((lid, bk), []).append(x)
    for m in ("ov", "se"):
        A[m]["all"].sort()
        for d in (A[m]["lg"], A[m]["age"], A[m]["lgage"]):
            for k in d: d[k].sort()
    return A


def _toppct(arr, x, min_n):
    n = len(arr)
    if n < min_n or x is None:
        return None
    r = bisect.bisect_right(arr, x)
    return max(1, min(100, round((1 - r / n) * 100)))


def pct_dla(A, ovr, ser, lid, bk, min_n):
    def one(m, x):
        return {"all": _toppct(A[m]["all"], x, min_n),
                "lg": _toppct(A[m]["lg"].get(lid, []), x, min_n),
                "age": _toppct(A[m]["age"].get(bk, []), x, min_n),
                "lgage": _toppct(A[m]["lgage"].get((lid, bk), []), x, min_n)}
    return {"ov": one("ov", ovr), "se": one("se", ser)}


def _logo_data():
    import base64
    for name in ("logo.png", "logo.PNG", "logo.jpg", "logo.svg"):
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            mime = "image/svg+xml" if name.endswith(".svg") else ("image/jpeg" if name.endswith(".jpg") else "image/png")
            return f"data:{mime};base64," + base64.b64encode(open(p, "rb").read()).decode()
    return None


# ───────── HTML ─────────
TEMPLATE = r'''<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>PM progress rank</title>
<style>
  :root{--bg:#08080A;--card:#0e0e11;--line:#1c1c22;--ink:#fff;--mut:#8a8a90;--red:#F00E0E;--grn:#31C56A;--amb:#E0A93C;}
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Arial,sans-serif;font-size:16px;line-height:1.35}
  .wrap{max-width:560px;margin:0 auto;padding:16px 14px 48px}
  a{color:inherit;text-decoration:none}
  .hd{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:6px 2px 14px;border-bottom:1px solid var(--line)}
  .hd img{height:60px;width:auto;display:block}
  .hd .r{text-align:right}.hd .d{color:var(--mut);font-size:12px}.hd .t{font-weight:800;font-size:15px}
  .lead{margin:16px 2px 6px}
  .lead h1{font-size:30px;line-height:1;margin:0;font-weight:900;letter-spacing:-.02em}.lead h1 b{color:var(--red)}
  .lead p{color:var(--mut);font-size:13px;margin:6px 0 0}
  .filters{position:sticky;top:0;z-index:5;background:linear-gradient(var(--bg),var(--bg) 80%,rgba(8,8,10,0));padding:12px 2px 8px;margin-top:6px}
  .flabel{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em;margin:8px 2px 4px}
  .frow{display:flex;gap:8px;flex-wrap:wrap;padding-bottom:6px}
  .seg{display:inline-flex;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:3px;gap:2px}
  .seg button{border:0;background:transparent;color:var(--mut);font-size:13px;font-weight:700;padding:7px 12px;border-radius:8px;cursor:pointer;white-space:nowrap}
  .seg button.on{background:var(--red);color:#fff}
  select{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:10px;padding:9px 12px;font-size:14px;font-weight:600;min-width:150px}
  input.search{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:10px;padding:9px 12px;font-size:14px;width:100%;margin-top:8px}
  .sec{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.08em;margin:22px 2px 10px;font-weight:700}
  .gain{display:flex;align-items:center;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:10px}
  .gain.top{border-color:#6a5327;background:linear-gradient(180deg,#151216,#0e0d10)}
  .gain .pos{font-weight:900;font-size:20px;color:var(--mut);min-width:26px;text-align:center}.gain.top .pos{color:var(--amb)}
  .gain .info{flex:1;min-width:0}
  .gain .nm{font-weight:800;font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .gain .cl{color:var(--mut);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .gain .chg{text-align:right;flex-shrink:0}.gain .jp{font-weight:900;font-size:22px;color:var(--grn);line-height:1}.gain .jp.dn{color:var(--red)}
  .gain .ba{color:var(--mut);font-size:12px;margin-top:3px;font-weight:600}
  .chev{color:var(--mut);font-size:18px;flex-shrink:0}
  .row{display:flex;align-items:center;gap:11px;padding:12px 8px;border-bottom:1px solid var(--line)}
  .row.me{background:rgba(240,14,14,.10);border-radius:10px;border-bottom-color:transparent}
  .row .pos{min-width:34px;text-align:center;font-weight:800;color:var(--mut);font-size:14px}
  .row .info{flex:1;min-width:0}
  .row .nm{font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .row.prem{box-shadow:inset 3px 0 0 var(--red);background:rgba(240,14,14,.06)}
  .gain.prem{box-shadow:inset 3px 0 0 var(--red)}
  .pct{color:var(--amb);font-weight:800}
  .pctc{color:var(--mut);font-weight:600}
  .legend{font-size:12px;color:var(--mut);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:6px 2px 2px;line-height:1.45}
  .legend b{color:var(--ink);font-weight:700}
  .legend .r{color:var(--red)}
  .row .cl{color:var(--mut);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .row .v{font-weight:800;font-size:16px;min-width:50px;text-align:right}
  .row .d{min-width:52px;text-align:right;font-weight:700;font-size:13px;color:var(--mut)}.row .d.up{color:var(--grn)}.row .d.dn{color:var(--red)}
  .more{width:100%;margin-top:12px;padding:12px;background:var(--card);border:1px solid var(--line);border-radius:12px;color:var(--ink);font-weight:700;font-size:14px;cursor:pointer}
  .empty{color:var(--mut);text-align:center;padding:24px;font-size:14px}
  .count{color:var(--mut);font-size:12px;margin:2px 2px 8px}
  .foot{margin-top:28px;padding-top:16px;border-top:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
  .foot .b{font-weight:900;font-size:15px}.foot .pm{color:var(--red);font-weight:800;font-size:13px}
</style></head><body><div class="wrap">
  <div class="hd">__BRAND__<div class="r"><div class="d">Aktualizacja</div><div class="t">__LABEL__</div></div></div>
  <div class="lead"><h1>PM <b>progress</b> rank</h1><p>__SUB__</p></div>
  <div class="filters">
    <div class="flabel">Metryka / sortowanie</div>
    <div class="frow">
      <div class="seg" id="segMetric"><button data-v="overall" class="on">Overall</button><button data-v="season">Sezon</button></div>
      <div class="seg" id="segMode"><button data-v="progress" class="on">Przyrost</button><button data-v="score">PM Score</button></div>
    </div>
    <div class="flabel">Kto / liga / wiek</div>
    <div class="frow">
      <div class="seg" id="segSrc"><button data-v="premium" class="on">Premium</button><button data-v="all">Wszyscy</button><button data-v="ref">Top-szczeble</button></div>
      <select id="fLeague"><option value="all">Wszystkie ligi</option></select>
      <div class="seg" id="segAge"><button data-v="all" class="on">Wszyscy</button><button data-v="u17">≤17</button><button data-v="1819">18–19</button><button data-v="20">20+</button></div>
    </div>
    <input class="search" id="q" placeholder="Szukaj zawodnika…">
  </div>
  <div class="legend">Zawodnicy z platformy — <b class="r">czerwona krawędź</b>. Ich <b>top X%</b> to miejsce na tle <b>wszystkich</b> w wybranym wycinku: <b>Polska</b> / <b>liga</b> / <b>rocznik</b> / <b>liga×rocznik</b> — wartość i podpis zmieniają się wraz z filtrami. Sezon 2026/27, tylko rozgrywki ligowe.</div>
  <div class="sec" id="gainsTitle">Największe wzrosty — ostatni mecz w oknie</div>
  <div id="gains"></div>
  <div class="sec" id="rankTitle">Ranking</div>
  <div class="count" id="rankCount"></div>
  <div id="rank"></div>
  <button class="more" id="moreBtn" style="display:none"></button>
  <div class="foot"><div class="b">__FOOTER__</div><div class="pm">playmaker.pro</div></div>
</div>
<script>
const PLAYERS=__DATA__, TOPN=__TOP__, CAP=150;
let metric="__METRIC__", mode="__MODE__", fLeague="all", fAge="all", fSrc="premium", q="", shown=CAP;
const MEQ=new URLSearchParams(location.search).get("me"); const MEI="__ME__"; const ME=MEQ||((MEI&&MEI.slice(0,2)!=="__")?MEI:null);
const val=p=>metric==="season"?p.se:p.ov, jmp=p=>metric==="season"?p.seJump:p.ovJump, prv=p=>metric==="season"?p.sePrev:p.ovPrev;
const f1=x=>x==null?"—":x.toFixed(1).replace(".",","), fj=x=>x==null?"—":(x>0?"+":"")+x.toFixed(1).replace(".",",");
const esc=s=>(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const href=u=>u?(u.startsWith("http")?u:"https://"+u):null;
function ageOk(p){if(fAge==="all")return true;if(p.age==null)return false;if(fAge==="u17")return p.age<=17;if(fAge==="1819")return p.age>=18&&p.age<=19;if(fAge==="20")return p.age>=20;return true;}
function passes(p){if(fSrc!=="all"&&p.src!==fSrc)return false;if(fLeague!=="all"&&p.league!==fLeague)return false;if(!ageOk(p))return false;if(q&&!(p.name||"").toLowerCase().includes(q))return false;return true;}
function nm(p){const u=href(p.url);const i=esc(p.name||"—");return u?`<a href="${u}" target="_blank" rel="noopener">${i}</a>`:i;}
function go(u){if(u)window.open(u,"_blank","noopener");}
const AGEL={u17:"≤17","1819":"18–19","20":"20+"};
function pctCtx(){
  if(fLeague!=="all"&&fAge!=="all") return fLeague+" · "+AGEL[fAge];
  if(fLeague!=="all") return fLeague;
  if(fAge!=="all") return "rocznik "+AGEL[fAge];
  return "Polska";
}
function pctHtml(p){
  if(p.src!=="premium"||!p.pct) return "";
  const set=metric==="season"?p.pct.se:p.pct.ov;
  let key="all";
  if(fLeague!=="all"&&fAge!=="all")key="lgage";
  else if(fLeague!=="all")key="lg";
  else if(fAge!=="all")key="age";
  const v=set&&set[key];
  return (v==null)?"":` · <span class="pct">top ${v}% <span class="pctc">${esc(pctCtx())}</span></span>`;
}
function renderGains(list){
  const el=document.getElementById("gains"),ttl=document.getElementById("gainsTitle");
  let g,showJump;
  if(mode==="progress"){ttl.textContent="Największe wzrosty — mecz w oknie";g=list.filter(p=>jmp(p)!=null).sort((a,b)=>jmp(b)-jmp(a)).slice(0,TOPN);showJump=true;}
  else{ttl.textContent="Najwyższy PM Score — "+(metric==="season"?"sezon":"overall");g=list.slice().sort((a,b)=>(val(b)??-1)-(val(a)??-1)).slice(0,TOPN);showJump=false;}
  if(!g.length){el.innerHTML='<div class="empty">Brak zawodników dla tych filtrów.</div>';return;}
  el.innerHTML=g.map((p,i)=>{const j=jmp(p);
    const big=showJump?`<div class="jp ${j>=0?'':'dn'}">${fj(j)}</div>`:`<div class="jp" style="color:var(--ink)">${f1(val(p))}</div>`;
    const sub=showJump?`${f1(prv(p))} → ${f1(val(p))}`:(j!=null?("Δ "+fj(j)):"");
    return `<div class="gain ${i===0?'top':''} ${p.src==='premium'?'prem':''}" onclick="go('${href(p.url)||''}')">
      <div class="pos">${i+1}</div><div class="info"><div class="nm">${nm(p)}</div><div class="cl">${esc(p.club||'')}${p.league?' · '+esc(p.league):''}${pctHtml(p)}</div></div>
      <div class="chg">${big}<div class="ba">${sub}</div></div>${href(p.url)?'<div class="chev">›</div>':''}</div>`;}).join("");
}
function renderRank(list){
  let arr=(mode==="progress")?list.filter(p=>jmp(p)!=null):list.slice();
  if(mode==="progress")arr.sort((a,b)=>jmp(b)-jmp(a));else arr.sort((a,b)=>(val(b)??-1)-(val(a)??-1));
  document.getElementById("rankTitle").textContent=mode==="progress"?"Ranking przyrostów (mecz w oknie)":("Ranking PM Score — "+(metric==="season"?"sezon":"overall"));
  document.getElementById("rankCount").textContent=arr.length+" zawodników"+(arr.length>shown?(" · pokazano "+shown):"");
  const el=document.getElementById("rank");
  if(!arr.length){el.innerHTML='<div class="empty">Brak wyników dla tych filtrów.</div>';document.getElementById("moreBtn").style.display="none";return;}
  const view=arr.slice(0,shown);
  el.innerHTML=view.map((p,i)=>{const j=jmp(p),dc=j==null?"":(j>0?"up":(j<0?"dn":"")),me=(ME&&p.id===ME)?"me":"";
    return `<div class="row ${me} ${p.src==='premium'?'prem':''}" onclick="go('${href(p.url)||''}')"><div class="pos">${i+1}</div>
      <div class="info"><div class="nm">${nm(p)}</div><div class="cl">${esc(p.club||'')}${p.league?' · '+esc(p.league):''}${pctHtml(p)}</div></div>
      <div class="v">${f1(val(p))}</div><div class="d ${dc}">${fj(j)}</div></div>`;}).join("");
  const mb=document.getElementById("moreBtn");
  if(arr.length>shown){mb.style.display="block";mb.textContent="Pokaż więcej ("+(arr.length-shown)+")";mb.onclick=()=>{shown+=CAP;renderRank(list);};}
  else mb.style.display="none";
  if(ME){const r=el.querySelector(".me");if(r)r.scrollIntoView({block:"center"});}
}
function leaguesFor(){return [...new Set(PLAYERS.filter(p=>(fSrc==="all"||p.src===fSrc)&&ageOk(p)).map(p=>p.league).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"pl"));}
function refreshLeagues(){const sel=document.getElementById("fLeague"),ls=leaguesFor();
  sel.innerHTML='<option value="all">Wszystkie ligi</option>'+ls.map(l=>`<option value="${esc(l)}">${esc(l)}</option>`).join("");
  if(fLeague!=="all"&&ls.includes(fLeague))sel.value=fLeague;else{fLeague="all";sel.value="all";}
  sel.style.display=ls.length?"":"none";}
function render(){shown=Math.max(shown,CAP);const list=PLAYERS.filter(passes);renderGains(list);renderRank(list);}
function initFilters(){
  document.getElementById("fLeague").onchange=e=>{fLeague=e.target.value;shown=CAP;render();};
  document.getElementById("q").oninput=e=>{q=e.target.value.toLowerCase().trim();shown=CAP;render();};
  const bind=(id,set,refresh)=>document.querySelectorAll("#"+id+" button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#"+id+" button").forEach(x=>x.classList.remove("on"));b.classList.add("on");set(b.dataset.v);shown=CAP;if(refresh)refreshLeagues();render();});
  bind("segMetric",v=>metric=v,false);bind("segMode",v=>mode=v,false);bind("segAge",v=>fAge=v,true);bind("segSrc",v=>fSrc=v,true);
  document.querySelectorAll("#segMetric button").forEach(b=>b.classList.toggle("on",b.dataset.v===metric));
  document.querySelectorAll("#segMode button").forEach(b=>b.classList.toggle("on",b.dataset.v===mode));
  document.querySelectorAll("#segSrc button").forEach(b=>b.classList.toggle("on",b.dataset.v===fSrc));
  document.querySelectorAll("#segAge button").forEach(b=>b.classList.toggle("on",b.dataset.v===fAge));
  refreshLeagues();
}
initFilters();render();
</script></body></html>'''


def build_html(players, label, sub, footer, top, im, imode, logo=None, me=""):
    brand = (f'<img src="{logo}" alt="PlayMaker">' if logo else '<div class="t">PLAYMAKER.PRO</div>')
    return (TEMPLATE.replace("__BRAND__", brand).replace("__LABEL__", label).replace("__SUB__", sub)
            .replace("__FOOTER__", footer).replace("__TOP__", str(max(1, top)))
            .replace("__METRIC__", im).replace("__MODE__", imode).replace("__ME__", me or "")
            .replace("__DATA__", json.dumps(players, ensure_ascii=False)))


def zapisz_html(outdir, players, label, sub, footer, top, im, imode):
    html = build_html(players, label, sub, footer, top, im, imode, logo=_logo_data(), me="")
    path = os.path.join(outdir, "ranking.html")
    with open(path, "w", encoding="utf-8") as f: f.write(html)
    return path


def _row_from(cur, prev, in_window):
    ov, se = s100(cur.get("overall")), s100(cur.get("season"))
    ovp = s100(prev.get("overall")) if (prev and in_window) else None
    sep = s100(prev.get("season")) if (prev and in_window) else None
    return {"ov": ov, "ovPrev": ovp, "ovJump": (round(ov - ovp, 1) if (ov is not None and ovp is not None) else None),
            "se": se, "sePrev": sep, "seJump": (round(se - sep, 1) if (se is not None and sep is not None) else None)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    ap.add_argument("--metric", choices=["overall", "season"], default="overall")
    ap.add_argument("--sort", choices=["progress", "score"], default="progress")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--min-age", dest="min_age", type=int, default=15)
    ap.add_argument("--teams", default=None)
    ap.add_argument("--data-do", dest="data_do", default=None)
    ap.add_argument("--dni", type=int, default=7)
    ap.add_argument("--ref-top", dest="ref_top", type=int, default=500, help="ilu referencyjnych z top-szczebli (0 = tylko premium)")
    ap.add_argument("--ref-od", dest="ref_od", default="2025-07-01", help="referencyjni z meczem od tej daty")
    ap.add_argument("--sezon", default="3c77d143-8010-4073-9842-d6b63365ffce", help="season_id do percentyli (26/27)")
    ap.add_argument("--min-grupa", dest="min_grupa", type=int, default=20, help="min. wielkość grupy do percentyla")
    ap.add_argument("--sprawdz", default=None, help="wypisz w konsoli szczegóły percentyla dla premium (fragment nazwiska)")
    ap.add_argument("--outdir", default=os.path.join(HERE, "data", "ranking"))
    a = ap.parse_args()

    csv_path = a.csv or os.path.join(HERE, "premium_pilkarze_lnp.csv")
    if not os.path.exists(csv_path): sys.exit(f"Nie znalazłem CSV: {csv_path}")
    os.makedirs(a.outdir, exist_ok=True)
    d_end = _to_date(a.data_do) or date.today(); d_start = d_end - timedelta(days=max(1, a.dni) - 1)

    premium = wczytaj_premium(csv_path)
    prem_ids = {p["player_lnp"] for p in premium}
    print(f"Premium: {len(premium)}")
    lnp = connect_lnp()
    allmap, topmap, cupmap = pobierz_ligi(lnp)
    print(f"  ligi: wszystkich={len(allmap)}, top-szczeble={len(topmap)}, pucharowe(wykluczone)={len(cupmap)} -> {sorted(set(topmap.values()))[:8]}")

    sc_prem = _score_rows(lnp, None, ids=list(prem_ids), exclude=cupmap)
    print(f"  score premium: {len(sc_prem)}")
    ref = pobierz_top(lnp, list(topmap.keys()), a.ref_od, a.ref_top) if a.ref_top > 0 else {}
    ref = {pid: d for pid, d in ref.items() if pid not in prem_ids}   # premium ma pierwszeństwo
    print(f"  referencyjni (top-szczeble): {len(ref)}")

    all_ids = list(prem_ids | set(ref.keys()))
    teamy = pobierz_team(lnp, all_ids, exclude=cupmap)
    nazwiska = pobierz_nazwiska(lnp, list(ref.keys()))
    print("Pobieram populację sezonu do percentyli ...")
    pop_raw = pobierz_populacje(lnp, a.sezon, exclude=cupmap)
    print(f"  populacja sezonu {a.sezon[:8]}: {len(pop_raw)} graczy")
    lnp.close()
    tm, cm = load_maps(a.teams)
    print(f"  mapping nazw: team={len(tm)}, club={len(cm)}")
    bad_plays = load_slownik()
    print(f"  słownik: odrzucam {len(bad_plays)} rozgrywek (kobiece/baraże/7x7)")
    ROZ = zbuduj_rozklady(pop_raw, allmap, bad_plays)
    print(f"  rozkłady percentyli: Polska n={len(ROZ['ov']['all'])}, lig={len(ROZ['ov']['lg'])}, bucketów={len(ROZ['ov']['age'])}")

    def women_or_bad(cur, lig):
        return (cur.get("play_id") in bad_plays) or _is_women(lig)

    def klub_for(pid):
        tid, cid, raw, lm = teamy.get(pid, (None, None, "", None))
        return ((tm.get(tid) if tid else None) or (cm.get(cid) if cid else None) or raw or ""), lm

    players = []
    gralo = 0
    # premium
    for p in premium:
        d = sc_prem.get(p["player_lnp"])
        if not d or not d["curr"]: continue
        cur = d["curr"]; age = cur.get("age")
        try: age = int(age) if age is not None else None
        except Exception: age = None
        if age is not None and age <= a.min_age: continue
        lig = allmap.get(cur.get("league_id"), None)
        if women_or_bad(cur, lig): continue
        klub, lm = klub_for(p["player_lnp"])
        inw = lm is not None and d_start <= lm <= d_end
        if inw: gralo += 1
        r = _row_from(cur, d["prev"], inw)
        pct = pct_dla(ROZ, cur.get("overall"), cur.get("season"),
                      cur.get("league_id"), _bucket(age), a.min_grupa)
        if a.sprawdz and a.sprawdz.lower() in (p["player_name"] or "").lower():
            ovr = cur.get("overall"); bk = _bucket(age); lid = cur.get("league_id")
            print(f"\n  ── SPRAWDZENIE: {p['player_name']} | overall={s100(ovr)} | liga={lig} | wiek={age} (bucket {bk}) ──")
            for etyk, arr in [("Polska", ROZ["ov"]["all"]), (f"liga {lig}", ROZ["ov"]["lg"].get(lid, [])),
                              (f"rocznik {bk}", ROZ["ov"]["age"].get(bk, [])), ("liga×rocznik", ROZ["ov"]["lgage"].get((lid, bk), []))]:
                n = len(arr)
                below = bisect.bisect_left(arr, ovr) if ovr is not None else 0
                top = (max(1, min(100, round((1 - bisect.bisect_right(arr, ovr) / n) * 100))) if (n and ovr is not None) else None)
                print(f"     {etyk:<22} n={n:<6} lepszych_od_niego={n-below:<5} top={top}%")
        players.append({"id": p["player_lnp"], "name": p["player_name"], "url": p["profile_url"],
                        "club": klub, "league": lig, "age": age, "src": "premium", "pct": pct, **r})
    # referencyjni
    for pid, d in ref.items():
        cur = d["curr"]; age = cur.get("age")
        try: age = int(age) if age is not None else None
        except Exception: age = None
        if age is not None and age <= a.min_age: continue
        lig = allmap.get(cur.get("league_id"), None)
        if women_or_bad(cur, lig): continue
        klub, lm = klub_for(pid)
        inw = lm is not None and d_start <= lm <= d_end
        r = _row_from(cur, d["prev"], inw)
        players.append({"id": pid, "name": nazwiska.get(pid, "Zawodnik"), "url": None,
                        "club": klub, "league": lig, "age": age, "src": "ref", **r})

    print(f"  RAZEM w rankingu: {len(players)} (premium grało w oknie: {gralo})")
    sub = f"premium na tle top-szczebli · {d_end:%d.%m.%Y}"
    label = f"{d_start:%d.%m}–{d_end:%d.%m}"
    html = zapisz_html(a.outdir, players, label, sub, "jesteś jak twój ostatni mecz", a.top, a.metric, a.sort)

    # kompaktowy artefakt dla Streamlit (bez bazy w runtime)
    data_json = {"players": players, "label": label, "sub": sub, "footer": "jesteś jak twój ostatni mecz",
                 "top": a.top, "metric": a.metric, "mode": a.sort, "logo": _logo_data(),
                 "wygenerowano": date.today().strftime("%Y-%m-%d")}
    with open(os.path.join(a.outdir, "ranking_data.json"), "w", encoding="utf-8") as f:
        json.dump(data_json, f, ensure_ascii=False)

    latest = os.path.join(a.outdir, "ranking_latest.csv")
    with open(latest, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["src", "name", "league", "club", "age", "overall", "overall_skok", "season", "season_skok", "url"])
        for p in sorted(players, key=lambda r: (r["ov"] if r["ov"] is not None else -1), reverse=True):
            w.writerow([p["src"], p["name"], p["league"] or "", p["club"], p["age"] if p["age"] is not None else "",
                        p["ov"], p["ovJump"] if p["ovJump"] is not None else "",
                        p["se"], p["seJump"] if p["seJump"] is not None else "", p["url"] or ""])
    print(f"\n✓ HTML: {html}\n✓ CSV:  {latest}\n✓ JSON (Streamlit): {os.path.join(a.outdir, 'ranking_data.json')}")


if __name__ == "__main__":
    main()
