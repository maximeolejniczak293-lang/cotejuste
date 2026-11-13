"""Suivi des performances : journal des cotes et bilan des paris « valeur ».

data/journal.csv (versionné) : une ligne par relevé de cotes d'un match à venir
  - type « releve »  : à chaque mise à jour où les cotes du match ont été (re)lues ;
  - type « cloture » : une seule fois, moins de 30 min avant le coup d'envoi (cote de clôture).
  Colonnes : probabilités du modèle, cote moyenne et meilleure cote des bookmakers pour 1, N, 2, +2,5, -2,5.

data/paris.csv (recalculé à chaque fois) : les paris « valeur » (cote × proba >= 1,05) pris au dernier
relevé avant le match, avec la cote moyenne : résultat, gain pour 1 € misé, CLV.

Format : séparateur « ; » et virgule décimale, pour s'ouvrir directement dans Excel.
"""
import csv
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("CJ_DATA_DIR", os.path.join(ROOT, "data"))
JOURNAL = os.path.join(DATA_DIR, "journal.csv")
PARIS = os.path.join(DATA_DIR, "paris.csv")
VALUE_MIN = 1.05
MARKETS = ["1", "N", "2", "plus25", "moins25"]
LABEL = {"1": "1", "N": "N", "2": "2", "plus25": "+2,5 buts", "moins25": "-2,5 buts"}
SUMMARY_KEY = {"1": "h", "N": "d", "2": "a", "plus25": "o25", "moins25": "u25"}
COLS = (["releve_utc", "type", "ligue", "match_id", "coup_envoi_utc", "domicile", "exterieur"]
        + [f"p_{k}" for k in MARKETS] + [f"moy_{k}" for k in MARKETS] + [f"max_{k}" for k in MARKETS]
        + ["nb_bookmakers", "cotes_api_maj"])
NUM = {c for c in COLS if c.startswith(("p_", "moy_", "max_"))}


# --------------------------------------------------------------------------- lecture / écriture
def _fmt(v):
    if v is None or v == "":
        return ""
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",")
    return str(v)


def _num(s):
    s = (s or "").strip()
    return float(s.replace(",", ".")) if s else None


def read_journal(path=None) -> list[dict]:
    path = path or JOURNAL
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    for r in rows:
        for c in NUM:
            r[c] = _num(r.get(c))
    return rows


def _write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([_fmt(r.get(c)) for c in cols])
    os.replace(tmp, path)


def journal_row(fx: dict, kind: str, summary: dict, stamp: str) -> dict | None:
    """fx : match exporté par export.py ; summary : résumé des cotes (api_football.summarize_odds)."""
    if not summary or not summary.get("mean"):
        return None
    p = {"1": fx["p"]["h"], "N": fx["p"]["d"], "2": fx["p"]["a"],
         "plus25": fx["markets"]["over25"], "moins25": 1 - fx["markets"]["over25"]}
    row = dict(releve_utc=stamp, type=kind, ligue=fx["league"], match_id=str(fx["api_id"]),
               coup_envoi_utc=fx["kickoff"], domicile=fx["home"], exterieur=fx["away"],
               nb_bookmakers=summary.get("n"), cotes_api_maj=summary.get("update") or "")
    for k in MARKETS:
        sk = SUMMARY_KEY[k]
        row[f"p_{k}"] = float(p[k])
        row[f"moy_{k}"] = summary["mean"].get(sk)
        row[f"max_{k}"] = (summary["best"].get(sk) or [None])[0]
    return row


def record(fixtures: list[dict]) -> int:
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


# --------------------------------------------------------------------------- bilan
def _won(k, hg, ag):
    return {"1": hg > ag, "N": hg == ag, "2": hg < ag, "plus25": hg + ag >= 3, "moins25": hg + ag <= 2}[k]


def _implied(row, prefix):
    o = [row.get(f"{prefix}_{k}") for k in ("1", "N", "2")]
    if not all(o):
        return None
    inv = [1 / x for x in o]
    s = sum(inv)
    return [x / s for x in inv]


