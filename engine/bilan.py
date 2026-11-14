"""Suivi des performances : journal des cotes, journal des recos et bilan.

data/journal.csv (versionné) : une ligne par relevé de cotes d'un match à venir
  - type « releve »  : à chaque mise à jour où les cotes du match ont été (re)lues ;
  - type « cloture » : une seule fois, moins de 30 min avant le coup d'envoi (cote de clôture).
  Pour 1, N, 2, +2,5, -2,5 : proba modèle, proba marché (cote moyenne, marge retirée), proba finale,
  cote moyenne, meilleure cote et cote de ton bookmaker (config.BOOKMAKER) quand l'API la fournit.

data/recos.csv (versionné) : chaque reco au moment où elle apparaît (une par type, par match et par jour ;
  on garde la première). Une ligne par sélection (un combiné a 2 ou 3 lignes avec le même reco_id).

data/paris.csv (recalculé) : tous les paris suivis, réglés ou en attente, série par série.

Cote prise : celle de ton bookmaker si l'API la donne pour ce match, sinon la cote moyenne.
CLV = cote prise / cote de clôture du même type - 1 (ton bookmaker contre ton bookmaker, moyenne contre moyenne).
Format CSV : séparateur « ; » et virgule décimale, pour Excel.
"""
import csv
import math
import os
from datetime import datetime, timezone

import config as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("CJ_DATA_DIR", os.path.join(ROOT, "data"))
JOURNAL = os.path.join(DATA_DIR, "journal.csv")
RECOS = os.path.join(DATA_DIR, "recos.csv")
PARIS = os.path.join(DATA_DIR, "paris.csv")
MARKETS = ["1", "N", "2", "plus25", "moins25"]
LABEL = {"1": "1", "N": "N", "2": "2", "plus25": "+2,5 buts", "moins25": "−2,5 buts"}
KEY = {"1": "h", "N": "d", "2": "a", "plus25": "o25", "moins25": "u25"}
FROM_KEY = {v: k for k, v in KEY.items()}
COLS = (["releve_utc", "type", "ligue", "match_id", "coup_envoi_utc", "domicile", "exterieur"]
        + [f"{pre}_{k}" for pre in ("p_modele", "p_marche", "p_finale", "moy", "max", "bk") for k in MARKETS]
        + ["bk_nom", "nb_bookmakers", "cotes_api_maj"])
RECO_COLS = ["reco_id", "horodatage_utc", "jour", "type", "jambe", "ligue", "match_id", "coup_envoi_utc",
             "domicile", "exterieur", "pari", "p_modele", "p_marche", "p_finale", "meilleure_cote",
             "bookmaker_meilleure", "cote_moyenne", "cote_bk", "cote_prise", "base_prise", "cote_min",
             "valeur", "confiance"]
SERIES = [("secu", "Pari sécu"), ("valeur", "Pari valeur"), ("combine", "Combiné du jour"),
          ("grosse", "Grosse cote"), ("toutes_modele", "Toutes les valeurs, modèle seul"),
          ("toutes_finale", "Toutes les valeurs, proba finale")]


# --------------------------------------------------------------------------- lecture / écriture
def _fmt(v):
    if v is None or v == "":
        return ""
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",")
    return str(v)


def _num(s):
    s = (s or "").strip() if isinstance(s, str) else s
    if s in ("", None):
        return None
    return float(str(s).replace(",", "."))


def _read(path, numeric_prefixes):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    for r in rows:
        for c in list(r):
            if c.startswith(numeric_prefixes):
                r[c] = _num(r[c])
    return rows


def read_journal(path=None):
    rows = _read(path or JOURNAL, ("p_", "moy_", "max_", "bk_1", "bk_N", "bk_2", "bk_plus", "bk_moins"))
    for r in rows:  # ancien format (p_1 = modèle) : on le relit comme p_modele_1
        for k in MARKETS:
            if r.get(f"p_modele_{k}") is None and r.get(f"p_{k}") is not None:
                r[f"p_modele_{k}"] = r[f"p_{k}"]
    return rows


def read_recos(path=None):
    return _read(path or RECOS, ("p_", "meilleure_cote", "cote_", "valeur"))


def _write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([_fmt(r.get(c)) for c in cols])
    os.replace(tmp, path)


