"""Entraîne le modèle final et exporte toutes les données affichées par le site (out/data.json).

Matchs à venir, par championnat, pour la prochaine journée :
  - matchs à moins de 48 h : cache/live.json, écrit par update.py depuis API-Football
    (horaire exact, cotes des bookmakers, absents, compositions) ;
  - autres matchs de la journée : calendrier openfootball (date provisoire, pas encore de cotes).
"""
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bilan  # noqa: E402
import recos  # noqa: E402
from config import W_MODELE  # noqa: E402
from data import CACHE, CURRENT, calendar, find_missing, load_current, load_league, table  # noqa: E402
from model import DixonColes  # noqa: E402
from names import LEAGUES  # noqa: E402

REF_DATE = os.environ.get("REF_DATE") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
with open(os.path.join(HERE, "..", "out", "backtest.json"), encoding="utf-8") as _f:
    BT = json.load(_f)
XI, L2 = BT["params"]["xi"], BT["params"]["l2"]
A_XG = BT["params"].get("a", 0.0)   # poids des xG retenu par le backtest (0 = buts seuls)
LIVE_PATH = os.path.join(CACHE, "live.json")
HORIZON_DAYS = 14          # on cherche la prochaine journée dans les 14 jours
CANCELLED = {"PST", "CANC", "ABD", "AWD", "WO"}


def _xg_sources() -> dict:
    """Provenance des fichiers xG (data/xg/_sources.json), pour l'afficher dans Méthode."""
    try:
        import understat
        with open(understat.SOURCES, encoding="utf-8") as f:
            return {k: dict(source=v.get("source"), matches=v.get("matches"), total=v.get("total"),
                            last_match=v.get("last_match"), complete=v.get("complete")) for k, v in json.load(f).items()}
    except Exception:  # noqa: BLE001
        return {}


def load_live() -> dict:
    try:
        with open(LIVE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"fixtures": []}


def res_letter(gf, ga):
    return "V" if gf > ga else ("N" if gf == ga else "D")


def team_matches(df, team):
    m = df[(df.home == team) | (df.away == team)].sort_values("date")
    out = []
    for r in m.itertuples():
        home = r.home == team
        gf, ga = (r.hg, r.ag) if home else (r.ag, r.hg)
        xf, xa = (r.xh, r.xa) if home else (r.xa, r.xh)
        out.append(dict(date=r.date.strftime("%Y-%m-%d"), opp=r.away if home else r.home,
                        venue="D" if home else "E", gf=int(gf), ga=int(ga), res=res_letter(gf, ga),
                        season=r.season, xgf=None if math.isnan(xf) else round(float(xf), 2),
                        xga=None if math.isnan(xa) else round(float(xa), 2)))
    return out


def xg_summary(allm):
    """xG pour / contre : moyenne de la saison en cours et des 5 derniers matchs avec xG, et buts − xG."""
    seas = [m for m in allm if m["season"] == CURRENT and m["xgf"] is not None]
    last = [m for m in allm if m["xgf"] is not None][-5:]

    def agg(ms):
        if not ms:
            return None
        n = len(ms)
        gf, ga = sum(m["gf"] for m in ms), sum(m["ga"] for m in ms)
        xf, xa = sum(m["xgf"] for m in ms), sum(m["xga"] for m in ms)
        return dict(n=n, xgf=round(xf / n, 2), xga=round(xa / n, 2), gf=round(gf / n, 2), ga=round(ga / n, 2),
                    xgf_tot=round(xf, 1), xga_tot=round(xa, 1), att_luck=round(gf - xf, 1), def_luck=round(xa - ga, 1),
                    first=ms[0]["date"], last=ms[-1]["date"])
    return dict(season=agg(seas), last5=agg(last))


def upcoming(lg, cur, live):
    """Prochaine journée : matchs API (< 48 h) + reste de la journée tiré du calendrier openfootball."""
    played = set(zip(cur.home, cur.away))
    today = datetime.now(timezone.utc).date()
    api = [f for f in live.get("fixtures", []) if f["league"] == lg
           and f["status"] not in CANCELLED and (f["home_c"], f["away_c"]) not in played]
    pairs = {(f["home_c"], f["away_c"]) for f in api}
    cal = [c for c in calendar(lg, today, HORIZON_DAYS) if (c["home"], c["away"]) not in played | pairs]
    rounds = [f.get("round_n") for f in api if f.get("round_n")] + [c["round"] for c in cal if c["round"]]
    nxt = min(rounds) if rounds else None
    out = [dict(source="api", kickoff=f["kickoff"].replace("+00:00", "Z"), time_known=True, home=f["home_c"],
                away=f["away_c"], round=f.get("round_n"), status=f["status"], venue=f.get("venue"), live=f) for f in api]
    out += [dict(source="calendrier", kickoff=c["kickoff"], time_known=c["time_known"], home=c["home"], away=c["away"],
                 round=c["round"], status="NS", venue=None, live=None) for c in cal if nxt is None or c["round"] == nxt]
    return sorted(out, key=lambda x: x["kickoff"])


