"""Recos du jour : pari sécu, pari valeur, combiné du jour et grosse cote (optionnelle, pour s'amuser).

Calculées à chaque mise à jour du site à partir des cotes déjà en cache (aucune requête API).
Candidats : 1, N, 2, +2,5, -2,5 des matchs pas encore commencés, à moins de 48 h, avec cotes.
Cote de référence = cote de ton bookmaker (config.BOOKMAKER) si l'API la fournit pour ce match et ce pari,
sinon la cote moyenne. Valeur = cote de référence × proba finale ; Kelly et cotes de combiné aussi.
Combiné : produit des cotes de ton bookmaker si toutes les sélections en ont une, sinon produit des cotes
moyennes (jamais un mélange). La meilleure cote n'est affichée qu'à titre indicatif.
Le bilan juge chaque reco à exactement cette cote de référence. Les seuils sont dans config.py.
Les mises en euros sont calculées dans la page (bankroll du visiteur) : ici, on fournit la fraction de Kelly.
"""
import itertools
from datetime import datetime, timedelta, timezone

import config as C

LABEL = {"h": "1", "d": "N", "a": "2", "o25": "+2,5 buts", "u25": "−2,5 buts"}
BUTS = {"o25", "u25"}
CONF_ORDER = ["Faible", "Moyenne", "Élevée"]


def _ko(f):
    return datetime.fromisoformat(f["kickoff"].replace("Z", "+00:00"))


def pick_name(f, k):
    return {"h": f"Victoire {f['home']}", "d": "Match nul", "a": f"Victoire {f['away']}",
            "o25": "Plus de 2,5 buts", "u25": "Moins de 2,5 buts"}[k]


def kelly(p, o):
    """1/4 de Kelly, plafonné à 5 % de la bankroll (fraction, pas d'euros)."""
    if o <= 1:
        return 0.0
    f = (o * p - 1) / (o - 1)
    return max(0.0, min(f * C.KELLY_FRACTION, C.KELLY_PLAFOND))


def candidates(fixtures, now):
    out = []
    for f in fixtures:
        if not f.get("pk") or not f.get("odds") or f.get("source") != "api":
            continue
        ko = _ko(f)
        if not (now < ko <= now + timedelta(hours=C.HORIZON_H)):
            continue
        o = f["odds"]
        pref = o.get("pref") or {}
        for k in LABEL:
            if k not in f["pk"] or not o["best"].get(k) or not o["mean"].get(k):
                continue
            best, best_bk = o["best"][k]
            p = f["pf"][k]
            mine = (pref.get("odds") or {}).get(k)
            ref, src = (mine, "bookmaker") if mine else (o["mean"][k], "moyenne")
            out.append(dict(f=f, k=k, p=p, pm=f["pm"][k], pk=f["pk"][k], best=best, best_bk=best_bk,
                            mean=o["mean"][k], pref=mine, pref_name=pref.get("name"),
                            ref=ref, ref_src=src, valeur=ref * p))
    return out


def combo_odds(cands):
    """Cote d'un combiné : ton bookmaker si toutes les sélections en ont une, sinon la moyenne partout."""
    src = "bookmaker" if all(c["pref"] for c in cands) else "moyenne"
    cote = 1.0
    for c in cands:
        cote *= c["pref"] if src == "bookmaker" else c["mean"]
    return cote, src


def confidence(c):
    agree = abs(c["pm"] - c["pk"]) <= C.CONFIANCE_ECART
    known = c["f"].get("absents") is not None
    return CONF_ORDER[int(agree) + int(known)]