# --------------------------------------------------------------------------- journal des cotes
def market_probs(summary):
    """Probas marché {h,d,a,o25,u25} tirées de la cote moyenne, marge retirée."""
    if not summary:
        return {}
    return dict(summary.get("implied") or {}, **(summary.get("implied_ou") or {}))


def journal_row(fx, kind, summary, stamp):
    if not summary or not summary.get("mean"):
        return None
    pm = fx["pm"]
    pk = market_probs(summary)
    pref = summary.get("pref") or {}
    row = dict(releve_utc=stamp, type=kind, ligue=fx["league"], match_id=str(fx["api_id"]),
               coup_envoi_utc=fx["kickoff"], domicile=fx["home"], exterieur=fx["away"],
               bk_nom=pref.get("name") or "", nb_bookmakers=summary.get("n"), cotes_api_maj=summary.get("update") or "")
    for k in MARKETS:
        sk = KEY[k]
        row[f"p_modele_{k}"] = float(pm[sk])
        row[f"p_marche_{k}"] = pk.get(sk)
        row[f"p_finale_{k}"] = C.W_MODELE * float(pm[sk]) + (1 - C.W_MODELE) * pk[sk] if sk in pk else float(pm[sk])
        row[f"moy_{k}"] = summary["mean"].get(sk)
        row[f"max_{k}"] = (summary["best"].get(sk) or [None])[0]
        row[f"bk_{k}"] = (pref.get("odds") or {}).get(sk)
    return row


def record(fixtures):
    """Ajoute au journal les relevés (et cotes de clôture) des matchs exportés. Renvoie le nombre d'ajouts."""
    rows = read_journal()
    keys = {(r["match_id"], r["type"], r["releve_utc"] if r["type"] == "releve" else "") for r in rows}
    new = []
    for fx in fixtures:
        if not fx.get("api_id"):
            continue
        for kind, summary, stamp in (("releve", fx.get("odds"), (fx.get("checked") or {}).get("odds")),
                                     ("cloture", fx.get("closing"), (fx.get("closing") or {}).get("fetched"))):
            if not summary or not stamp:
                continue
            key = (str(fx["api_id"]), kind, stamp if kind == "releve" else "")
            if key in keys:
                continue
            row = journal_row(fx, kind, summary, stamp)
            if row:
                keys.add(key)
                new.append(row)
    if new:
        _write_csv(JOURNAL, COLS, rows + new)
    return len(new)


# --------------------------------------------------------------------------- journal des recos
def _paris_day(now):
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d")
    except Exception:
        return now.strftime("%Y-%m-%d")


def record_recos(items, now=None):
    """Enregistre les recos affichées. Une par type, par match et par jour : on garde la première."""
    now = now or datetime.now(timezone.utc)
    rows = read_recos()
    known = {r["reco_id"] for r in rows}
    day = _paris_day(now)
    new = []
    for it in items:
        ids = "+".join(str(l["api_id"]) for l in it["legs"])
        rid = f"{day}-{it['type']}-{ids}"
        if rid in known or not all(l["api_id"] for l in it["legs"]):
            continue
        known.add(rid)
        for j, l in enumerate(it["legs"], 1):
            # exactement la cote de référence de la reco (même base pour toutes les sélections d'un combiné)
            if l.get("ref"):
                prise, base = l["ref"], l["ref_src"]
            else:  # ancien format
                prise, base = (l["pref"], "bookmaker") if l.get("pref") else (l["mean"], "moyenne")
            new.append(dict(reco_id=rid, horodatage_utc=now.isoformat(timespec="seconds"), jour=day, type=it["type"],
                            jambe=j, ligue=l["league"], match_id=str(l["api_id"]), coup_envoi_utc=l["kickoff"],
                            domicile=l["home"], exterieur=l["away"], pari=FROM_KEY[l["k"]], p_modele=l["pm"],
                            p_marche=l["pk"], p_finale=l["p"], meilleure_cote=l["best"], bookmaker_meilleure=l["best_bk"],
                            cote_moyenne=l["mean"], cote_bk=l.get("pref"), cote_prise=prise, base_prise=base,
                            cote_min=it["cote_min"], valeur=it["valeur"], confiance=it["confiance"]))
    if new:
        _write_csv(RECOS, RECO_COLS, rows + new)
    return len({r["reco_id"] for r in new})


# --------------------------------------------------------------------------- bilan
def _won(k, hg, ag):
    return {"1": hg > ag, "N": hg == ag, "2": hg < ag, "plus25": hg + ag >= 3, "moins25": hg + ag <= 2}[k]