def side_lists(live_fx, key):
    """Sépare absents / compositions par équipe : {'home': ..., 'away': ...} ou None si pas encore connu."""
    if not live_fx or live_fx.get(key) is None:
        return None
    return live_fx[key]


def build_league(lg, live):
    df = load_league(lg)
    cur = df[df.season == CURRENT]
    teams = sorted(set(cur.home) | set(cur.away))
    model = DixonColes(xi=XI, l2=L2, a=A_XG).fit(df, REF_DATE, current_teams=teams)
    p = model.params

    # --- classement (calculé, vérifié par data.py)
    tab = table(cur)
    standings = []
    for rank, (team, r) in enumerate(tab.iterrows(), 1):
        mine = cur[((cur.home == team) | (cur.away == team)) & cur.xh.notna()]
        xgf = float(sum(x.xh if x.home == team else x.xa for x in mine.itertuples()))
        xga = float(sum(x.xa if x.home == team else x.xh for x in mine.itertuples()))
        standings.append(dict(rank=rank, team=team, P=int(r.P), W=int(r.W), D=int(r.D), L=int(r.L),
                              GF=int(r.GF), GA=int(r.GA), GD=int(r.GD), Pts=int(r.Pts),
                              xg_n=len(mine), xGF=round(xgf, 1) if len(mine) else None,
                              xGA=round(xga, 1) if len(mine) else None, xGD=round(xgf - xga, 1) if len(mine) else None))
    rank_of = {s["team"]: s["rank"] for s in standings}

    # --- fiches équipes
    strength = {}
    for t in teams:
        gf_avg = math.exp(p["mu"] + p["home"] / 2 + p["att"][t])          # buts marqués vs équipe moyenne
        ga_avg = math.exp(p["mu"] + p["home"] / 2 - p["dfn"][t])          # buts encaissés vs équipe moyenne
        strength[t] = dict(att=math.exp(p["att"][t]), dfn=math.exp(-p["dfn"][t]),
                           xgf=gf_avg, xga=ga_avg, net=gf_avg - ga_avg)
    order = sorted(teams, key=lambda t: -strength[t]["net"])
    team_data = {}
    for t in teams:
        allm = team_matches(df, t)
        seas = [m for m in allm if m["season"] == CURRENT]
        home = [m for m in seas if m["venue"] == "D"]
        away = [m for m in seas if m["venue"] == "E"]

        def rec(ms):
            return dict(P=len(ms), W=sum(m["res"] == "V" for m in ms), D=sum(m["res"] == "N" for m in ms),
                        L=sum(m["res"] == "D" for m in ms), GF=sum(m["gf"] for m in ms), GA=sum(m["ga"] for m in ms))
        last5 = allm[-5:]
        team_data[t] = dict(
            xg=xg_summary(allm),
            rank=rank_of.get(t), power_rank=order.index(t) + 1,
            att=round(strength[t]["att"], 3), dfn=round(strength[t]["dfn"], 3),
            xgf=round(strength[t]["xgf"], 2), xga=round(strength[t]["xga"], 2),
            form=last5[::-1], form_pts=sum({"V": 3, "N": 1, "D": 0}[m["res"]] for m in last5),
            home=rec(home), away=rec(away),
            clean_sheets=sum(m["ga"] == 0 for m in seas), failed_to_score=sum(m["gf"] == 0 for m in seas),
            over25=sum(m["gf"] + m["ga"] >= 3 for m in seas), btts=sum(m["gf"] > 0 and m["ga"] > 0 for m in seas),
            n=len(seas),
        )

    # --- matchs à venir
    fixtures = []
    for u in upcoming(lg, cur, live):
        h, a = u["home"], u["away"]
        if h not in team_data or a not in team_data:
            print(f"   ! {lg} {h}-{a} ignoré : équipe hors championnat")
            continue
        pr = model.predict(h, a)
        h2h = df[((df.home == h) & (df.away == a)) | ((df.home == a) & (df.away == h))].sort_values("date")
        h2h_list = [dict(date=r.date.strftime("%Y-%m-%d"), home=r.home, away=r.away, hg=int(r.hg), ag=int(r.ag))
                    for r in h2h.itertuples()][::-1][:6]
        lv = u["live"] or {}
        odds = lv.get("odds")
        pm = {k: float(v) for k, v in {"h": pr["p_home"], "d": pr["p_draw"], "a": pr["p_away"],
                                        "o25": pr["over25"], "u25": 1 - pr["over25"]}.items()}
        pk = dict((odds or {}).get("implied") or {}, **((odds or {}).get("implied_ou") or {})) or None
        pf = {k: (W_MODELE * v + (1 - W_MODELE) * pk[k]) if pk and k in pk else v for k, v in pm.items()}
        fx = dict(
            id=f"{lg}-{h}-{a}".replace(" ", "_"), league=lg, kickoff=u["kickoff"], time_known=u["time_known"],
            source=u["source"], status=u["status"], round=u["round"], venue=u["venue"], home=h, away=a,
            api_id=lv.get("id"), closing=lv.get("closing"),
            p=dict(h=pr["p_home"], d=pr["p_draw"], a=pr["p_away"]),
            pm=pm, pk=pk, pf=pf, sans_marche=not pk,
            market=odds.get("implied") if odds else None,
            odds=odds,
            absents=side_lists(lv, "injuries"), lineups=side_lists(lv, "lineups"),
            checked=lv.get("checked"),
            xg=dict(h=pr["xg_home"], a=pr["xg_away"]),
            markets=dict(over15=pr["over15"], over25=pr["over25"], over35=pr["over35"], btts=pr["btts"],
                         home_cs=pr["home_cs"], away_cs=pr["away_cs"]),
            top_scores=pr["top_scores"], matrix=pr["matrix"], h2h=h2h_list,
        )
        fx["insights"] = insights(fx, team_data, standings)
        fixtures.append(fx)

    return dict(code=lg, **{k: v for k, v in LEAGUES[lg].items() if k != "of"},
                params=dict(home_adv=math.exp(p["home"]), rho=p["rho"], avg_goals=math.exp(p["mu"]) * 2),
                standings=standings, teams=team_data, fixtures=fixtures,
                n_matches=len(df), n_current=len(cur), last_result=cur.date.max().strftime("%Y-%m-%d"))


