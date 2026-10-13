"""
Liga Endesa (ACB) data, read from the public pages of acb.com.

acb.com has no open API, but every page carries its data inside the HTML (the "flight" rows that
Next.js sends to the browser). This module downloads those pages and returns plain Python data:

    calendar()                 the running season: clubs and all games (schedule and results)
    box(game code)             one finished game: quarter scores, coaches, arena, full box score
    roster(club slug)          a club's current players and head coach
    standings()                the official table (with the league's tie-breakers)
    past_games(season)         every game of a finished season
    past_players(season)       every player's totals in a finished season

Seasons are named by the year they start in: "2026" is 2026-27. Clubs are identified by acb.com's
club id (Real Madrid is "9"), which stays the same when the sponsor in the name changes.
Only uses the Python standard library.
"""

import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

SITE = "https://acb.com/es/liga"
LIVE = "https://live.acb.com/es/partidos"

# Everyday club names (acb.com only has the sponsor names) and home cities: club id -> (name, city, country)
CLUBS = {
    "2": ("Barça", "Barcelona", "Spain"),
    "3": ("Baskonia", "Vitoria-Gasteiz", "Spain"),
    "4": ("Bilbao Basket", "Bilbao", "Spain"),
    "5": ("Gran Canaria", "Las Palmas", "Spain"),
    "8": ("Joventut", "Badalona", "Spain"),
    "9": ("Real Madrid", "Madrid", "Spain"),
    "10": ("Manresa", "Manresa", "Spain"),
    "12": ("UCAM Murcia", "Murcia", "Spain"),
    "13": ("Valencia Basket", "Valencia", "Spain"),
    "14": ("Unicaja", "Málaga", "Spain"),
    "16": ("Zaragoza", "Zaragoza", "Spain"),
    "22": ("Andorra", "Andorra la Vella", "Andorra"),
    "25": ("Breogán", "Lugo", "Spain"),
    "28": ("Tenerife", "La Laguna", "Spain"),
    "57": ("Obradoiro", "Santiago de Compostela", "Spain"),
    "549": ("Burgos", "Burgos", "Spain"),
    "591": ("Girona", "Girona", "Spain"),
    "592": ("Granada", "Granada", "Spain"),
    "657": ("Coruña", "A Coruña", "Spain"),
    "658": ("Lleida", "Lleida", "Spain"),
}

POSITIONS = {"Base": "Point guard", "Escolta": "Shooting guard", "Alero": "Small forward",
             "Ala-pívot": "Power forward", "Pívot": "Center"}

# acb.com names countries in Spanish; the site shows the usual three-letter codes
COUNTRIES = {
    "España": "ESP", "EE.UU.": "USA", "Estados Unidos": "USA", "Francia": "FRA", "Alemania": "GER", "Italia": "ITA",
    "Lituania": "LTU", "Letonia": "LAT", "Estonia": "EST", "Serbia": "SRB", "Croacia": "CRO", "Eslovenia": "SLO",
    "Montenegro": "MNE", "Bosnia y Herzegovina": "BIH", "Macedonia del Norte": "MKD", "Grecia": "GRE",
    "Turquía": "TUR", "Argentina": "ARG", "Brasil": "BRA", "Uruguay": "URU", "Venezuela": "VEN", "Colombia": "COL",
    "México": "MEX", "Cuba": "CUB", "República Dominicana": "DOM", "Puerto Rico": "PUR", "Canadá": "CAN",
    "Senegal": "SEN", "Nigeria": "NGR", "Mali": "MLI", "Malí": "MLI", "Angola": "ANG", "Camerún": "CMR",
    "Cabo Verde": "CPV", "Guinea": "GUI", "Costa de Marfil": "CIV", "Sudán del Sur": "SSD", "Egipto": "EGY",
    "República Democrática del Congo": "COD", "Congo": "CGO", "Túnez": "TUN", "Marruecos": "MAR",
    "Reino Unido": "GBR", "Gran Bretaña": "GBR", "Irlanda": "IRL", "Países Bajos": "NED", "Bélgica": "BEL",
    "Suecia": "SWE", "Dinamarca": "DEN", "Finlandia": "FIN", "Noruega": "NOR", "Islandia": "ISL",
    "Polonia": "POL", "República Checa": "CZE", "Chequia": "CZE", "Eslovaquia": "SVK", "Hungría": "HUN",
    "Austria": "AUT", "Suiza": "SUI", "Portugal": "POR", "Ucrania": "UKR", "Rusia": "RUS", "Georgia": "GEO",
    "Bulgaria": "BUL", "Rumanía": "ROU", "Israel": "ISR", "Australia": "AUS", "Nueva Zelanda": "NZL",
    "Japón": "JPN", "China": "CHN", "Andorra": "AND", "Bahamas": "BAH", "Jamaica": "JAM", "Georgia ": "GEO",
}


