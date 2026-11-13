"""Chargement et vérification des données de matchs.

Sources :
  - historique 2022-2026 : openfootball (dossier football.json/, cloné depuis GitHub) ;
  - saison en cours : raw/<ligue>_2026-27.txt. Les résultats jusqu'au 8/11/2026 ont été saisis à la main ;
    depuis, update.py y ajoute chaque jour les résultats venant d'API-Football. Le plan gratuit ne permet
    pas de redemander les jours passés : ces fichiers servent donc d'archive et sont conservés dans le dépôt ;
  - calendrier à venir : openfootball (dates provisoires), remplacé par l'API pour les matchs à moins de 48 h.
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from names import LEAGUES, UNKNOWN, canon  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPENFOOTBALL = os.environ.get("OPENFOOTBALL_DIR", os.path.join(ROOT, "football.json"))
RAW = os.path.join(ROOT, "raw")
CACHE = os.environ.get("CJ_CACHE_DIR", os.path.join(ROOT, "cache"))
HIST_SEASONS = ["2022-23", "2023-24", "2024-25", "2025-26"]
CURRENT = "2026-27"
LOCAL_TZ = {"fr1": "Europe/Paris", "en1": "Europe/London", "es1": "Europe/Madrid"}


def _ft(m):
    sc = m.get("score")
    if isinstance(sc, dict):
        return sc.get("ft")
    if isinstance(sc, list) and len(sc) == 2:
        return sc
    return None


def _of_matches(league: str, season: str) -> list:
    path = os.path.join(OPENFOOTBALL, season, LEAGUES[league]["of"] + ".json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)["matches"]


def load_openfootball(league: str, season: str) -> pd.DataFrame:
    rows = []
    for m in _of_matches(league, season):
        ft = _ft(m)
        if not ft:
            continue
        rows.append(dict(date=m["date"], home=canon(league, m["team1"], strict=False), away=canon(league, m["team2"], strict=False),
                         hg=int(ft[0]), ag=int(ft[1]), season=season, source="openfootball"))
    return pd.DataFrame(rows)


def _raw_path(league: str) -> str:
    return os.path.join(RAW, f"{league}_{CURRENT}.txt")


def _raw_lines(league: str) -> list[str]:
    with open(_raw_path(league), encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def load_current(league: str) -> pd.DataFrame:
    rows = []
    for line in _raw_lines(league):
        d, mw, h, hg, ag, a = [x.strip() for x in line.split("|")]
        rows.append(dict(date=d, round=int(mw), home=canon(league, h), away=canon(league, a),
                         hg=int(hg), ag=int(ag), season=CURRENT, source="raw"))
    return pd.DataFrame(rows)


def add_results(league: str, matches: list[dict]) -> list[dict]:
    """Ajoute en haut de raw/<ligue>_2026-27.txt les résultats pas encore présents.
    matches : dicts {date, round, home, away, hg, ag} avec des noms canoniques. Renvoie les ajouts."""
    lines = _raw_lines(league)
    seen = set()
    for line in lines:
        _, _, h, _, _, a = [x.strip() for x in line.split("|")]
        seen.add((canon(league, h), canon(league, a)))
    new = []
    for m in matches:
        if (m["home"], m["away"]) in seen:
            continue
        seen.add((m["home"], m["away"]))
        new.append(m)
    if not new:
        return []
    new.sort(key=lambda m: (m["date"], m["home"]), reverse=True)
    out = [f"{m['date']} | {m['round'] or 0} | {m['home']} | {m['hg']} | {m['ag']} | {m['away']}" for m in new] + lines
    with open(_raw_path(league), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    return new


def load_league(league: str) -> pd.DataFrame:
    frames = [load_openfootball(league, s) for s in HIST_SEASONS]
    frames.append(load_current(league))
    df = pd.concat([f for f in frames if len(f)], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _round_num(label) -> int | None:
    """'Matchday 11' ou 'Regular Season - 11' -> 11"""
    m = re.search(r"(\d+)\s*$", str(label or ""))
    return int(m.group(1)) if m else None


def calendar(league: str, start: date, days: int = 14) -> list[dict]:
    """Matchs non joués du calendrier openfootball entre start et start + days (dates provisoires)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(LOCAL_TZ[league])
    except Exception:  # base des fuseaux absente : on suppose UTC+1
        tz = timezone(timedelta(hours=1))
    out = []
    for m in _of_matches(league, CURRENT):
        if _ft(m):
            continue
        d = date.fromisoformat(m["date"])
        if not (start <= d < start + timedelta(days=days)):
            continue
        try:
            h, a = canon(league, m["team1"]), canon(league, m["team2"])
        except KeyError:
            UNKNOWN.add((league, m["team1"] + " / " + m["team2"]))
            continue
        t = (m.get("time") or "")[:5]
        known = len(t) == 5 and t[2] == ":"
        local = datetime.combine(d, datetime.strptime(t if known else "12:00", "%H:%M").time(), tz)
        out.append(dict(home=h, away=a, kickoff=local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        time_known=known, round=_round_num(m.get("round"))))
    return out