def insights(fx, td, standings):
    h, a = fx["home"], fx["away"]
    th, ta = td[h], td[a]
    out = []
    if fx["market"]:
        n = fx["odds"]["n"]
        for side, team in (("h", h), ("a", a)):
            mp, bp = fx["p"][side], fx["market"][side]
            if abs(mp - bp) >= 0.06:
                verbe = "croit plus" if mp > bp else "croit moins"
                out.append(f"Notre modèle {verbe} en {team} que les bookmakers : {mp * 100:.0f} % de victoire "
                           f"contre {bp * 100:.0f} % (cotes médianes de {n} bookmakers, marge retirée).")
    if fx["absents"]:
        for side, team in (("home", h), ("away", a)):
            lst = fx["absents"].get(side) or []
            sure = sum(x["type"] == "Missing Fixture" for x in lst)
            doubt = len(lst) - sure
            if len(lst) >= 3:
                out.append(f"{team} : {sure} absent{'s' if sure > 1 else ''}"
                           + (f" et {doubt} incertain{'s' if doubt > 1 else ''}" if doubt else "")
                           + ". Le modèle n'en tient pas compte : à pondérer.")
    for t, d in ((h, th), (a, ta)):
        f = "".join(m["res"] for m in d["form"][::-1])
        if d["form_pts"] >= 12:
            out.append(f"{t} est en grande forme : {f} sur ses 5 derniers matchs ({d['form_pts']} pts sur 15).")
        elif d["form_pts"] <= 3:
            out.append(f"{t} est en difficulté : {f} sur ses 5 derniers matchs ({d['form_pts']} pt{'s' if d['form_pts'] > 1 else ''} sur 15).")
    hr, ar = th["home"], ta["away"]
    if hr["P"] >= 3 and hr["L"] == 0:
        out.append(f"{h} est invaincu à domicile cette saison ({hr['W']}V {hr['D']}N).")
    if ar["P"] >= 3 and ar["W"] == 0:
        out.append(f"{a} n'a gagné aucun de ses {ar['P']} matchs à l'extérieur cette saison.")
    if hr["P"] >= 3 and hr["W"] == 0:
        out.append(f"{h} n'a gagné aucun de ses {hr['P']} matchs à domicile cette saison.")
    if ar["P"] >= 3 and ar["L"] == 0:
        out.append(f"{a} est invaincu à l'extérieur cette saison ({ar['W']}V {ar['D']}N).")
    gap = abs(th["rank"] - ta["rank"]) if th["rank"] and ta["rank"] else 0
    if gap >= 10:
        out.append(f"Gros écart au classement : {th['rank']}e contre {ta['rank']}e.")
    if fx["h2h"]:
        n = len(fx["h2h"])
        wins_h = sum((m["home"] == h and m["hg"] > m["ag"]) or (m["away"] == h and m["ag"] > m["hg"]) for m in fx["h2h"])
        wins_a = sum((m["home"] == a and m["hg"] > m["ag"]) or (m["away"] == a and m["ag"] > m["hg"]) for m in fx["h2h"])
        out.append(f"Confrontations depuis 2022 : {wins_h} victoire(s) {h}, {n - wins_h - wins_a} nul(s), {wins_a} victoire(s) {a}.")
    tot = fx["xg"]["h"] + fx["xg"]["a"]
    if tot >= 3.2:
        out.append(f"Match à buts attendu : {tot:.1f} buts en moyenne selon le modèle.")
    elif tot <= 2.1:
        out.append(f"Match fermé attendu : {tot:.1f} buts en moyenne selon le modèle.")
    return out