def _prise(row, k):
    """Cote prise et sa base : ton bookmaker s'il est là, sinon la moyenne."""
    if row.get(f"bk_{k}"):
        return row[f"bk_{k}"], "bookmaker"
    return row.get(f"moy_{k}"), "moyenne"


def _clv(taken_bk, taken_mean, close, k):
    """CLV d'une sélection, en comparant deux cotes du même type."""
    if not close:
        return None, None
    if taken_bk and close.get(f"bk_{k}"):
        return taken_bk, close[f"bk_{k}"]
    if taken_mean and close.get(f"moy_{k}"):
        return taken_mean, close[f"moy_{k}"]
    return None, None


def _ll(p):
    return -math.log(max(p, 1e-12))


def compute(journal, results, reco_rows=None):
    """journal, reco_rows : lignes lues ; results : {(ligue, domicile, exterieur): (buts dom, buts ext)}."""
    reco_rows = reco_rows or []
    by_match = {}
    for r in journal:
        by_match.setdefault(r["match_id"], []).append(r)
    closes = {mid: next((r for r in rows if r["type"] == "cloture"), None) for mid, rows in by_match.items()}
    series = {s: [] for s, _ in SERIES}
    ll = dict(n=0, model=0.0, final=0.0, book=0.0, n_close=0, model_close=0.0, final_close=0.0, close=0.0)
    wdata = []

    for mid, rows in by_match.items():
        ko = rows[0]["coup_envoi_utc"]
        pre = sorted([r for r in rows if r["type"] == "releve" and r["releve_utc"][:19] < ko[:19]],
                     key=lambda r: r["releve_utc"])
        if not pre:
            continue
        snap, close = pre[-1], closes[mid]
        res = results.get((snap["ligue"], snap["domicile"], snap["exterieur"]))
        if res:
            y = ["1", "N", "2"][0 if res[0] > res[1] else (1 if res[0] == res[1] else 2)]
            if snap.get(f"p_marche_{y}") is not None:
                ll["n"] += 1
                ll["model"] += _ll(snap[f"p_modele_{y}"])
                ll["final"] += _ll(snap[f"p_finale_{y}"])
                ll["book"] += _ll(snap[f"p_marche_{y}"])
                if close and close.get(f"p_marche_{y}") is not None:
                    ll["n_close"] += 1
                    ll["model_close"] += _ll(snap[f"p_modele_{y}"])
                    ll["final_close"] += _ll(snap[f"p_finale_{y}"])
                    ll["close"] += _ll(close[f"p_marche_{y}"])
                    wdata.append((y, [snap[f"p_modele_{k}"] for k in ("1", "N", "2")],
                                  [snap[f"p_marche_{k}"] for k in ("1", "N", "2")]))

        for serie, pcol in (("toutes_modele", "p_modele"), ("toutes_finale", "p_finale")):
            for k in MARKETS:
                p = snap.get(f"{pcol}_{k}")
                o, base = _prise(snap, k)
                if not p or not o or p * o < C.VALEUR_MIN_BILAN:
                    continue
                t, c = _clv(snap.get(f"bk_{k}"), snap.get(f"moy_{k}"), close, k)
                series[serie].append(_bet(serie, snap, k, p, o, base, t, c, res, ko))

    # recos : une entrée par reco_id (1 à 3 sélections)
    groups = {}
    for r in reco_rows:
        groups.setdefault(r["reco_id"], []).append(r)
    for rid, legs in groups.items():
        legs.sort(key=lambda r: int(r["jambe"]))
        prise, chance, t_all, c_all, settled, won = 1.0, 1.0, 1.0, 1.0, True, True
        clv_ok = True
        scores = []
        for l in legs:
            prise *= l["cote_prise"]
            chance *= l["p_finale"]
            close = closes.get(l["match_id"])
            t, c = _clv(l.get("cote_bk") if l["base_prise"] == "bookmaker" else None, l["cote_moyenne"], close, l["pari"])
            if t and c:
                t_all *= t; c_all *= c
            else:
                clv_ok = False
            res = results.get((l["ligue"], l["domicile"], l["exterieur"]))
            if res is None:
                settled = False
            else:
                won = won and _won(l["pari"], *res)
                scores.append(f"{res[0]}-{res[1]}")
        first = legs[0]
        bet = dict(serie=first["type"], reco_id=rid, coup_envoi=min(l["coup_envoi_utc"] for l in legs),
                   ligue=first["ligue"] if len(legs) == 1 else "mix",
                   match=" + ".join(f"{l['domicile']} – {l['exterieur']}" for l in legs),
                   pari=" + ".join(LABEL[l["pari"]] for l in legs), proba=chance, cote=prise,
                   base="+".join(sorted({l["base_prise"] for l in legs})), cloture=c_all if clv_ok else None,
                   clv=(t_all / c_all - 1) if clv_ok else None, score=" ; ".join(scores) if settled else None,
                   resultat=None, gain=None, jambes=len(legs), confiance=first["confiance"])
        if settled:
            bet["resultat"] = "gagné" if won else "perdu"
            bet["gain"] = (prise - 1) if won else -1.0
        series[first["type"]].append(bet)

    out = {"series": {}, "labels": dict(SERIES), "journal_rows": len(journal), "matches": len(by_match),
           "recos": len(groups), "echantillon_min": C.ECHANTILLON_MIN}
    for s, bets in series.items():
        bets.sort(key=lambda b: (b["coup_envoi"], b["match"], b["pari"]))
        out["series"][s] = dict(summary=_summary(bets), bets=bets)
    n, nc = ll["n"], ll["n_close"]
    out["logloss"] = dict(n=n, model=ll["model"] / n if n else None, final=ll["final"] / n if n else None,
                          book=ll["book"] / n if n else None, n_close=nc,
                          model_close=ll["model_close"] / nc if nc else None,
                          final_close=ll["final_close"] / nc if nc else None, close=ll["close"] / nc if nc else None)
    out["w"] = best_w(wdata)
    return out


