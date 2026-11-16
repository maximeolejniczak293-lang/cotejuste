"""xG (buts attendus) par match depuis Understat : Ligue 1, Premier League, LaLiga, saisons 2022-23 à 2026-27.

Comment Understat sert ses données (vérifié le 14/11/2026) :
  - format actuel : JSON à l'adresse https://understat.com/getLeagueData/<ligue>/<année>
    -> {"teams": ..., "players": ..., "dates": [{"h": {"title"}, "a": ..., "goals": {"h","a"}, "xG": {"h","a"},
        "datetime", "isResult"}, ...]} ;
  - ancien format (avant 2025) : page HTML /league/<ligue>/<année> avec « datesData = JSON.parse('...') ».
  Les deux sont lus. Le 14/11/2026, Understat affichait une page de maintenance (« We will come back soon »),
  même dans un vrai navigateur : on se rabat alors sur la copie archivée par la Wayback Machine (archive.org).

Ordre des sources : Understat en direct -> archive.org -> dernières données déjà enregistrées (data/xg/).
Politesse : cache local, une requête à la fois avec 5 s d'écart, User-Agent explicite.
Saisons passées : récupérées une seule fois (complètes), ensuite seule la saison en cours est mise à jour.

Résultat : data/xg/<ligue>_<saison>.csv (date;domicile;exterieur;buts_dom;buts_ext;xg_dom;xg_ext), noms de names.py,
plus data/xg/_sources.json (d'où vient chaque fichier et quand).
"""
import csv
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from names import LEAGUES, canon  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("CJ_DATA_DIR", os.path.join(ROOT, "data"))
XG_DIR = os.path.join(DATA_DIR, "xg")
SOURCES = os.path.join(XG_DIR, "_sources.json")
CACHE = os.path.join(os.environ.get("CJ_CACHE_DIR", os.path.join(ROOT, "cache")), "understat")
UA = "CoteJuste/1.0 (projet personnel de prediction football, usage non commercial)"
DELAY = 5.0
CODE = {"fr1": "Ligue_1", "en1": "EPL", "es1": "La_liga"}
SEASONS = {2022: "2022-23", 2023: "2023-24", 2024: "2024-25", 2025: "2025-26", 2026: "2026-27"}
CURRENT_YEAR = 2026
COLS = ["date", "domicile", "exterieur", "buts_dom", "buts_ext", "xg_dom", "xg_ext"]

_last = 0.0
UNKNOWN_NAMES: set = set()


class Unavailable(RuntimeError):
    pass