if __name__ == "__main__":
    live = load_live()
    data = dict(
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), ref_date=REF_DATE,
        model=dict(name="Dixon-Coles pondéré", xi=XI, l2=L2, a=A_XG, half_life_days=round(math.log(2) / XI)),
        xg=dict(a=A_XG, comparison=BT.get("comparison"), sources=_xg_sources()),
        backtest=dict(overall=BT["overall"], leagues=BT["leagues"], calibration=BT["calibration"], over25=BT["over25"]),
        live=dict(updated=live.get("generated"), window=live.get("window"), quota=live.get("quota")),
        leagues=[build_league(lg, live) for lg in LEAGUES],
    )

    # --- résultats manquants (bandeau discret sur le site)
    data["missing"] = [dict(league=m["league"], home=m["home"], away=m["away"], date=m["date"])
                       for lg in LEAGUES for m in find_missing(lg)]
    if data["missing"]:
        print(f"   ! {len(data['missing'])} résultat(s) manquant(s) signalé(s) sur le site")

    # --- recos du jour (cotes déjà en cache, aucune requête)
    all_fx = [f for L in data["leagues"] for f in L["fixtures"]]
    data["recos"] = recos.build(all_fx, {L["code"]: L["teams"] for L in data["leagues"]})
    data["recos"] = bilan.freeze_recos(data["recos"])  # figées pour la journée au premier passage (le matin)
    data["recos"]["generated"] = data["generated"]
    data["config"] = dict(w=W_MODELE, bookmaker=recos.C.BOOKMAKER)
    with_odds = [f for f in all_fx if f.get("odds")]
    with_bk = [f for f in with_odds if (f["odds"].get("pref") or {}).get("odds")]
    names = sorted({b for f in with_odds for b in f["odds"].get("bookmakers", [])})
    print(f"cotes : {len(with_odds)} match(s) avec cotes, {recos.C.BOOKMAKER} présent sur {len(with_bk)} ; "
          f"cote prise = {recos.C.BOOKMAKER if with_bk else 'cote moyenne'}"
          + (f" ; bookmakers vus : {', '.join(names)}" if names else ""))
    print(f"recos : {len(data['recos']['items'])} ({', '.join(i['type'] for i in data['recos']['items']) or 'aucune'}) "
          f"parmi {data['recos']['candidats']} candidat(s)")

    # --- suivi des performances : journal des cotes et des recos, puis bilan
    added = bilan.record(all_fx)
    added_r = bilan.record_recos(data["recos"]["items"])
    results = {}
    for lg in LEAGUES:
        for r in load_current(lg).itertuples():
            results[(lg, r.home, r.away)] = (int(r.hg), int(r.ag))
    data["bilan"] = bilan.compute(bilan.read_journal(), results, bilan.read_recos())
    bilan.write_paris(data["bilan"])
    print(f"journal : {added} relevé(s) et {added_r} reco(s) ajouté(s) ; {data['bilan']['journal_rows']} relevé(s), "
          f"{data['bilan']['recos']} reco(s) au total")

    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.floating, float)):
            return round(float(o), 4)
        if isinstance(o, np.integer):
            return int(o)
        return o

    path = os.path.join(HERE, "..", "out", "data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean(data), f, ensure_ascii=False, separators=(",", ":"))
    print("écrit", os.path.normpath(path), os.path.getsize(path) // 1024, "Ko")
    for L in data["leagues"]:
        n_api = sum(f["source"] == "api" for f in L["fixtures"])
        print(f"{L['name']} : {len(L['fixtures'])} matchs à venir ({n_api} avec données API)")
        for f in L["fixtures"][:2]:
            print("  ", f["home"], "-", f["away"], f["kickoff"], {k: round(float(v), 3) for k, v in f["p"].items()})