def best_w(wdata):
    """W qui minimise le log loss du mélange sur le 1N2, à partir de W_MIN_MATCHS matchs avec clôture."""
    res = dict(n=len(wdata), needed=C.W_MIN_MATCHS, current=C.W_MODELE, best=None, ll_best=None, ll_current=None)
    if len(wdata) < C.W_MIN_MATCHS:
        return res
    idx = {"1": 0, "N": 1, "2": 2}

    def loss(w):
        return sum(_ll(w * pm[idx[y]] + (1 - w) * pk[idx[y]]) for y, pm, pk in wdata) / len(wdata)
    grid = [i / 20 for i in range(21)]
    w = min(grid, key=loss)
    res.update(best=w, ll_best=loss(w), ll_current=loss(C.W_MODELE))
    return res


def _bet(serie, snap, k, p, o, base, t, c, res, ko):
    bet = dict(serie=serie, coup_envoi=ko, ligue=snap["ligue"], match=f"{snap['domicile']} – {snap['exterieur']}",
               pari=LABEL[k], proba=p, cote=o, base=base, cloture=c, clv=(t / c - 1) if t and c else None,
               score=f"{res[0]}-{res[1]}" if res else None, resultat=None, gain=None, jambes=1)
    if res:
        w = _won(k, *res)
        bet["resultat"] = "gagné" if w else "perdu"
        bet["gain"] = (o - 1) if w else -1.0
    return bet


def _summary(bets):
    done = [b for b in bets if b["resultat"]]
    clv = [b["clv"] for b in bets if b["clv"] is not None]
    profit = sum(b["gain"] for b in done)
    won = sum(b["resultat"] == "gagné" for b in done)
    return dict(n=len(bets), settled=len(done), pending=len(bets) - len(done), won=won,
                hit=won / len(done) if done else None, stake=float(len(done)), profit=profit,
                roi=profit / len(done) if done else None,
                avg_odds=sum(b["cote"] for b in done) / len(done) if done else None,
                clv_n=len(clv), clv_mean=sum(clv) / len(clv) if clv else None,
                clv_pos=sum(c > 0 for c in clv) / len(clv) if clv else None,
                small=len(done) < C.ECHANTILLON_MIN)


def write_paris(bilan):
    """data/paris.csv : tous les paris suivis, série par série."""
    cols = ["serie", "coup_envoi", "ligue", "match", "pari", "proba", "cote", "base", "cloture", "clv",
            "score", "resultat", "gain"]
    rows = [dict(b, serie=bilan["labels"][s]) for s, v in bilan["series"].items() for b in v["bets"]]
    _write_csv(PARIS, cols, rows)