def edition(season):
    """'2026' -> acb.com's edition id (91)"""
    return int(season) - 1935


def previous(season):
    return str(int(season) - 1)


def madrid_time(utc):
    """'2026-09-26T16:00:00Z' -> the same moment on a clock in Madrid, '2026-09-26T18:00:00'"""
    t = datetime.fromisoformat(utc.replace("Z", "+00:00")).replace(tzinfo=None)

    def last_sunday(month):  # summer time runs from the last Sunday of March to the last Sunday of October
        d = datetime(t.year, month, 31, 1)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    summer = last_sunday(3) <= t < last_sunday(10)
    return (t + timedelta(hours=2 if summer else 1)).isoformat()


# ---------- downloading and reading pages ----------
def fetch(url, attempts=6):
    """GET a page, waiting and retrying when the site is busy or the connection drops."""
    req = urllib.request.Request(url, headers={"User-Agent": "acb-hub"})
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == attempts - 1:
                raise
            wait = int(e.headers.get("Retry-After") or 30)
            print(f"  acb.com is busy ({e.code}), waiting {wait}s...", flush=True)
            time.sleep(wait + 1)
        except (urllib.error.URLError, TimeoutError) as e:
            if i == attempts - 1:
                raise
            print(f"  connection problem ({e}), retrying in 20s...", flush=True)
            time.sleep(20)


_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


class Page:
    """The data rows of one acb.com page: row id -> parsed JSON."""

    def __init__(self, url):
        data = "".join(json.loads(m.group(1)) for m in _PUSH.finditer(fetch(url))).encode("utf-8")
        self.rows, pos = {}, 0
        while pos < len(data):
            colon = data.find(b":", pos)
            if colon < 0:
                break
            if data[colon + 1:colon + 2] == b"T":  # a text row: "id:T<length in hex>,<text>"
                comma = data.find(b",", colon)
                pos = comma + 1 + int(data[colon + 2:comma], 16)
                continue
            end = data.find(b"\n", colon)
            end = len(data) if end < 0 else end
            try:
                self.rows[data[pos:colon].decode()] = json.loads(data[colon + 1:end])
            except ValueError:
                pass  # not data (a script or style reference)
            pos = end + 1

    def resolve(self, value):
        """Repeated objects are sent once and then pointed to, like '$2f:props:data:teams:14'."""
        seen = 0
        while isinstance(value, str) and re.fullmatch(r"\$[0-9a-f]+(:[\w-]+)+", value) and seen < 10:
            row, *path = value[1:].split(":")
            value = self.rows.get(row)
            for p in path:
                if isinstance(value, list):
                    value = value[3] if p == "props" else value[int(p)]
                else:
                    value = value[p]
            seen += 1
        return value

    def find(self, *keys):
        """Every dict on the page that has all of `keys`."""
        def walk(node):
            if isinstance(node, dict):
                if all(k in node for k in keys):
                    yield node
                for v in node.values():
                    yield from walk(v)
            elif isinstance(node, list):
                for v in node:
                    yield from walk(v)
        for row in self.rows.values():
            yield from walk(row)

    def elements(self, tag):
        """Every rendered element <tag> on the page, as [key, props]."""
        def walk(node):
            if isinstance(node, list):
                if len(node) == 4 and node[0] == "$" and node[1] == tag and isinstance(node[3], dict):
                    yield node[2], node[3]
                for v in node:
                    yield from walk(v)
            elif isinstance(node, dict):
                for v in node.values():
                    yield from walk(v)
        for row in self.rows.values():
            yield from walk(row)

    def texts(self, node, depth=0):
        """The texts and numbers shown inside a rendered element, in reading order."""
        if isinstance(node, list):
            if len(node) == 4 and node[0] == "$" and isinstance(node[3], dict):
                node = node[3]
            else:
                for v in node:
                    yield from self.texts(v, depth)
                return
        if isinstance(node, dict):
            if isinstance(node.get("dateString"), str):
                yield node["dateString"]
            yield from self.texts(node.get("children"), depth)
        elif isinstance(node, str):
            ref = re.fullmatch(r"\$L?([0-9a-f]+)", node)
            if ref:  # a part of the element that was sent as its own row
                if ref.group(1) in self.rows and depth < 20:
                    yield from self.texts(self.rows[ref.group(1)], depth + 1)
            elif not node.startswith("$"):
                yield node
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            yield node


def club_code(team):
    return str(team["clubId"])