def reasons(c, teams):
    """2 ou 3 raisons tirées des données du match, les plus parlantes d'abord."""
    f, k = c["f"], c["k"]
    h, a = f["home"], f["away"]
    th, ta = teams[h], teams[a]
    R = []
    gap = c["pm"] - c["pk"]
    if abs(gap) <= C.CONFIANCE_ECART:
        R.append((3, f"Modèle et marché d'accord : {c['pm'] * 100:.0f} % et {c['pk'] * 100:.0f} %."))
    else:
        R.append((2, f"Le modèle donne {abs(gap) * 100:.0f} points {'de plus' if gap > 0 else 'de moins'} que le marché "
                     f"({c['pm'] * 100:.0f} % contre {c['pk'] * 100:.0f} %)."))
    if k in ("h", "a"):
        me, opp = (h, a) if k == "h" else (a, h)
        tm, to = teams[me], teams[opp]
        if tm["form_pts"] - to["form_pts"] >= 3:
            R.append((3, f"Meilleure forme : {me} {tm['form_pts']}/15 sur ses 5 derniers matchs, {opp} {to['form_pts']}/15."))
        if to["power_rank"] - tm["power_rank"] >= 4:
            R.append((3, f"Rang de puissance du modèle : {me} {tm['power_rank']}e, {opp} {to['power_rank']}e."))
        rec, where = (tm["home"], "à domicile") if k == "h" else (tm["away"], "à l'extérieur")
        if rec["P"] >= 3:
            R.append((2 if rec["W"] * 2 >= rec["P"] else 0, f"{me} {where} cette saison : {rec['W']}V {rec['D']}N {rec['L']}D."))
    elif k == "d":
        if abs(th["power_rank"] - ta["power_rank"]) <= 3:
            R.append((3, f"Équipes proches : rangs de puissance {th['power_rank']}e et {ta['power_rank']}e."))
        R.append((1, f"Nuls cette saison : {th['home']['D'] + th['away']['D']} pour {h}, {ta['home']['D'] + ta['away']['D']} pour {a}."))
    else:
        xg = f["xg"]["h"] + f["xg"]["a"]
        strong = (k == "o25" and xg >= 2.9) or (k == "u25" and xg <= 2.3)
        R.append((3 if strong else 1, f"Buts attendus par le modèle : {xg:.1f}.".replace(".", ",", 1)))
        if th["n"] and ta["n"]:
            R.append((2, f"Matchs à 3 buts ou plus cette saison : {th['over25']}/{th['n']} pour {h}, {ta['over25']}/{ta['n']} pour {a}."))
    ab = f.get("absents")
    if ab is not None:
        nh, na = len(ab.get("home") or []), len(ab.get("away") or [])
        R.append((2 if nh or na else 1, f"Absents connus : {nh} pour {h}, {na} pour {a}." if nh or na
                  else "Aucun absent signalé pour les deux équipes."))
    else:
        R.append((0, "Liste des absents pas encore connue : prudence."))
    if f.get("h2h") and k in ("h", "d", "a"):
        n = len(f["h2h"])
        wins = {"h": h, "a": a}
        if k == "d":
            hit = sum(m["hg"] == m["ag"] for m in f["h2h"])
            R.append((1, f"Confrontations depuis 2022 : {hit} nul(s) sur {n}."))
        else:
            t = wins[k]
            hit = sum((m["home"] == t and m["hg"] > m["ag"]) or (m["away"] == t and m["ag"] > m["hg"]) for m in f["h2h"])
            R.append((1, f"Confrontations depuis 2022 : {hit} victoire(s) de {t} sur {n}."))
    R.sort(key=lambda x: -x[0])
    return [t for _, t in R[:3]]


def _leg(c, src):
    f = c["f"]
    return dict(id=f["id"], api_id=f.get("api_id"), league=f["league"], home=f["home"], away=f["away"],
                kickoff=f["kickoff"], k=c["k"], label=LABEL[c["k"]], pick=pick_name(f, c["k"]),
                p=c["p"], pm=c["pm"], pk=c["pk"], best=c["best"], best_bk=c["best_bk"], mean=c["mean"],
                pref=c["pref"], pref_name=c["pref_name"] if c["pref"] else None,
                ref=c["pref"] if src == "bookmaker" else c["mean"], ref_src=src,
                absents_connus=f.get("absents") is not None)