def compute(journal: list[dict], results: dict) -> dict:
    """journal : lignes de read_journal ; results : {(ligue, domicile, exterieur): (buts dom, buts ext)}."""
    by_match = {}
    for r in journal:
        by_match.setdefault(r["match_id"], []).append(r)

    variants = {"moy": [], "max": []}
    ll = dict(n=0, model=0.0, book=0.0, n_close=0, model_close=0.0, close=0.0)
    for mid, rows in by_match.items():
        ko = rows[0]["coup_envoi_utc"]
        pre = sorted([r for r in rows if r["type"] == "releve" and r["releve_utc"][:19] < ko[:19]],
                     key=lambda r: r["releve_utc"])
        if not pre:
            continue
        snap = pre[-1]                                  # dernier relevé avant le match
        close = next((r for r in rows if r["type"] == "cloture"), None)
        res = results.get((snap["ligue"], snap["domicile"], snap["exterieur"]))

        if res:  # log loss 1N2 : modèle contre bookmakers (marge retirée)
            y = 0 if res[0] > res[1] else (1 if res[0] == res[1] else 2)
            pm = [snap["p_1"], snap["p_N"], snap["p_2"]]
            pb = _implied(snap, "moy")
            if pb:
                ll["n"] += 1
                ll["model"] -= math.log(max(pm[y], 1e-12))
                ll["book"] -= math.log(max(pb[y], 1e-12))
            pc = _implied(close, "moy") if close else None
            if pc:
                ll["n_close"] += 1
                ll["model_close"] -= math.log(max(pm[y], 1e-12))
                ll["close"] -= math.log(max(pc[y], 1e-12))

        for var in variants:
            for k in MARKETS:
                p, o = snap[f"p_{k}"], snap[f"{var}_{k}"]
                if not p or not o or p * o < VALUE_MIN:
                    continue
                c = close.get(f"{var}_{k}") if close else None
                bet = dict(match_id=mid, ligue=snap["ligue"], coup_envoi=ko, releve=snap["releve_utc"],
                           domicile=snap["domicile"], exterieur=snap["exterieur"], pari=k, label=LABEL[k],
                           proba=p, cote=o, valeur=p * o, cloture=c, clv=(o / c - 1) if c else None,
                           score=f"{res[0]}-{res[1]}" if res else None, resultat=None, gain=None)
                if res:
                    w = _won(k, *res)
                    bet["resultat"] = "gagné" if w else "perdu"
                    bet["gain"] = (o - 1) if w else -1.0
                variants[var].append(bet)

    out = {"variants": {}, "journal_rows": len(journal), "matches": len(by_match)}
    for var, bets in variants.items():
        bets.sort(key=lambda b: (b["coup_envoi"], b["domicile"], MARKETS.index(b["pari"])))
        out["variants"][var] = dict(summary=_summary(bets), by_market=_groups(bets, "pari"),
                                    by_league=_groups(bets, "ligue"), bets=bets)
    out["logloss"] = {
        "n": ll["n"], "model": ll["model"] / ll["n"] if ll["n"] else None, "book": ll["book"] / ll["n"] if ll["n"] else None,
        "n_close": ll["n_close"], "model_close": ll["model_close"] / ll["n_close"] if ll["n_close"] else None,
        "close": ll["close"] / ll["n_close"] if ll["n_close"] else None}
    return out


def _summary(bets):
    done = [b for b in bets if b["resultat"]]
    clv = [b["clv"] for b in bets if b["clv"] is not None]
    profit = sum(b["gain"] for b in done)
    return dict(n=len(bets), settled=len(done), pending=len(bets) - len(done),
                won=sum(b["resultat"] == "gagné" for b in done), stake=float(len(done)), profit=profit,
                roi=profit / len(done) if done else None, avg_odds=sum(b["cote"] for b in done) / len(done) if done else None,
                clv_n=len(clv), clv_mean=sum(clv) / len(clv) if clv else None,
                clv_pos=sum(c > 0 for c in clv) / len(clv) if clv else None)


def _groups(bets, key):
    keys = MARKETS if key == "pari" else sorted({b[key] for b in bets})
    out = []
    for k in keys:
        g = [b for b in bets if b[key] == k]
        if g:
            out.append(dict(key=k, label=LABEL.get(k, k), **_summary(g)))
    return out


def write_paris(bilan: dict):
    """data/paris.csv : les paris « valeur » avec la cote moyenne (la référence du bilan)."""
    cols = ["coup_envoi", "ligue", "domicile", "exterieur", "pari", "proba", "cote", "valeur", "cloture", "clv",
            "score", "resultat", "gain"]
    rows = [dict(b, pari=b["label"]) for b in bilan["variants"]["moy"]["bets"]]
    _write_csv(PARIS, cols, rows)