# ---------- the running season ----------
def calendar():
    """-> (season, clubs, games) of the season acb.com is showing now.
    clubs: club id -> {"id", "short", "name", "fullName", "city", "country", "crest"}
    games: [{"code", "round", "utc", "home", "away", "played", "score", "phase"}], phase "RS" or "PO"
    """
    page = Page(f"{SITE}/calendario")
    data = next(d for d in page.find("teams", "rounds") if d["rounds"] and "matches" in d["rounds"][0])
    season = str(next(page.find("currentEditionId"))["currentEditionId"] + 1935)
    clubs = {}
    for t in data["teams"]:
        t = page.resolve(t)
        code = club_code(t)
        name, city, country = CLUBS.get(code, (t["fullName"], "", "Spain"))
        clubs[code] = {"id": code, "short": t["abbreviatedName"], "name": name, "fullName": t["fullName"],
                       "city": city, "country": country, "crest": t.get("logo") or ""}
    games = []
    for rnd in data["rounds"]:
        for m in rnd["matches"]:
            m = page.resolve(m)
            played = m["matchStatus"] == "FINALIZED"
            games.append({
                "code": m["id"],
                "round": rnd["roundNumber"],
                "utc": m.get("startDateTime") or "",
                "home": club_code(page.resolve(m["homeTeam"])),
                "away": club_code(page.resolve(m["awayTeam"])),
                "played": played,
                "score": [m["homeTeamScore"], m["awayTeamScore"]] if played else None,
                "phase": "PO" if rnd.get("subphase") else "RS",
                "status": m["matchStatus"],
            })
    return season, clubs, games


def club_links(season=None):
    """club id -> the club's page name on acb.com ('real-madrid-9'), for the clubs of a season"""
    url = f"{SITE}/equipos" + (f"?editionId={edition(season)}" if season else "")
    return {m.group(2): m.group(1) for m in re.finditer(r'href="/es/liga/equipos/([a-z0-9-]+-(\d+))["?]', fetch(url))}


def roster(link):
    """-> (head coach, players) of a club today; players: [{"code", "name", "num", "pos", "nat"}]"""
    page = Page(f"{SITE}/equipos/{link}/plantilla")
    coach, players = "", {}
    for d in page.find("coach", "licensing"):
        c = page.resolve(d["coach"])
        if c.get("gameRole") == "Entrenador":
            coach = c.get("nickname") or f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
    for d in page.find("player", "licensing"):
        p = page.resolve(d["player"])
        if d.get("isLicenseActive") is False:
            continue
        nat = (d.get("nationalityCountry") or "").strip()
        players[str(p["id"])] = {
            "code": str(p["id"]),
            "name": player_name(p),
            "num": p.get("shirtNumber") or "",
            "pos": POSITIONS.get(p.get("gameRole"), p.get("gameRole") or ""),
            "nat": COUNTRIES.get(nat, nat),
        }
    return coach, list(players.values())


def player_name(p):
    return (p.get("nickname") or f"{p.get('firstName', '')} {p.get('lastName', '')}").strip()


def standings():
    """-> club id -> [position, games played, games won], in the league's official order"""
    page = Page(f"{SITE}/clasificacion")
    out = {}
    for d in page.find("position", "matchesPlayed", "wins", "team"):
        out[club_code(page.resolve(d["team"]))] = [d["position"], d["matchesPlayed"], d["wins"]]
    return out


# ---------- box scores ----------
# a team's totals in a game, in this order (model.possessions and the team statistics rely on it)
TOTAL_KEYS = ("twoPointersMade", "twoPointersAttempted", "threePointersMade", "threePointersAttempted",
              "freeThrowsMade", "freeThrowsAttempted", "offRebounds", "defRebounds", "turnovers", "points",
              "assists", "steals", "blocks")
# a player's line: our name -> acb.com's name
PLAYER_KEYS = {"pts": "points", "reb": "totalRebounds", "ast": "assists", "stl": "steals", "blk": "blocks",
               "pir": "rating", "m2": "twoPointersMade", "a2": "twoPointersAttempted", "m3": "threePointersMade",
               "a3": "threePointersAttempted", "mf": "freeThrowsMade", "af": "freeThrowsAttempted",
               "tov": "turnovers", "pm": "plusMinus"}


def seconds(play_time):
    """'23:19' -> 1399"""
    try:
        m, s = (play_time or "0:0").split(":")[-2:]
        return int(m) * 60 + int(s)
    except ValueError:
        return 0


