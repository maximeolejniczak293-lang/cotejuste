"""Mise à jour automatique de CoteJuste : API-Football -> raw/ + cache/live.json -> export.py -> build.py.

À lancer depuis le dossier cotejuste-code :
  python update.py                    mise à jour complète (chaque matin)
  python update.py --lineups          compositions des matchs qui commencent dans l'heure, puis site
  python update.py --lineups --check  dit seulement s'il y a des compositions à chercher (0 requête)
  python update.py --offline          aucune requête : reconstruit le site à partir du cache
  python update.py --budget 5         au plus 5 requêtes pendant ce lancement (pour tester)
  python update.py --no-site          s'arrête après l'API (ni export ni build)

Plan gratuit : seules les dates d'hier, d'aujourd'hui et de demain sont accessibles. Chaque matin on récupère
donc les résultats de la veille (ajoutés à raw/*.txt, qui sert d'archive) et les matchs des 48 h à venir,
avec leurs cotes et leurs absents.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "engine"))
import api_football as af  # noqa: E402
from names import canon  # noqa: E402

LIVE = af.CACHE / "live.json"
SEASON_API = 2026                      # saison 2026-27 côté API-Football
REFRESH = 12 * 3600                    # cotes et absents : rafraîchis s'ils ont plus de 12 h
LINEUP_FROM = timedelta(minutes=50)    # compositions cherchées à partir de 50 min avant le coup d'envoi
LINEUP_UNTIL = timedelta(minutes=20)   # ... et jusqu'à 20 min après
LINEUP_TRIES = 3                       # au plus 3 essais par match
IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def log(msg=""):
    print(msg, flush=True)


def warn(msg):
    print(("::warning::" if IN_ACTIONS else "  ! ") + msg, flush=True)


def set_output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def kickoff(f):
    return af.parse_iso(f["kickoff"])


def name_of(league, api_name):
    try:
        return canon(league, api_name)
    except KeyError:
        sys.exit(f"\nNom d'équipe inconnu renvoyé par l'API : {api_name!r} ({league}).\n"
                 f"Ajoute-le dans engine/names.py (liste ALIASES de l'équipe concernée), puis relance.")


def by_side(items, f):
    """Répartit une liste (absents, compositions) entre domicile et extérieur grâce à l'identifiant d'équipe."""
    return {"home": [x for x in items if x["team_id"] == f["home_id"]],
            "away": [x for x in items if x["team_id"] == f["away_id"]]}


def lineups_of(client, f):
    data = client.cached_data(f"lineups/{f['id']}")
    if not data or len(data) < 2:
        return None
    sides = by_side(data, f)
    if not sides["home"] or not sides["away"]:
        return None
    return {"home": sides["home"][0], "away": sides["away"][0]}


def fetched_at(name):
    hit = af._read_json(af.CACHE / f"{name}.json")
    return hit["fetched"] if hit else None


def enrich(client, f, previous=None):
    lg = f["league"]
    inj = client.cached_data(f"injuries/{f['id']}")
    return dict(
        f, home_c=name_of(lg, f["home"]), away_c=name_of(lg, f["away"]), round_n=af.round_number(f["round"]),
        odds=af.summarize_odds(client.cached_data(f"odds/{f['id']}")),
        injuries=None if inj is None else {k: [{x: i[x] for x in ("player", "type", "reason")} for i in v]
                                           for k, v in by_side(inj, f).items()},
        lineups=lineups_of(client, f),
        checked={"odds": fetched_at(f"odds/{f['id']}"), "injuries": fetched_at(f"injuries/{f['id']}")},
        lineup_tries=(previous or {}).get("lineup_tries", 0),
    )


# --------------------------------------------------------------------------- résultats -> raw/
def store_results():
    """Ajoute à raw/*.txt les matchs terminés de toutes les journées en cache (rien n'est perdu
    si un lancement a échoué : le cache garde la réponse de l'API)."""
    import data  # pandas n'est nécessaire qu'ici
    found = {lg: [] for lg in af.LEAGUE_IDS}
    for path in sorted((af.CACHE / "fixtures").glob("*.json")):
        for f in af._read_json(path)["data"]:
            if f["status"] in af.FINISHED and f["season"] == SEASON_API and f["hg"] is not None:
                lg = f["league"]
                found[lg].append(dict(date=f["kickoff"][:10], round=af.round_number(f["round"]),
                                      home=name_of(lg, f["home"]), away=name_of(lg, f["away"]), hg=f["hg"], ag=f["ag"]))
    added = {}
    for lg, matches in found.items():
        new = data.add_results(lg, matches)
        if new:
            added[lg] = new
    return added


def verify_all():
    import data
    for lg in af.LEAGUE_IDS:
        issues, notes = data.verify(lg)
        if issues:
            for i in issues:
                warn(f"{lg} : {i}")
        else:
            log(f"  {lg} : vérification OK")
        for n in notes:
            log(f"  {lg} (info) : {n}")


# --------------------------------------------------------------------------- mise à jour complète
def full_update(client):
    now = af.utcnow()
    today = now.date()
    days = [(today + timedelta(days=k)).isoformat() for k in (-1, 0, 1)]

    log("1) Calendrier et résultats (1 requête par jour : hier, aujourd'hui, demain)")
    fixtures = []
    for d in days:
        try:
            got = client.fixtures_on(d)
            fixtures += got
            log(f"   {d} : {len(got)} match(s) Ligue 1 / Premier League / LaLiga")
        except af.ApiError as e:
            warn(f"{d} : {e}")

    log("2) Résultats ajoutés aux fichiers raw/")
    added = store_results()
    for lg, new in added.items():
        for m in new:
            log(f"   + {lg} {m['date']} {m['home']} {m['hg']}-{m['ag']} {m['away']}")
    if not added:
        log("   aucun nouveau résultat")
    verify_all()

    upcoming = sorted([f for f in fixtures if f["status"] not in af.FINISHED | af.CANCELLED
                       and kickoff(f) > now - timedelta(hours=3)], key=kickoff)
    for f in upcoming:  # vérifie les noms tout de suite
        name_of(f["league"], f["home"]), name_of(f["league"], f["away"])
    pre = [f for f in upcoming if kickoff(f) > now]

    log(f"3) Cotes et absents de {len(pre)} match(s) à venir dans les 48 h")
    # on garde de quoi chercher les compositions des matchs du jour
    reserve = LINEUP_TRIES * sum(1 for f in pre if kickoff(f) - now < timedelta(hours=20) and kickoff(f) - now > LINEUP_FROM)
    tasks = []
    for f in pre:
        match_day = kickoff(f) - now < timedelta(hours=30)
        for kind in ("injuries", "odds"):
            name = f"{kind}/{f['id']}"
            if client.is_fresh(name, REFRESH):
                continue
            exists = client.cached_data(name) is not None
            if exists and not match_day:
                continue  # déjà vu hier : on attend le jour du match pour rafraîchir
            prio = (0 if match_day else 2) if not exists else (1 if kind == "injuries" else 3)
            tasks.append((prio, f["kickoff"], kind, f))
    tasks.sort(key=lambda t: t[:3])
    skipped = 0
    for prio, _, kind, f in tasks:
        room = client.quota.left - reserve
        if room <= 0 or (client.budget is not None and client.made >= client.budget):
            skipped += 1
            continue
        try:
            getattr(client, kind)(f, REFRESH)
        except af.QuotaReached as e:
            warn(str(e)); skipped += 1
        except af.ApiError as e:
            warn(f"{kind} {f['home']}-{f['away']} : {e}")
    if skipped:
        log(f"   {skipped} appel(s) reporté(s) pour garder {reserve} requêtes aux compositions (ou budget atteint)")

    old = {f["id"]: f for f in (af._read_json(LIVE) or {}).get("fixtures", [])}
    for f in upcoming:  # compositions si on est déjà dans l'heure qui précède
        if -LINEUP_UNTIL <= kickoff(f) - now <= LINEUP_FROM:
            try:
                client.lineups(f)
            except af.ApiError as e:
                warn(f"compositions {f['home']}-{f['away']} : {e}")

    live = dict(generated=now.isoformat(timespec="seconds"), mode="complet", window=days,
                quota=dict(used=client.quota.used, limit=client.quota.limit),
                fixtures=[enrich(client, f, old.get(f["id"])) for f in upcoming])
    af._write_json(LIVE, live)
    return True


# --------------------------------------------------------------------------- compositions seulement
def lineup_targets(live, now):
    return [f for f in live.get("fixtures", [])
            if f.get("lineups") is None and f.get("lineup_tries", 0) < LINEUP_TRIES
            and -LINEUP_UNTIL <= kickoff(f) - now <= LINEUP_FROM]


def lineups_update(client, check_only):
    live = af._read_json(LIVE)
    if not live:
        log("Pas encore de cache/live.json : lance d'abord une mise à jour complète.")
        set_output("needed", "false")
        return False
    now = af.utcnow()
    targets = lineup_targets(live, now)
    if check_only:
        log(f"{len(targets)} match(s) dont on attend les compositions" +
            "".join(f"\n   {f['home']} - {f['away']} ({f['kickoff']})" for f in targets))
        set_output("needed", "true" if targets else "false")
        return False
    changed = False
    for f in targets:
        f["lineup_tries"] = f.get("lineup_tries", 0) + 1
        try:
            client.lineups(f)
        except af.ApiError as e:
            warn(f"compositions {f['home']}-{f['away']} : {e}")
            continue
        lu = lineups_of(client, f)
        log(f"   {f['home']} - {f['away']} : " + ("compositions publiées" if lu else "pas encore publiées"))
        if lu:
            f["lineups"] = lu
            changed = True
    live["quota"] = dict(used=client.quota.used, limit=client.quota.limit)
    af._write_json(LIVE, live)
    return changed


# --------------------------------------------------------------------------- site
def build_site():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    log("4) Modèle et export (engine/export.py)")
    subprocess.run([sys.executable, "export.py"], cwd=ROOT / "engine", check=True, env=env)
    log("5) Site (site/build.py)")
    subprocess.run([sys.executable, "build.py"], cwd=ROOT / "site", check=True, env=env)


def main():
    ap = argparse.ArgumentParser(description="Mise à jour de CoteJuste depuis API-Football")
    ap.add_argument("--lineups", action="store_true", help="seulement les compositions des matchs imminents")
    ap.add_argument("--check", action="store_true", help="avec --lineups : dire s'il y a quelque chose à faire")
    ap.add_argument("--offline", action="store_true", help="aucune requête, utilise le cache")
    ap.add_argument("--budget", type=int, help="nombre maximum de requêtes pour ce lancement")
    ap.add_argument("--no-site", action="store_true", help="ne pas relancer export.py et build.py")
    args = ap.parse_args()

    client = af.Client(offline=args.offline, budget=args.budget)
    if not args.offline and not args.check:
        st = client.sync_status()
        if st:
            log(f"API-Football : plan {st['plan']}, {st['used']}/{st['limit']} requêtes utilisées aujourd'hui "
                f"(arrêt de sécurité à {client.quota.limit})")
    if args.lineups:
        changed = lineups_update(client, args.check)
        if args.check:
            return
    else:
        changed = full_update(client)
    set_output("changed", "true" if changed else "false")
    if changed and not args.no_site:
        build_site()
    elif not changed:
        log("Rien de nouveau : site inchangé.")
    for n in client.notes:
        warn(n)
    log(f"\nBilan : {client.made} requête(s) envoyée(s), {client.from_cache} réponse(s) lue(s) dans le cache, "
        f"compteur du jour {client.quota.used}/{client.quota.limit}.")


if __name__ == "__main__":
    main()
