"""Modèle de Dixon-Coles (Poisson bivarié corrigé) avec pondération temporelle.

log(buts attendus domicile)  = mu + avantage_domicile + attaque[dom] - defense[ext]
log(buts attendus extérieur) = mu + attaque[ext] - defense[dom]

- Les matchs récents pèsent plus : poids = exp(-xi * jours écoulés).
- Une pénalité L2 tire les équipes vers la moyenne (ou vers un niveau "promu"
  pour les équipes qui viennent de monter), ce qui stabilise les estimations
  quand il y a peu de matchs.
- Le paramètre rho de Dixon-Coles corrige la fréquence des petits scores
  (0-0, 1-0, 0-1, 1-1), que le Poisson simple estime mal.
- xG : attaque et défense sont estimées sur un mélange
  buts_utilisés = a × xG + (1 − a) × buts réels (vraisemblance de Poisson sur valeurs non entières).
  Sans xG pour un match, on prend ses buts réels. rho reste estimé sur les vrais scores.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

MAX_GOALS = 10
PROMOTED_PRIOR = -0.18  # niveau a priori (attaque et défense) d'un promu, en log


@dataclass
class DixonColes:
    xi: float = 0.0025      # décroissance temporelle par jour (demi-vie ≈ 277 jours)
    l2: float = 2.0         # force de la pénalité vers le niveau a priori
    a: float = 0.0          # poids des xG dans les buts utilisés (0 = buts réels seuls)
    teams: list = field(default_factory=list)
    params: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ fit
    def fit(self, df: pd.DataFrame, ref_date, current_teams=None):
        ref_date = pd.Timestamp(ref_date)
        df = df[df.date < ref_date]
        days = (ref_date - df.date).dt.days.to_numpy()
        w = np.exp(-self.xi * days)
        keep = w > 1e-3
        df, w = df[keep], w[keep]

        teams = sorted(set(df.home) | set(df.away) | set(current_teams or []))
        idx = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        hi = df.home.map(idx).to_numpy()
        ai = df.away.map(idx).to_numpy()
        hg = df.hg.to_numpy(float)          # vrais scores (pour rho)
        ag = df.ag.to_numpy(float)
        uh, ua = hg, ag                     # buts utilisés pour attaque / défense
        if self.a > 0 and "xh" in df and "xa" in df:
            xh = df.xh.to_numpy(float)
            xa = df.xa.to_numpy(float)
            uh = np.where(np.isnan(xh), hg, self.a * xh + (1 - self.a) * hg)
            ua = np.where(np.isnan(xa), ag, self.a * xa + (1 - self.a) * ag)

        # a priori : 0 pour une équipe établie, PROMOTED_PRIOR pour un promu
        prior = np.zeros(n)
        last_season = df.season.max() if len(df) else None
        if current_teams:
            prev = df[df.season != last_season] if last_season else df.iloc[0:0]
            seen_prev = set(prev.home) | set(prev.away)
            for t in current_teams:
                recent_prev = prev[(prev.home == t) | (prev.away == t)]
                if t not in seen_prev or recent_prev.date.max() < ref_date - pd.Timedelta(days=500):
                    prior[idx[t]] = PROMOTED_PRIOR

        def unpack(x):
            return x[0], x[1], x[2:2 + n], x[2 + n:]

        def nll(x):
            mu, home, att, dfn = unpack(x)
            lh = mu + home + att[hi] - dfn[ai]
            la = mu + att[ai] - dfn[hi]
            eh, ea = np.exp(lh), np.exp(la)
            ll = w * (uh * lh - eh + ua * la - ea)
            pen = 0.5 * self.l2 * (np.sum((att - prior) ** 2) + np.sum((dfn - prior) ** 2))
            f = -ll.sum() + pen
            # gradient analytique
            rh = w * (uh - eh)
            ra = w * (ua - ea)
            g_mu = -(rh.sum() + ra.sum())
            g_home = -rh.sum()
            g_att = -(np.bincount(hi, rh, n) + np.bincount(ai, ra, n)) + self.l2 * (att - prior)
            g_def = (np.bincount(ai, rh, n) + np.bincount(hi, ra, n)) + self.l2 * (dfn - prior)
            return f, np.concatenate([[g_mu, g_home], g_att, g_def])

        x0 = np.concatenate([[0.3, 0.2], prior, prior])
        res = minimize(nll, x0, jac=True, method="L-BFGS-B")
        mu, home, att, dfn = unpack(res.x)

        # rho de Dixon-Coles (estimé à paramètres de Poisson fixés)
        lam = np.exp(mu + home + att[hi] - dfn[ai])
        mua = np.exp(mu + att[ai] - dfn[hi])

        def neg_rho(r):
            t = _tau(hg, ag, lam, mua, r)
            return -np.sum(w * np.log(np.clip(t, 1e-10, None)))

        rho = minimize_scalar(neg_rho, bounds=(-0.25, 0.25), method="bounded").x

        self.teams = teams
        self.params = dict(mu=mu, home=home, rho=rho,
                           att=dict(zip(teams, att)), dfn=dict(zip(teams, dfn)),
                           n_matches=len(df), weight_sum=float(w.sum()))
        return self

    # -------------------------------------------------------------- predict
    def rates(self, home: str, away: str):
        p = self.params
        lh = np.exp(p["mu"] + p["home"] + p["att"][home] - p["dfn"][away])
        la = np.exp(p["mu"] + p["att"][away] - p["dfn"][home])
        return float(lh), float(la)

    def score_matrix(self, home: str, away: str) -> np.ndarray:
        lh, la = self.rates(home, away)
        g = np.arange(MAX_GOALS + 1)
        m = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
        r = self.params["rho"]
        m[0, 0] *= 1 - lh * la * r
        m[0, 1] *= 1 + lh * r
        m[1, 0] *= 1 + la * r
        m[1, 1] *= 1 - r
        return m / m.sum()

    def predict(self, home: str, away: str) -> dict:
        m = self.score_matrix(home, away)
        lh, la = self.rates(home, away)
        g = np.arange(MAX_GOALS + 1)
        tot = g[:, None] + g[None, :]
        ph, pd_, pa = np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()
        out = dict(
            xg_home=lh, xg_away=la,
            p_home=ph, p_draw=pd_, p_away=pa,
            over15=m[tot >= 2].sum(), over25=m[tot >= 3].sum(), over35=m[tot >= 4].sum(),
            btts=m[1:, 1:].sum(),
            home_cs=m[:, 0].sum(), away_cs=m[0, :].sum(),
        )
        flat = [(int(i), int(j), float(m[i, j])) for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1)]
        flat.sort(key=lambda x: -x[2])
        out["top_scores"] = flat[:8]
        out["matrix"] = m[:6, :6].round(5).tolist()
        return out


def _tau(x, y, lam, mu, rho):
    t = np.ones_like(lam)
    t = np.where((x == 0) & (y == 0), 1 - lam * mu * rho, t)
    t = np.where((x == 0) & (y == 1), 1 + lam * rho, t)
    t = np.where((x == 1) & (y == 0), 1 + mu * rho, t)
    t = np.where((x == 1) & (y == 1), 1 - rho, t)
    return t
