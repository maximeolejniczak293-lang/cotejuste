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


def walk_forward(df, season, xi, l2):
    test = df[df.season == season].copy()
    test["week"] = test.date.dt.to_period("W-MON").dt.start_time
    rows = []
    for wk, grp in test.groupby("week"):
        teams = sorted(set(df[df.season == season].home))
        m = DixonColes(xi=xi, l2=l2).fit(df, wk, current_teams=teams)
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


if __name__ == "__main__":
    data = {lg: load_league(lg) for lg in LEAGUES}

    # 1) réglage des hyperparamètres sur la saison 2024-25 uniquement
    grid = list(itertools.product([0.0015, 0.0025, 0.004, 0.006], [1.0, 3.0, 8.0]))
    scores = {}
    for xi, l2 in grid:
        ll = []
        for lg, df in data.items():
            res = walk_forward(df, "2024-25", xi, l2)
            ll.append(evaluate(res)[0]["logloss"] * len(res))
            n = len(res)
        scores[(xi, l2)] = sum(ll)
        print(f"xi={xi:<7} l2={l2:<4} logloss total={sum(ll):.1f}")
    best = min(scores, key=scores.get)
    print("Meilleurs paramètres :", best)

    # 2) évaluation hors échantillon sur 2025-26 et 2026-27
    out = dict(params=dict(xi=best[0], l2=best[1]), leagues={}, calibration=None)
    allres = []
    for lg, df in data.items():
        out["leagues"][lg] = {}
        for season in ["2025-26", "2026-27"]:
            res = walk_forward(df, season, *best)
            res["league"] = lg; res["season"] = season
            allres.append(res)
            m, b = evaluate(res)
            out["leagues"][lg][season] = dict(model=m, baseline=b)
            print(lg, season, {k: round(v, 4) for k, v in m.items()}, "| naïf:", round(b["logloss"], 4))
    allres = pd.concat(allres)
    m, b = evaluate(allres)
    out["overall"] = dict(model=m, baseline=b)
    out["calibration"] = calibration(allres)
    # over 2.5
    o = allres.o25.to_numpy(); y = allres.y25.to_numpy()
    out["over25"] = dict(brier=float(np.mean((o - y) ** 2)), base_brier=float(np.mean((y.mean() - y) ** 2)))
    print("GLOBAL", m, "\nNAÏF", b)
    json.dump(out, open(os.path.join(os.path.dirname(__file__), "..", "out", "backtest.json"), "w"), indent=1, default=float)
