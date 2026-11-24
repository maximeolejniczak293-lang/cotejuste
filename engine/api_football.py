"""Client minimal pour API-Football (v3), avec cache disque et garde-fou de quota.

Ce que permet le plan gratuit (vérifié le 13/11/2026) :
  - 100 requêtes par jour, 10 par minute ;
  - /fixtures?date=AAAA-MM-JJ seulement pour hier, aujourd'hui et demain (toutes ligues en 1 requête) ;
  - /odds?fixture=, /injuries?fixture=, /fixtures/lineups?fixture= match par match ;
  - PAS de season=2026, ni /standings, ni les paramètres next, last et ids.

La clé est lue dans la variable d'environnement API_FOOTBALL_KEY (secret GitHub),
sinon dans le fichier .env à la racine du projet. Elle n'est jamais affichée.

Le cache (dossier cache/) garde chaque réponse :
  - pour toujours quand la donnée ne peut plus changer (journée terminée, compositions publiées,
    cotes et absents d'un match commencé) : elle n'est plus jamais redemandée ;
  - pendant une durée limitée sinon (cotes, absents et calendrier des matchs à venir).
Le compteur cache/_quota.json bloque tout appel au-delà de API_DAILY_LIMIT (90 par défaut)
requêtes par jour UTC (le quota de l'API se remet à zéro à minuit UTC).
"""
import json
import os
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("CJ_CACHE_DIR", ROOT / "cache"))
BASE = "https://v3.football.api-sports.io"
DAILY_LIMIT = int(os.environ.get("API_DAILY_LIMIT", "90"))
MIN_INTERVAL = 6.5  # secondes entre deux requêtes : on reste sous 10 par minute

LEAGUE_IDS = {"fr1": 61, "en1": 39, "es1": 140, "it1": 135}
ID_TO_LEAGUE = {v: k for k, v in LEAGUE_IDS.items()}
FINISHED = {"FT", "AET", "PEN"}
CANCELLED = {"PST", "CANC", "ABD", "AWD", "WO"}  # reporté, annulé, arrêté, sur tapis vert
NOT_STARTED = {"NS", "TBD"}


class ApiError(RuntimeError):
    pass


class QuotaReached(ApiError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, ValueError):
        return None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _load_key() -> str:
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if key:
        return key
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"\s*(?:export\s+)?API_FOOTBALL_KEY\s*=\s*(.*)$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    raise ApiError("clé absente : ajoute la ligne API_FOOTBALL_KEY=... dans le fichier .env "
                   "(ou le secret API_FOOTBALL_KEY sur GitHub)")


# --------------------------------------------------------------------------- quota
class Quota:
    """Compteur de requêtes du jour (UTC), conservé dans cache/_quota.json."""

    def __init__(self):
        self.path = CACHE / "_quota.json"
        self.day = utcnow().strftime("%Y-%m-%d")
        saved = _read_json(self.path) or {}
        self.used = saved.get("used", 0) if saved.get("day") == self.day else 0
        self.limit = DAILY_LIMIT

    def save(self):
        _write_json(self.path, {"day": self.day, "used": self.used, "limit": self.limit})

    def sync(self, used_by_server: int):
        """Aligne le compteur sur celui de l'API (on garde le plus prudent des deux)."""
        if used_by_server > self.used:
            self.used = used_by_server
            self.save()

    @property
    def left(self) -> int:
        return max(0, self.limit - self.used)

    def take(self):
        if self.used >= self.limit:
            raise QuotaReached(f"quota de sécurité atteint ({self.used}/{self.limit} requêtes aujourd'hui)")
        self.used += 1
        self.save()


