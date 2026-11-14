"""Backtest walk-forward : on ré-entraîne le modèle chaque semaine avec uniquement
les matchs déjà joués, puis on prédit les matchs de la semaine suivante."""
import itertools
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from data import load_league  # noqa: E402
from model import DixonColes  # noqa: E402
from names import LEAGUES  # noqa: E402


def walk_forward(df, season, xi, l2, a=0.0):
    test = df[df.season == season].copy()
    test["week"] = test.date.dt.to_period("W-MON").dt.start_time
    rows = []
    for wk, grp in test.groupby("week"):
        teams = sorted(set(df[df.season == season].home))
        m = DixonColes(xi=xi, l2=l2, a=a).fit(df, wk, current_teams=teams)
        hist = df[(df.date < wk)].tail(1500)
        base = np.array([(hist.hg > hist.ag).mean(), (hist.hg == hist.ag).mean(), (hist.hg < hist.ag).mean()])
        for r in grp.itertuples():
            p = m.predict(r.home, r.away)
            y = 0 if r.hg > r.ag else (1 if r.hg == r.ag else 2)
            rows.append(dict(date=r.date, home=r.home, away=r.away, y=y,
                             ph=p["p_home"], pd=p["p_draw"], pa=p["p_away"],
                             bh=base[0], bd=base[1], ba=base[2],
                             o25=p["over25"], y25=int(r.hg + r.ag >= 3)))
    return pd.DataFrame(rows)


def metrics(res, prefix=""):
    P = res[[prefix + c for c in (["ph", "pd", "pa"] if not prefix else ["h", "d", "a"])]].to_numpy() \
        if prefix else res[["ph", "pd", "pa"]].to_numpy()
    return _metrics(P, res.y.to_numpy())


def _metrics(P, y):
    n = len(y)
    Y = np.zeros_like(P); Y[np.arange(n), y] = 1
    logloss = -np.mean(np.log(np.clip(P[np.arange(n), y], 1e-12, None)))
    brier = np.mean(np.sum((P - Y) ** 2, axis=1))
    cp, cy = np.cumsum(P, 1)[:, :2], np.cumsum(Y, 1)[:, :2]
    rps = np.mean(np.sum((cp - cy) ** 2, axis=1) / 2)
    acc = np.mean(P.argmax(1) == y)
    return dict(n=n, logloss=logloss, brier=brier, rps=rps, accuracy=acc)


def evaluate(res):
    model = _metrics(res[["ph", "pd", "pa"]].to_numpy(), res.y.to_numpy())
    base = _metrics(res[["bh", "bd", "ba"]].to_numpy(), res.y.to_numpy())
    return model, base


def calibration(res, bins=10):
    p = np.concatenate([res.ph, res.pd, res.pa])
    o = np.concatenate([(res.y == 0), (res.y == 1), (res.y == 2)]).astype(float)
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mk = (p >= lo) & (p < hi)
        if mk.sum() >= 15:
            out.append(dict(lo=lo, hi=hi, n=int(mk.sum()), pred=float(p[mk].mean()), obs=float(o[mk].mean())))
    return out


def out_of_sample(data, xi, l2, a):
    """Évaluation hors échantillon sur 2025-26 et 2026-27."""
    leagues, allres = {}, []
    for lg, df in data.items():
        leagues[lg] = {}
        for season in ["2025-26", "2026-27"]:
            res = walk_forward(df, season, xi, l2, a)
            res["league"] = lg; res["season"] = season
            allres.append(res)
            m, b = evaluate(res)
            leagues[lg][season] = dict(model=m, baseline=b)
    allres = pd.concat(allres)
    m, b = evaluate(allres)
    o = allres.o25.to_numpy(); y = allres.y25.to_numpy()
    return dict(params=dict(xi=xi, l2=l2, a=a), leagues=leagues, overall=dict(model=m, baseline=b),
                calibration=calibration(allres),
                over25=dict(brier=float(np.mean((o - y) ** 2)), base_brier=float(np.mean((y.mean() - y) ** 2))))


def xg_coverage(data):
    """Part des matchs avec xG, par championnat et saison (pour l'afficher honnêtement)."""
    cov = {}
    for lg, df in data.items():
        cov[lg] = {s: dict(n=int(len(g)), xg=int(g.xh.notna().sum())) for s, g in df.groupby("season")}
    return cov


if __name__ == "__main__":
    data = {lg: load_league(lg) for lg in LEAGUES}

    # 1) réglage sur la saison 2024-25 uniquement : xi, l2 et a (poids des xG)
    A_GRID = [0.0, 0.3, 0.5, 0.7, 1.0]
    grid = list(itertools.product([0.0015, 0.0025, 0.004, 0.006], [1.0, 3.0, 8.0], A_GRID))
    scores = {}
    for xi, l2, a in grid:
        tot, n = 0.0, 0
        for lg, df in data.items():
            res = walk_forward(df, "2024-25", xi, l2, a)
            tot += evaluate(res)[0]["logloss"] * len(res); n += len(res)
        scores[(xi, l2, a)] = tot / n
        print(f"xi={xi:<7} l2={l2:<4} a={a:<4} log loss 2024-25 = {tot / n:.4f}", flush=True)
    old_p = min((k for k in scores if k[2] == 0.0), key=scores.get)   # modèle actuel : buts seuls
    new_p = min(scores, key=scores.get)                                 # meilleur avec xG (a libre)
    best_by_a = {a: min((k for k in scores if k[2] == a), key=scores.get) for a in A_GRID}
    print("Ancien (buts seuls) :", old_p, "| meilleur avec xG :", new_p)

    # 2) hors échantillon (2025-26 et 2026-27) : ancien contre nouveau, côte à côte
    old = out_of_sample(data, *old_p)
    new = out_of_sample(data, *new_p) if new_p != old_p else old
    adopted = new["overall"]["model"]["logloss"] < old["overall"]["model"]["logloss"] and new_p[2] > 0
    chosen = new if adopted else old

    def brief(r):
        return dict(params=r["params"], logloss=r["overall"]["model"]["logloss"], rps=r["overall"]["model"]["rps"],
                    accuracy=r["overall"]["model"]["accuracy"], n=r["overall"]["model"]["n"],
                    over25_brier=r["over25"]["brier"], over25_base=r["over25"]["base_brier"],
                    leagues={lg: {s: v["model"]["logloss"] for s, v in d.items()} for lg, d in r["leagues"].items()})
    out = dict(chosen)
    out["comparison"] = dict(old=brief(old), new=brief(new), adopted=adopted,
                             tuning_2024_25={str(a): dict(xi=k[0], l2=k[1], logloss=scores[k]) for a, k in best_by_a.items()},
                             xg_coverage=xg_coverage(data))
    for name, r in (("ANCIEN (buts seuls)", old), ("NOUVEAU (xG)", new)):
        m = r["overall"]["model"]
        print(f"{name:<22} {r['params']} log loss {m['logloss']:.4f} RPS {m['rps']:.4f} bon favori {m['accuracy']:.3f} "
              f"Brier +2,5 {r['over25']['brier']:.4f} (moyenne {r['over25']['base_brier']:.4f})")
    print("xG ADOPTÉS" if adopted else "xG NON ADOPTÉS : on garde le modèle buts seuls")
    json.dump(out, open(os.path.join(os.path.dirname(__file__), "..", "out", "backtest.json"), "w", encoding="utf-8"),
              indent=1, default=float)