def postponed(league: str) -> set:
    """Matchs signalés reportés ou annulés par l'API (lus dans le cache)."""
    out = set()
    for path in glob.glob(os.path.join(CACHE, "fixtures", "*.json")):
        with open(path, encoding="utf-8") as f:
            for fx in json.load(f)["data"]:
                if fx["league"] == league and fx["status"] in {"PST", "CANC", "ABD"}:
                    try:
                        out.add((canon(league, fx["home"]), canon(league, fx["away"])))
                    except KeyError:
                        pass
    return out


def table(df: pd.DataFrame) -> pd.DataFrame:
    """Classement calculé à partir des résultats."""
    t = defaultdict(lambda: dict(P=0, W=0, D=0, L=0, GF=0, GA=0, Pts=0))
    for r in df.itertuples():
        for team, gf, ga in ((r.home, r.hg, r.ag), (r.away, r.ag, r.hg)):
            s = t[team]
            s["P"] += 1; s["GF"] += gf; s["GA"] += ga
            if gf > ga:
                s["W"] += 1; s["Pts"] += 3
            elif gf == ga:
                s["D"] += 1; s["Pts"] += 1
            else:
                s["L"] += 1
    out = pd.DataFrame.from_dict(t, orient="index")
    out["GD"] = out.GF - out.GA
    return out.sort_values(["Pts", "GD", "GF"], ascending=False)


def verify(league: str) -> tuple[list[str], list[str]]:
    """Renvoie (erreurs, remarques).

    1. doublons ;
    2. classement officiel de référence (raw/live_snapshot.py, à mettre à jour à la main quand tu veux) :
       comparé aux seuls matchs joués jusqu'à sa date. Le plan gratuit de l'API ne donne pas le classement 2026 ;
    3. journées complètes : chaque équipe doit jouer une fois par journée (sinon match manquant ou reporté) ;
    4. recoupement avec openfootball pour les matchs qu'il connaît.
    """
    sys.path.insert(0, RAW)
    from live_snapshot import SNAPSHOT_DATE, STANDINGS  # noqa
    issues, notes = [], []
    cur = load_current(league)
    dup = cur.duplicated(["home", "away"]).sum()
    if dup:
        issues.append(f"{dup} match(s) en double")

    ref = cur[cur.date <= SNAPSHOT_DATE]
    t = table(ref)
    for name, w, d, l, pts in STANDINGS[league]:
        c = canon(league, name)
        if c not in t.index:
            issues.append(f"{c} absent des résultats"); continue
        r = t.loc[c]
        if (r.W, r.D, r.L, r.Pts) != (w, d, l, pts):
            issues.append(f"{c}: nous {r.W}-{r.D}-{r.L} {r.Pts}pts vs officiel du {SNAPSHOT_DATE} {w}-{d}-{l} {pts}pts")

    teams = sorted(set(cur.home) | set(cur.away))
    pst = postponed(league)
    last = int(cur["round"].max())
    for rnd in range(1, last):  # la dernière journée peut être en cours
        g = cur[cur["round"] == rnd]
        cnt = pd.concat([g.home, g.away]).value_counts()
        twice = sorted(cnt[cnt > 1].index)
        missing = [x for x in teams if x not in cnt.index]
        if twice:
            issues.append(f"journée {rnd} : {', '.join(twice)} y joue(nt) deux fois")
        if missing:
            known = [f"{h}-{a}" for h, a in pst if h in missing and a in missing]
            notes.append(f"journée {rnd} : pas de résultat pour {', '.join(missing)}"
                         + (f" (reporté selon l'API : {', '.join(known)})" if known else " (match reporté ou manquant ?)"))

    of = load_openfootball(league, CURRENT)
    if len(of):
        m = of.merge(cur, on=["home", "away"], how="left", suffixes=("_of", "_v"))
        bad = m[(m.hg_of != m.hg_v) | (m.ag_of != m.ag_v)]
        for r in bad.itertuples():
            issues.append(f"écart openfootball {r.home}-{r.away}: {r.hg_of}-{r.ag_of} vs {r.hg_v}-{r.ag_v}")
    return issues, notes


if __name__ == "__main__":
    for lg in LEAGUES:
        df = load_league(lg)
        cur = df[df.season == CURRENT]
        print(f"{lg}: {len(df)} matchs ({len(cur)} cette saison), du {df.date.min().date()} au {df.date.max().date()}")
        iss, notes = verify(lg)
        print("   OK" if not iss else "\n".join("   ! " + i for i in iss))
        for n in notes:
            print("   i " + n)
    print("Équipes historiques sans alias :", sorted(UNKNOWN))