# --------------------------------------------------------------------------- réseau
def _get(url, ajax=False):
    """GET poli : 5 s minimum entre deux requêtes, User-Agent explicite, gzip géré."""
    global _last
    wait = DELAY - (time.monotonic() - _last)
    if _last and wait > 0:
        time.sleep(wait)
    headers = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9"}
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise Unavailable(f"HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise Unavailable(f"réseau : {getattr(e, 'reason', e)}") from None
    finally:
        _last = time.monotonic()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def _parse(text):
    """Renvoie la liste des matchs, quel que soit le format (JSON actuel ou ancienne page HTML)."""
    t = text.lstrip()
    if t.startswith("{"):
        d = json.loads(t)
        if isinstance(d.get("dates"), list):
            return d["dates"]
    m = re.search(r"datesData\s*=\s*JSON\.parse\('(.*?)'\)", text, re.S)
    if m:
        return json.loads(m.group(1).encode("utf-8").decode("unicode_escape"))
    if "come back soon" in text.lower():
        raise Unavailable("Understat en maintenance")
    raise Unavailable("format Understat non reconnu")


def _from_understat(code, year):
    errs = []
    for url, ajax in ((f"https://understat.com/getLeagueData/{code}/{year}", True),
                      (f"https://understat.com/league/{code}/{year}", False)):
        try:
            return _parse(_get(url, ajax)), url
        except (Unavailable, ValueError) as e:
            errs.append(str(e))
            if "maintenance" in str(e):
                break  # inutile d'insister : tout le site est en maintenance
    raise Unavailable(" / ".join(errs))


def _captures(target):
    """Copies archive.org d'une adresse (index CDX), de la plus récente à la plus ancienne, avec leur taille."""
    q = urllib.parse.urlencode({"url": target, "output": "json", "filter": "statuscode:200",
                                "fl": "timestamp,length", "collapse": "timestamp:8"})
    txt = _get("https://web.archive.org/cdx/search/cdx?" + q)
    try:
        rows = json.loads(txt)[1:]
    except ValueError:
        raise Unavailable("index archive.org indisponible") from None
    return sorted(((ts, int(ln or 0)) for ts, ln in rows), reverse=True)


def _from_archive(code, year, current, tries=3):
    """Copie archivée la plus complète : on essaie les plus récentes qui contiennent des données
    (l'ancienne page HTML ne contient les matchs que jusqu'au changement de format, fin 2025)."""
    errs, best = [], None
    for target, min_len in ((f"understat.com/getLeagueData/{code}/{year}", 5000), (f"understat.com/league/{code}/{year}", 20000)):
        try:
            caps = [c for c in _captures(target) if c[1] >= min_len][:tries]
        except Unavailable as e:
            errs.append(f"{target} : {e}")
            continue
        if not caps:
            errs.append(f"pas de copie utile de {target}")
            continue
        for ts, _ in caps:
            try:
                matches = _parse(_get(f"https://web.archive.org/web/{ts}id_/https://{target}"))
            except (Unavailable, ValueError) as e:
                errs.append(f"{target} {ts[:8]} : {e}")
                continue
            played = sum(1 for m in matches if m.get("isResult"))
            if best is None or played > best[0]:
                best = (played, matches, f"archive.org {ts[:8]} ({target.split('/')[1]})")
            if played == len(matches):
                break  # saison complète : inutile d'aller plus loin
        if best and best[0] == len(best[1]):
            break
    if best:
        return best[1], best[2]
    raise Unavailable(" / ".join(errs))


# --------------------------------------------------------------------------- fichiers
def _sources():
    try:
        with open(SOURCES, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def _save_sources(s):
    os.makedirs(XG_DIR, exist_ok=True)
    with open(SOURCES, "w", encoding="utf-8", newline="\n") as f:  # mêmes fins de ligne sous Windows et sur GitHub
        json.dump(s, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def csv_path(league, year):
    return os.path.join(XG_DIR, f"{league}_{SEASONS[year]}.csv")


def _num(x):
    return f"{float(x):.3f}".rstrip("0").rstrip(".").replace(".", ",")


def _write(league, year, matches):
    rows = []
    for m in matches:
        if not m.get("isResult"):
            continue
        h = canon(league, m["h"]["title"], strict=False)
        a = canon(league, m["a"]["title"], strict=False)
        for raw, c in ((m["h"]["title"], h), (m["a"]["title"], a)):
            if raw == c and raw not in _known(league):
                UNKNOWN_NAMES.add((league, raw))
        rows.append([m["datetime"][:10], h, a, int(m["goals"]["h"]), int(m["goals"]["a"]),
                     _num(m["xG"]["h"]), _num(m["xG"]["a"])])
    rows.sort()
    os.makedirs(XG_DIR, exist_ok=True)
    tmp = csv_path(league, year) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(COLS)
        w.writerows(rows)
    os.replace(tmp, csv_path(league, year))
    return len(rows), len(matches)


def _known(league):
    from names import ALIASES
    return {c for c in ALIASES[league]}


def _cache_raw(league, year, matches, source):
    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, f"{league}_{year}.json"), "w", encoding="utf-8") as f:
        json.dump({"fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": source, "dates": matches}, f)


# --------------------------------------------------------------------------- mise à jour
LIVE_OK = False  # devient vrai dès qu'Understat a répondu en direct pendant ce lancement


def incomplete_past(leagues=None):
    """Saisons passées encore incomplètes ou absentes (à compléter quand Understat sera de retour)."""
    src = _sources()
    return [(lg, y) for lg in (leagues or CODE) for y in SEASONS if y != CURRENT_YEAR
            and not (src.get(f"{lg}_{SEASONS[y]}", {}).get("complete") and os.path.exists(csv_path(lg, y)))]


def daily(log=print):
    """Mise à jour quotidienne : saison en cours ; si Understat répond en direct, on complète aussi,
    une seule fois, les saisons passées incomplètes (en direct uniquement, pas par archive.org).
    Renvoie la liste des saisons complétées (vide la plupart du temps)."""
    update(years=[CURRENT_YEAR], log=log)
    todo = incomplete_past()
    if not (LIVE_OK and todo):
        return []
    log(f"   Understat est de retour : on complète {len(todo)} saison(s) passée(s)")
    done = []
    for lg, y in todo:
        before = _sources().get(f"{lg}_{SEASONS[y]}", {}).get("matches", 0)
        update(years=[y], leagues=[lg], log=log, live_only=True)
        after = _sources().get(f"{lg}_{SEASONS[y]}", {})
        if after.get("matches", 0) > before:
            done.append(f"{lg}_{SEASONS[y]} ({before} -> {after['matches']} matchs)")
    return done


def update(years=None, leagues=None, log=print, live_only=False):
    """Met à jour les fichiers xG. Par défaut : saisons passées manquantes + saison en cours.
    live_only : Understat en direct seulement (pas d'archive.org).
    Ne lève jamais d'exception : en cas d'échec, on garde les dernières données connues."""
    global LIVE_OK
    src = _sources()
    years = years or list(SEASONS)
    leagues = leagues or list(CODE)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    live_down = False
    report = []
    for lg in leagues:
        for year in years:
            key = f"{lg}_{SEASONS[year]}"
            current = year == CURRENT_YEAR
            info = src.get(key, {})
            if not current and info.get("complete") and os.path.exists(csv_path(lg, year)):
                continue  # saison passée déjà complète : jamais redemandée
            if current and info.get("checked") == today and os.path.exists(csv_path(lg, year)):
                continue  # déjà mise à jour aujourd'hui
            matches, origin, errors = None, None, []
            if not live_down:
                try:
                    matches, origin = _from_understat(CODE[lg], year)
                    origin = "understat.com"
                    LIVE_OK = True
                except Unavailable as e:
                    errors.append(f"Understat : {e}")
                    live_down = "maintenance" in str(e) or "réseau" in str(e)
            if matches is None and not live_only:
                try:
                    matches, origin = _from_archive(CODE[lg], year, current)
                except Unavailable as e:
                    errors.append(f"archive : {e}")
            if matches is None:
                msg = f"{key} : xG indisponibles ({' ; '.join(errors)}), on garde " + (
                    f"les données du {info.get('fetched', '?')[:10]}" if os.path.exists(csv_path(lg, year)) else "les buts seuls")
                log("   ! " + msg)
                report.append(msg)
                continue
            played, total = _write(lg, year, matches)
            _cache_raw(lg, year, matches, origin)
            last = max((m["datetime"][:10] for m in matches if m.get("isResult")), default=None)
            complete = played == total and total > 0
            src[key] = dict(source=origin, fetched=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            checked=today, matches=played, total=total, last_match=last, complete=complete)
            log(f"   {key} : {played}/{total} matchs avec xG (source {origin}, dernier match {last})")
            report.append(f"{key} : {played} matchs, {origin}")
            _save_sources(src)
    if UNKNOWN_NAMES:
        log("   ! noms Understat inconnus (à ajouter dans names.py) : " + ", ".join(sorted(n for _, n in UNKNOWN_NAMES)))
    return report


def rebuild_from_cache(log=print):
    """Réécrit les CSV à partir des réponses brutes en cache (après un ajout d'alias dans names.py). 0 requête."""
    UNKNOWN_NAMES.clear()
    for lg in CODE:
        for year in SEASONS:
            p = os.path.join(CACHE, f"{lg}_{year}.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    _write(lg, year, json.load(f)["dates"])
    if UNKNOWN_NAMES:
        log("   ! noms Understat inconnus : " + ", ".join(sorted(f"{l}:{n}" for l, n in UNKNOWN_NAMES)))


# --------------------------------------------------------------------------- lecture et association
def load_xg(league):
    """Tous les matchs Understat enregistrés pour ce championnat (noms canoniques)."""
    rows = []
    for year in SEASONS:
        p = csv_path(league, year)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                rows.append(dict(date=r["date"], home=canon(league, r["domicile"], strict=False),
                                 away=canon(league, r["exterieur"], strict=False),
                                 hg=int(r["buts_dom"]), ag=int(r["buts_ext"]),
                                 xh=float(r["xg_dom"].replace(",", ".")), xa=float(r["xg_ext"].replace(",", "."))))
    return rows


def attach(df, league):
    """Ajoute les colonnes xh, xa (NaN si inconnu) à nos résultats : mêmes équipes, date à ± 1 jour.
    Renvoie (df, rapport). Le rapport sert au contrôle : part des matchs Understat associés, écarts de score."""
    import pandas as pd
    df = df.copy()
    df["xh"] = float("nan")
    df["xa"] = float("nan")
    xg = load_xg(league)
    rep = dict(understat=len(xg), associes=0, ecarts=[], non_associes=[], par_saison={})
    if not xg:
        return df, rep
    idx = {}
    for i, r in enumerate(df.itertuples()):
        idx.setdefault((r.home, r.away), []).append((r.date.date() if hasattr(r.date, "date") else date.fromisoformat(str(r.date)[:10]), i))
    used = set()
    xh, xa = df["xh"].to_numpy(copy=True), df["xa"].to_numpy(copy=True)
    for m in xg:
        d = date.fromisoformat(m["date"])
        hit = None
        for dd, i in idx.get((m["home"], m["away"]), []):
            if abs((dd - d).days) <= 1 and i not in used:
                hit = i
                break
        season = next((s for y, s in SEASONS.items() if date(y, 7, 1) <= d < date(y + 1, 7, 1)), "?")
        ps = rep["par_saison"].setdefault(season, dict(understat=0, associes=0))
        ps["understat"] += 1
        if hit is None:
            rep["non_associes"].append(f"{m['date']} {m['home']}-{m['away']}")
            continue
        used.add(hit)
        rep["associes"] += 1
        ps["associes"] += 1
        xh[hit], xa[hit] = m["xh"], m["xa"]
        r = df.iloc[hit]
        if (int(r.hg), int(r.ag)) != (m["hg"], m["ag"]):
            rep["ecarts"].append(f"{m['date']} {m['home']}-{m['away']} : nous {int(r.hg)}-{int(r.ag)}, Understat {m['hg']}-{m['ag']}")
    df["xh"], df["xa"] = xh, xa
    rep["taux"] = rep["associes"] / rep["understat"]
    return df, rep


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="xG Understat pour CoteJuste")
    ap.add_argument("--seasons", default="all", help="'all' (défaut) ou 'current'")
    ap.add_argument("--check", action="store_true", help="contrôle d'association avec nos résultats (aucune requête)")
    a = ap.parse_args()
    if not a.check:
        update(years=[CURRENT_YEAR] if a.seasons == "current" else None)
    from data import load_league
    ok = True
    for lg in CODE:
        df = load_league(lg)
        _, rep = attach(df, lg)
        if not rep["understat"]:
            print(f"{lg} : aucune donnée xG"); ok = False; continue
        print(f"{lg} : {rep['associes']}/{rep['understat']} matchs Understat associés ({rep['taux'] * 100:.2f} %)"
              + "".join(f"\n   {s} : {v['associes']}/{v['understat']}" for s, v in sorted(rep["par_saison"].items())))
        for e in rep["ecarts"]:
            print("   ! écart de score :", e)
        for n in rep["non_associes"][:15]:
            print("   ? non associé :", n)
        if len(rep["non_associes"]) > 15:
            print(f"   ? ... et {len(rep['non_associes']) - 15} autres")
        ok &= rep["taux"] >= 0.99 and not rep["ecarts"]
    print("CONTRÔLE :", "OK (≥ 99 % associés, scores identiques)" if ok else "À VÉRIFIER")