def _item(kind, cands, teams_by_league, cote_min_num, fixed=None):
    chance, best, mean = 1.0, 1.0, 1.0
    for c in cands:
        chance *= c["p"]; best *= c["best"]; mean *= c["mean"]
    ref, src = combo_odds(cands)
    conf = CONF_ORDER[min(CONF_ORDER.index(confidence(c)) for c in cands)]
    if len(cands) == 1:
        why = reasons(cands[0], teams_by_league[cands[0]["f"]["league"]])
    else:
        why = [f"{c['f']['home']} – {c['f']['away']} : {pick_name(c['f'], c['k'])} ({c['p'] * 100:.0f} %). "
               + reasons(c, teams_by_league[c["f"]["league"]])[0] for c in cands]
    return dict(type=kind, legs=[_leg(c, src) for c in cands], chance=chance,
                cote=ref, cote_src=src, cote_bk_nom=cands[0]["pref_name"] if src == "bookmaker" else None,
                meilleure_cote=best, cote_moyenne=mean,
                valeur=ref * chance, cote_min=cote_min_num / chance, kelly=None if fixed else kelly(chance, ref),
                mise_fixe=fixed, confiance=conf, raisons=why)


def build(fixtures, teams_by_league, now=None):
    """Renvoie {'items': [...], 'candidats': n, 'matchs': n}. Ne force jamais une reco."""
    now = now or datetime.now(timezone.utc)
    cands = candidates(fixtures, now)
    key = lambda c: (c["f"]["id"], c["k"])  # noqa: E731
    used, items = set(), []

    secu = [c for c in cands if c["p"] >= C.SECU["p_min"] and c["ref"] >= C.SECU["cote_min"]
            and c["valeur"] >= C.SECU["valeur_min"]]
    if secu:
        s = max(secu, key=lambda c: (c["p"], c["valeur"]))
        items.append(_item("secu", [s], teams_by_league, 1.0))
        used.add(key(s))

    val = [c for c in cands if key(c) not in used and c["p"] >= C.VALEUR["p_min"]
           and c["valeur"] >= (C.VALEUR["valeur_min_buts"] if c["k"] in BUTS else C.VALEUR["valeur_min_1n2"])]
    if val:
        v = max(val, key=lambda c: c["valeur"])
        items.append(_item("valeur", [v], teams_by_league, C.VALEUR["marge_cote_min"]))
        used.add(key(v))

    legs = [c for c in cands if c["p"] >= C.COMBI["p_min"]]
    top = None
    for n in C.COMBI["tailles"]:
        for combo in itertools.combinations(legs, n):
            if len({c["f"]["id"] for c in combo}) < n:
                continue
            chance = 1.0
            for c in combo:
                chance *= c["p"]
            cote, _ = combo_odds(combo)  # ton bookmaker partout, ou la moyenne partout
            v = chance * cote
            if chance >= C.COMBI["chance_min"] and v >= C.COMBI["valeur_min"] and (top is None or v > top[0]):
                top = (v, combo)
    if top:
        items.append(_item("combine", sorted(top[1], key=lambda c: c["f"]["kickoff"]), teams_by_league, 1.0))

    big = [c for c in cands if key(c) not in used and c["ref"] >= C.GROSSE["cote_min"]
           and c["valeur"] >= C.GROSSE["valeur_min"]]
    if big:
        g = max(big, key=lambda c: c["valeur"])
        items.append(_item("grosse", [g], teams_by_league, 1.0, fixed=C.GROSSE["mise"]))

    matches = len({c["f"]["id"] for c in cands})
    return dict(items=items, candidats=len(cands), matchs=matches,
                regles=dict(secu=C.SECU, valeur=C.VALEUR, combine=C.COMBI, grosse=C.GROSSE,
                            kelly=dict(fraction=C.KELLY_FRACTION, plafond=C.KELLY_PLAFOND, mise_min=C.MISE_MIN,
                                       plafond_total=C.PLAFOND_TOTAL)))