def box(code):
    """One game's statistics page, cut down to what the site and the model use:
    {"played", "utc", "score": [home, away], "quarters": [[home...], [away...]], "arena",
     "home"/"away": {"club", "coach", "total": [TOTAL_KEYS...],
                     "players": [{"code", "name", "num", "pos", "secs", "pts", "reb", ...PLAYER_KEYS}]}}
    """
    page = Page(f"{LIVE}/x-{code}/estadisticas")
    head = next(page.find("quarterScores", "teams"))
    out = {
        "played": head["status"] == "FINALIZED",
        "utc": head.get("start") or "",
        "score": [head.get("currentHomeScore"), head.get("currentAwayScore")],
        "quarters": [[q[side] for q in head["quarterScores"]] for side in ("home", "away")],
        "arena": next((d["arena"] or "" for d in page.find("arena", "teamBoxscores")), ""),
    }
    sides = {club_code(page.resolve(head["teams"][side])): side for side in ("home", "away")}
    for d in page.find("statsByPeriods", "team"):
        side = sides.get(club_code(page.resolve(d["team"])))
        game = next((page.resolve(p["stats"]) for p in d["statsByPeriods"] if p["quarter"] == 0), None)
        if not side or not game or side in out:
            continue
        players = []
        for line in game["players"]:
            p = page.resolve(line["player"])
            players.append({"code": str(p["id"]), "name": player_name(p), "num": p.get("shirtNumber") or "",
                            "pos": POSITIONS.get(p.get("gameRole"), p.get("gameRole") or ""),
                            "secs": seconds(line.get("playTime")),
                            **{k: line.get(api) or 0 for k, api in PLAYER_KEYS.items()}})
        out[side] = {"club": club_code(page.resolve(d["team"])), "coach": d.get("headCoach") or "",
                     "total": [game["total"].get(k) or 0 for k in TOTAL_KEYS], "players": players}
    if "home" not in out or "away" not in out:
        raise ValueError(f"no box score found for game {code}")
    return out


# ---------- finished seasons ----------
def _club_games(link, season):
    """A club's games in one season, from its 'partidos' page -> (the club's short code that season, rows)."""
    page = Page(f"{SITE}/equipos/{link}/partidos?editionId={edition(season)}")
    first, last = f"{season}-08-01", f"{int(season) + 1}-07-31"
    rows = []
    for key, props in page.elements("tr"):
        if not (isinstance(key, str) and key.isdigit()):
            continue
        cells = list(page.texts(props))
        dates = [c for c in cells if isinstance(c, str) and re.match(r"\d{4}-\d\d-\d\dT", c)]
        nums = [c for c in cells if isinstance(c, (int, float))]
        words = [c for c in cells if isinstance(c, str) and c not in dates and c != "-"]
        # round (regular season only), "Liga Regular", "LR", date, home name, home code, home points,
        # away points, away name, away code
        if not dates or not first <= dates[0][:10] <= last or len(nums) < 2 or len(words) < 6:
            continue
        rows.append({"code": int(key), "round": int(nums[0]) if len(nums) > 2 else 0, "utc": dates[0],
                     "phase": words[1], "home": words[3], "away": words[5], "score": [int(nums[-2]), int(nums[-1])]})
    own = Counter(r[side] for r in rows for side in ("home", "away")).most_common(1)
    return (own[0][0] if own else ""), rows


def past_games(season):
    """Every played game of a finished season (regular season and playoffs), same shape as calendar()'s games.
    Each game is listed on both clubs' pages; the club whose page shows it as a home game is the home team."""
    links = club_links(season)

    def one(item):
        return item[0], _club_games(item[1], season)

    with ThreadPoolExecutor(3) as pool:
        pages = dict(pool.map(one, links.items()))
    games = {}
    for club, (own, rows) in pages.items():
        for r in rows:
            g = games.setdefault(r["code"], {"code": r["code"], "round": r["round"], "utc": r["utc"], "played": True,
                                             "score": r["score"], "phase": "RS" if r["phase"] == "LR" else "PO",
                                             "home": None, "away": None})
            g["home" if r["home"] == own else "away"] = club
    out = sorted((g for g in games.values() if g["home"] and g["away"]), key=lambda g: (g["utc"], g["code"]))
    if len(out) != len(games):
        print(f"  warning: {len(games) - len(out)} games of {season} were found on one club's page only, skipped")
    return out


def past_players(season):
    """-> [[player code, club id, games, seconds played, total PIR]] for a finished season"""
    def one(item):
        club, link = item
        page = Page(f"{SITE}/equipos/{link}/estadisticas?editionId={edition(season)}")
        lines = {}
        for d in page.find("player", "totals"):
            p, t = page.resolve(d["player"]), page.resolve(d["totals"])
            if isinstance(p, dict) and isinstance(t, dict) and t.get("numGames"):
                lines[str(p["id"])] = [str(p["id"]), club, t["numGames"], t.get("timePlayed") or 0, t.get("rating") or 0]
        return list(lines.values())

    with ThreadPoolExecutor(3) as pool:
        return [line for lines in pool.map(one, club_links(season).items()) for line in lines]
