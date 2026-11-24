"""Complète data/xg/ avec les tirs Understat republiés par le projet ouvert worldfootballR_data (GitHub).

Pourquoi : Understat est en maintenance (novembre 2026) et ses copies archive.org sont incomplètes.
worldfootballR_data publie les tirs Understat (un xG par tir), mis à jour le 18/09/2025 : on additionne
les tirs de chaque équipe pour retrouver le xG du match. Contrôle fait le 16/11/2026 sur les saisons
déjà connues : écart médian < 0,01 xG par match avec Understat, scores identiques à 100 %.

On ne fait qu'AJOUTER les matchs absents : une donnée déjà présente dans data/xg/ n'est jamais remplacée.

Utilisation (une seule fois, à la main ; la mise à jour quotidienne n'en a pas besoin) :
  pip install pyreadr
  télécharger ligue_1_shot_data.rds, epl_shot_data.rds et la_liga_shot_data.rds depuis
  https://github.com/JaseZiv/worldfootballR_data/releases/tag/understat_shots
  python engine/xg_backfill.py DOSSIER_DES_FICHIERS
"""
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import understat as u  # noqa: E402

FILES = {"fr1": "ligue_1_shot_data.rds", "en1": "epl_shot_data.rds", "es1": "la_liga_shot_data.rds",
         "it1": "serie_a_shot_data.rds"}
EXPECTED = {"fr1": {2022: 380, 2023: 306, 2024: 306, 2025: 306, 2026: 306},
            "en1": {y: 380 for y in u.SEASONS}, "es1": {y: 380 for y in u.SEASONS}, "it1": {y: 380 for y in u.SEASONS}}
TAG = "worldfootballR (tirs Understat du 18/09/2025)"


def matches_from_shots(path):
    """{saison: [match au format Understat]} en additionnant les xG des tirs de chaque équipe."""
    import pyreadr
    df = list(pyreadr.read_r(path).values())[0]
    df = df[df.season >= min(u.SEASONS)].copy()
    df["side"] = df.h_a.fillna(df.home_away)          # la colonne a changé de nom selon les saisons
    out = {}
    for (year, mid), t in df.groupby(["season", "match_id"]):
        out.setdefault(int(year), []).append({
            "id": str(int(mid)), "isResult": True, "datetime": str(t.date.iloc[0])[:19],
            "h": {"title": t.home_team.iloc[0]}, "a": {"title": t.away_team.iloc[0]},
            "goals": {"h": str(int(t.home_goals.iloc[0])), "a": str(int(t.away_goals.iloc[0]))},
            "xG": {"h": str(round(float(t[t.side == "h"].xG.sum()), 4)), "a": str(round(float(t[t.side == "a"].xG.sum()), 4))},
        })
    return out


def existing(lg, year):
    """Matchs déjà dans data/xg/ (au format Understat), pour ne jamais les remplacer."""
    p = u.csv_path(lg, year)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return [{"isResult": True, "datetime": r["date"], "h": {"title": r["domicile"]}, "a": {"title": r["exterieur"]},
                 "goals": {"h": r["buts_dom"], "a": r["buts_ext"]},
                 "xG": {"h": r["xg_dom"].replace(",", "."), "a": r["xg_ext"].replace(",", ".")}}
                for r in csv.DictReader(f, delimiter=";")]


def backfill(folder, log=print):
    src = u._sources()
    for lg, fname in FILES.items():
        path = os.path.join(folder, fname)
        if not os.path.exists(path):
            log(f"   ! {fname} absent : {lg} ignoré")
            continue
        shots = matches_from_shots(path)
        for year in u.SEASONS:
            add = shots.get(year, [])
            if not add:
                continue
            have = existing(lg, year)
            # une affiche (domicile, extérieur) n'a lieu qu'une fois par saison : on compare sans la date,
            # qui peut différer d'un jour entre deux sources (fuseau horaire, match reprogrammé)
            keys = {(u.canon(lg, m["h"]["title"], strict=False), u.canon(lg, m["a"]["title"], strict=False)) for m in have}
            new = [m for m in add if (u.canon(lg, m["h"]["title"], strict=False),
                                      u.canon(lg, m["a"]["title"], strict=False)) not in keys]
            key = f"{lg}_{u.SEASONS[year]}"
            if not new:
                log(f"   {key} : rien à ajouter ({len(have)} matchs déjà présents)")
                continue
            merged = have + new
            played, _ = u._write(lg, year, merged)
            info = src.get(key, {})
            total = EXPECTED[lg][year]
            src[key] = dict(info, source=(f"{info['source']} + {TAG}" if info.get("source") else TAG),
                            fetched=datetime.now(timezone.utc).isoformat(timespec="seconds"), matches=played,
                            total=total, complete=played >= total,
                            last_match=max(m["datetime"][:10] for m in merged))
            log(f"   {key} : +{len(new)} matchs ({len(have)} -> {played} sur {total}{', saison complète' if played >= total else ''})")
    u._save_sources(src)
    if u.UNKNOWN_NAMES:
        log("   ! noms inconnus : " + ", ".join(sorted(f"{l}:{n}" for l, n in u.UNKNOWN_NAMES)))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    backfill(sys.argv[1])