# --------------------------------------------------------------------------- client
class Client:
    def __init__(self, offline: bool = False, budget: int | None = None):
        self.offline = offline
        self.budget = budget          # plafond pour ce lancement (utile pour les tests)
        self.quota = Quota()
        self.made = 0                 # requêtes réellement envoyées par ce lancement
        self.from_cache = 0
        self.notes: list[str] = []
        self._key = None
        self._last = 0.0

    # ---- bas niveau
    def _http(self, endpoint: str, params: dict, counts: bool = True) -> dict:
        if self.offline:
            raise ApiError("mode hors ligne")
        if counts:
            if self.budget is not None and self.made >= self.budget:
                raise QuotaReached(f"budget de ce lancement atteint ({self.budget} requêtes)")
            self.quota.take()
            self.made += 1
        if self._key is None:
            self._key = _load_key()
        wait = MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0 and self._last:
            time.sleep(wait)
        url = f"{BASE}/{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"x-apisports-key": self._key, "Accept": "application/json",
                                                   "User-Agent": "cotejuste/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read().decode("utf-8"))
                headers = r.headers
        except urllib.error.HTTPError as e:
            raise ApiError(f"/{endpoint} : erreur HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise ApiError(f"/{endpoint} : problème réseau ({e.reason})") from None
        finally:
            self._last = time.monotonic()
        lim, rem = headers.get("x-ratelimit-requests-limit"), headers.get("x-ratelimit-requests-remaining")
        if lim and rem:
            try:
                self.quota.sync(int(lim) - int(rem))
            except ValueError:
                pass
        errors = body.get("errors")
        if errors:
            raise ApiError(f"/{endpoint} : {errors}")
        return body

    def sync_status(self) -> dict | None:
        """/status ne compte pas dans le quota : on s'en sert pour recaler le compteur."""
        if self.offline:
            return None
        try:
            r = self._http("status", {}, counts=False)["response"]
        except ApiError as e:
            self.notes.append(f"/status indisponible ({e})")
            return None
        used, limit = r["requests"]["current"], r["requests"]["limit_day"]
        self.quota.sync(used)
        return {"plan": r["subscription"]["plan"], "used": used, "limit": limit}

    # ---- cache
    def _entry(self, name: str):
        return _read_json(CACHE / f"{name}.json")

    def is_fresh(self, name: str, max_age: float) -> bool:
        hit = self._entry(name)
        if not hit:
            return False
        if hit.get("final") or self.offline:
            return True
        return (utcnow() - parse_iso(hit["fetched"])).total_seconds() < max_age

    def cached_data(self, name: str):
        hit = self._entry(name)
        return hit["data"] if hit else None

    def _cached(self, name: str, max_age: float, fetch, is_final):
        hit = self._entry(name)
        if hit and self.is_fresh(name, max_age):
            self.from_cache += 1
            return hit["data"]
        try:
            data = fetch()
        except ApiError as e:
            if hit:  # on garde l'ancienne version plutôt que rien
                self.notes.append(f"{name} : ancienne version conservée ({e})")
                return hit["data"]
            raise
        _write_json(CACHE / f"{name}.json",
                    {"fetched": utcnow().isoformat(timespec="seconds"), "final": bool(is_final(data)), "data": data})
        return data

    # ---- points d'accès
    def fixtures_on(self, day: str, max_age: float = 3 * 3600) -> list[dict]:
        """Matchs de Ligue 1, Premier League, LaLiga et Serie A à cette date (UTC). 1 requête, toutes ligues."""
        d = date.fromisoformat(day)

        def fetch():
            body = self._http("fixtures", {"date": day})
            return [_slim_fixture(f) for f in body["response"] if f["league"]["id"] in ID_TO_LEAGUE]

        def final(data):  # journée passée et tous les matchs terminés (ou reportés) : ne changera plus
            return d < utcnow().date() and all(f["status"] in FINISHED | CANCELLED for f in data)

        return self._cached(f"fixtures/{day}", max_age, fetch, final)

    def odds(self, fixture: dict, max_age: float) -> dict:
        def fetch():
            return _slim_odds(self._http("odds", {"fixture": fixture["id"]})["response"])
        return self._cached(f"odds/{fixture['id']}", max_age, fetch, lambda _: _started(fixture))

    def injuries(self, fixture: dict, max_age: float) -> list[dict]:
        def fetch():
            return _slim_injuries(self._http("injuries", {"fixture": fixture["id"]})["response"])
        return self._cached(f"injuries/{fixture['id']}", max_age, fetch, lambda _: _started(fixture))

    def closing_odds(self, fixture: dict) -> dict:
        """Cotes de clôture : lues une seule fois, juste avant le coup d'envoi, et gardées pour toujours."""
        def fetch():
            return _slim_odds(self._http("odds", {"fixture": fixture["id"]})["response"])
        return self._cached(f"closing/{fixture['id']}", 0, fetch, lambda _: True)

    def lineups(self, fixture: dict) -> list[dict]:
        """Compositions : redemandées tant qu'elles ne sont pas publiées, gardées pour toujours ensuite."""
        def fetch():
            return _slim_lineups(self._http("fixtures/lineups", {"fixture": fixture["id"]})["response"])

        def final(data):
            return len(data) == 2 and all(len(t["xi"]) == 11 for t in data)
        return self._cached(f"lineups/{fixture['id']}", 0, fetch, final)


def _started(fixture: dict) -> bool:
    return parse_iso(fixture["kickoff"]) <= utcnow()


# --------------------------------------------------------------------------- mise en forme
def round_number(label: str) -> int | None:
    """'Regular Season - 11' -> 11"""
    m = re.search(r"(\d+)\s*$", label or "")
    return int(m.group(1)) if m else None


def _slim_fixture(f: dict) -> dict:
    ft = (f.get("score") or {}).get("fulltime") or {}
    return dict(
        id=f["fixture"]["id"], league=ID_TO_LEAGUE[f["league"]["id"]], season=f["league"]["season"],
        round=f["league"]["round"], kickoff=f["fixture"]["date"], status=f["fixture"]["status"]["short"],
        venue=((f["fixture"].get("venue") or {}).get("name")),
        home=f["teams"]["home"]["name"], home_id=f["teams"]["home"]["id"],
        away=f["teams"]["away"]["name"], away_id=f["teams"]["away"]["id"],
        hg=ft.get("home", f["goals"]["home"]), ag=ft.get("away", f["goals"]["away"]),
    )


def _slim_odds(resp: list) -> dict:
    if not resp:
        return {"update": None, "bookmakers": []}
    item = resp[0]
    bks = []
    for b in item.get("bookmakers", []):
        rec = {"name": b["name"]}
        for bet in b.get("bets", []):
            vals = {v["value"]: v["odd"] for v in bet.get("values", [])}
            if bet["id"] == 1:  # Match Winner
                rec["1n2"] = {"h": vals.get("Home"), "d": vals.get("Draw"), "a": vals.get("Away")}
            elif bet["id"] == 5:  # Goals Over/Under
                rec["ou25"] = {"o": vals.get("Over 2.5"), "u": vals.get("Under 2.5")}
        bks.append(rec)
    return {"update": item.get("update"), "bookmakers": bks}


def _slim_injuries(resp: list) -> list[dict]:
    out = []
    for r in resp:
        p = r.get("player") or {}
        out.append(dict(team_id=(r.get("team") or {}).get("id"), player=p.get("name"),
                        type=p.get("type"), reason=p.get("reason")))
    return out


def _slim_lineups(resp: list) -> list[dict]:
    def players(lst):
        return [dict(n=(x.get("player") or {}).get("number"), name=(x.get("player") or {}).get("name"),
                     pos=(x.get("player") or {}).get("pos")) for x in lst or []]
    return [dict(team_id=t["team"]["id"], formation=t.get("formation"), coach=(t.get("coach") or {}).get("name"),
                 xi=players(t.get("startXI")), subs=players(t.get("substitutes"))) for t in resp]


def _plain(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def summarize_odds(slim: dict | None) -> dict | None:
    """Médiane, moyenne et meilleure cote parmi les bookmakers, cote de ton bookmaker (config.BOOKMAKER)
    s'il est présent, et probabilités implicites tirées de la cote MOYENNE, marge retirée
    (sur 3 issues pour le 1N2, sur 2 pour +/-2,5)."""
    if not slim or not slim.get("bookmakers"):
        return None
    try:
        from config import BOOKMAKER
    except ImportError:
        BOOKMAKER = ""
    out = {"n": len(slim["bookmakers"]), "update": slim.get("update"), "median": {}, "mean": {}, "best": {},
           "bookmakers": sorted(b["name"] for b in slim["bookmakers"]), "pref": None}
    mine = next((b for b in slim["bookmakers"] if BOOKMAKER and _plain(BOOKMAKER) in _plain(b["name"])), None)
    if mine:
        odds = {}
        for key, (bet, side) in {"h": ("1n2", "h"), "d": ("1n2", "d"), "a": ("1n2", "a"),
                                 "o25": ("ou25", "o"), "u25": ("ou25", "u")}.items():
            try:
                v = float((mine.get(bet) or {}).get(side))
                if v > 1:
                    odds[key] = v
            except (TypeError, ValueError):
                pass
        out["pref"] = {"name": mine["name"], "odds": odds} if odds else None
    for key, (bet, side) in {"h": ("1n2", "h"), "d": ("1n2", "d"), "a": ("1n2", "a"),
                             "o25": ("ou25", "o"), "u25": ("ou25", "u")}.items():
        vals = []
        for b in slim["bookmakers"]:
            try:
                v = float((b.get(bet) or {}).get(side))
            except (TypeError, ValueError):
                continue
            if v > 1:
                vals.append((v, b["name"]))
        if vals:
            out["median"][key] = round(statistics.median(v for v, _ in vals), 2)
            out["mean"][key] = round(statistics.fmean(v for v, _ in vals), 3)
            best = max(vals)
            out["best"][key] = [best[0], best[1]]
    m = out["mean"]
    if all(k in m for k in "hda"):
        inv = {k: 1 / m[k] for k in "hda"}
        s = sum(inv.values())
        out["implied"] = {k: round(v / s, 4) for k, v in inv.items()}
        out["margin"] = round(s - 1, 4)
    if "o25" in m and "u25" in m:
        io, iu = 1 / m["o25"], 1 / m["u25"]
        out["implied_ou"] = {"o25": round(io / (io + iu), 4), "u25": round(iu / (io + iu), 4)}
    return out if out["median"] else None


if __name__ == "__main__":
    # petit diagnostic sans consommer de quota
    c = Client()
    st = c.sync_status()
    print("statut :", st if st else c.notes)
    print(f"compteur local : {c.quota.used}/{c.quota.limit} requêtes aujourd'hui (UTC)")
