"""
Download real Liga Endesa (ACB) data from acb.com and write js/data.js.

    python update_data.py            # the season acb.com is showing now
    python update_data.py --if-new   # quick check: only update when a game has finished since last time

Only uses the Python standard library. Re-run whenever you want fresh
results, standings, rosters and stats.
"""

import json
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import acb
import model

OUT = Path(__file__).parent / "js" / "data.js"
# Box scores of finished games never change, so they are saved here and not downloaded again.
CACHE = Path(__file__).parent / ".cache"


def get_box(season, game):
    file = CACHE / season / f"box_{game['code']}.json"
    if file.exists():
        return json.loads(file.read_text(encoding="utf-8"))
    data = acb.box(game["code"])
    # the statistics page can be a few minutes behind the result: only keep it once it is final
    if data["played"] and data["score"] == game["score"]:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(data), encoding="utf-8")
    return data


def new_results(raw_games):
    """True if acb.com has a finished game (or a changed score) that js/data.js doesn't have yet."""
    m = re.search(r"^const GAMES = (.*);$", OUT.read_text(encoding="utf-8"), re.M) if OUT.exists() else None
    if not m:
        return True
    have = {g["code"]: g["score"] for g in json.loads(m.group(1)) if g["score"]}
    now = {g["code"]: g["score"] for g in raw_games if g["played"]}
    return have != now


def main():
    # ---- Clubs and games ----
    season, teams, raw_games = acb.calendar()
    print(f"Season {season}")
    if "--if-new" in sys.argv and not new_results(raw_games):
        print("  no newly finished games, nothing to do")
        return
    for t in teams.values():
        t.update(coach="", players={})
    print(f"  {len(teams)} teams")

    # ---- Rosters ----
    links = acb.club_links()

    def roster(code):
        return code, acb.roster(links[code])

    with ThreadPoolExecutor(4) as pool:
        for code, (coach, players) in pool.map(roster, [c for c in teams if c in links]):
            teams[code]["coach"] = coach
            teams[code]["players"] = {p["code"]: p for p in players}

    roster = {code: set(t["players"]) for code, t in teams.items()}  # current squads, for the model

    # ---- Games ----
    # a game without a date yet is listed after the others of its round
    last_date = max((g["utc"] for g in raw_games if g["utc"]), default="")
    for g in raw_games:
        g["utc"] = g["utc"] or max((o["utc"] for o in raw_games if o["round"] == g["round"]), default="") or last_date
    raw_games.sort(key=lambda g: (g["phase"] != "RS", g["round"], g["utc"]))
    played = [g for g in raw_games if g["played"]]
    print(f"  {len(raw_games)} games, {len(played)} played")

    # ---- Box scores for played games ----
    def box(game):
        return game["code"], get_box(season, game)

    with ThreadPoolExecutor(4) as pool:
        boxes = dict(pool.map(box, played))

    # where each team plays at home, for games still to come
    arena = {}
    for g in sorted(played, key=lambda g: g["utc"]):
        if boxes[g["code"]]["arena"]:
            arena[g["home"]] = boxes[g["code"]]["arena"]

    totals = defaultdict(lambda: defaultdict(float))  # (team, player) -> summed stats
    team_totals = defaultdict(lambda: defaultdict(float))  # team -> summed team stats
    games = []
    for g in raw_games:
        home, away = g["home"], g["away"]
        game = {
            "code": g["code"],
            "round": g["round"],
            "date": acb.madrid_time(g["utc"]),
            "utc": g["utc"],
            "venue": arena.get(home, ""),
            "home": home,
            "away": away,
            "score": None,
        }
        if g["phase"] != "RS":
            game["phase"] = g["phase"]  # playoffs: not in the standings
        if g["played"]:
            b = boxes[g["code"]]
            game["venue"] = b["arena"] or game["venue"]
            game["score"] = g["score"]
            game["quarters"] = b["quarters"]
            game["box"] = {}
            for side, team in (("home", home), ("away", away)):
                if not teams[team]["coach"]:
                    teams[team]["coach"] = b[side]["coach"]
                lines = []
                for p in b[side]["players"]:
                    line = {**p, "min": round(p["secs"] / 60, 1)}
                    # the player's code comes last: it links the line to his page on the site
                    lines.append([line[k] for k in ("name", "num", "min", "pts", "reb", "ast", "stl", "blk", "pir")]
                                 + [p["code"]])
                    if p["secs"] > 0:
                        t = totals[(team, p["code"])]
                        t["gp"] += 1
                        for k in ("min", "pts", "reb", "ast", "stl", "blk", "pir",
                                  "m2", "a2", "m3", "a3", "mf", "af", "tov", "pm"):
                            t[k] += line[k]
                        # players who left the club still show up with their stats
                        teams[team]["players"].setdefault(p["code"], {
                            "code": p["code"], "name": p["name"], "num": p["num"], "pos": p["pos"], "nat": "",
                        })
                game["box"][side] = lines
            # team totals, own and opponent's, for the team statistics page
            ct = model.compact_totals(b)
            poss = (model.possessions(ct["home"]) + model.possessions(ct["away"])) / 2
            for side, team, other in (("home", home, "away"), ("away", away, "home")):
                tt = team_totals[team]
                tt["gp"] += 1
                tt["poss"] += poss
                for i, v in enumerate(ct[side]):
                    tt[f"own{i}"] += v
                for i, v in enumerate(ct[other]):
                    tt[f"opp{i}"] += v
                for k, v in zip(("ast", "stl", "blk"), b[side]["total"][10:13]):
                    tt[k] += v
        games.append(game)

    # ---- Per-game averages ----
    for team in teams.values():
        for code, pl in team["players"].items():
            t = totals.get((team["id"], code))
            gp = int(t["gp"]) if t else 0
            pl["gp"] = gp
            for k in ("min", "pts", "reb", "ast", "stl", "blk", "pir", "tov", "pm"):
                pl[k] = round(t[k] / gp, 1) if gp else 0
            # shooting totals [2PM, 2PA, 3PM, 3PA, FTM, FTA]; the site turns them into percentages
            pl["sh"] = [int(t[k]) for k in ("m2", "a2", "m3", "a3", "mf", "af")] if gp else [0] * 6
        team["players"] = sorted(team["players"].values(), key=lambda p: (-p["gp"], -p["pts"], p["name"]))

    # ---- Team statistics ----
    # index into acb.TOTAL_KEYS: 0 2PM, 1 2PA, 2 3PM, 3 3PA, 4 FTM, 5 FTA, 6 OREB, 7 DREB, 8 TOV, 9 PTS
    def pct(made, att):
        return round(100 * made / att, 1) if att else 0

    team_stats = {}
    for code, tt in team_totals.items():
        n, poss = tt["gp"], tt["poss"]
        o = [tt[f"own{i}"] for i in range(10)]
        p = [tt[f"opp{i}"] for i in range(10)]
        team_stats[code] = {
            "gp": int(n),
            "pts": round(o[9] / n, 1), "opp": round(p[9] / n, 1),
            "ortg": round(100 * o[9] / poss, 1), "drtg": round(100 * p[9] / poss, 1),
            "net": round(100 * (o[9] - p[9]) / poss, 1), "pace": round(poss / n, 1),
            "p2": pct(o[0], o[1]), "p3": pct(o[2], o[3]), "ft": pct(o[4], o[5]),
            "efg": pct(o[0] + 1.5 * o[2], o[1] + o[3]), "oefg": pct(p[0] + 1.5 * p[2], p[1] + p[3]),
            "reb": round((o[6] + o[7]) / n, 1), "orebp": pct(o[6], o[6] + p[7]),
            "ast": round(tt["ast"] / n, 1), "tov": round(o[8] / n, 1),
            "stl": round(tt["stl"] / n, 1), "blk": round(tt["blk"] / n, 1),
        }

    # ---- Prediction model (see model.py) ----
    print("  fitting prediction model...")
    prior = model.preseason_prior(season, roster)
    model_games = model.simplify_games(raw_games)
    by_code = {g["code"]: g for g in games}
    for raw in played:
        # what the model would have said before this game (only earlier games known)
        day = model.parse_date(raw["utc"]).replace(hour=0, minute=0)
        r = model.fit(model_games, teams, prior, as_of=day)
        hp, ap, p = r.predict(raw["home"], raw["away"])
        by_code[raw["code"]]["pred"] = [round(hp), round(ap), round(p, 3)]
    ratings = model.fit(model_games, teams, prior)

    # who plays: each team's regulars, their value, and who missed the latest game
    # and how fast each team plays (possessions per game), for predicted totals
    av = model.Availability(model.history_player_totals(model.previous(season)))
    pace = model.Pace()
    for raw in sorted(played, key=lambda g: g["utc"]):
        b = model.compact_box(boxes[raw["code"]])
        av.add(raw["home"], b["home"])
        av.add(raw["away"], b["away"])
        pace.add(raw["home"], raw["away"], model.compact_totals(boxes[raw["code"]]))
    model_json = ratings.to_json(teams)
    # season forecast: play out the rest of the regular season (model.simulate_season)
    rs = [g for g in raw_games if g["phase"] == "RS"]
    forecast = model.simulate_season(
        ratings, teams,
        [(g["home"], g["away"], g["score"][0] - g["score"][1]) for g in rs if g["played"]],
        [(g["home"], g["away"]) for g in rs if not g["played"]])
    # team -> [chance of finishing 1-8, chance of finishing in the last two, expected final wins]
    model_json["forecast"] = {t: [round(v[0], 3), round(v[1], 3), round(v[2], 1)] for t, v in forecast.items()}
    model_json["forecastGames"] = len(rs) * 2 // len(teams) if teams else 0
    model_json["pace"] = {t: round(pace.team(t), 2) for t in teams}
    # Official regular-season order (the league's tie-breakers: head-to-head and so on), which the site
    # can't always work out from wins and point difference alone.
    official = None
    rs_rounds = [g["round"] for g in played if g["phase"] == "RS"]
    if rs_rounds:
        try:
            official = {"round": max(rs_rounds), "teams": acb.standings()}
        except Exception as e:  # the site then falls back to its own order
            print(f"  official standings not available ({e})")

    # teams that weren't in last season's Liga Endesa (promoted): their starting rating is only a rough guess
    new_teams = sorted(set(teams) - model.season_teams(model.history_games(model.previous(season))))

    availability = {}
    for code in teams:
        regs = av.regulars(code)
        last = av.last_played.get(code, set())
        availability[code] = [
            # [player, PIR per game, missed the latest game, no longer on the roster]
            [c, round(v, 1), c not in last, c not in roster[code]]
            for c, v in sorted(regs.items(), key=lambda x: -x[1])
        ]

    season_name = f"{season}-{(int(season) + 1) % 100:02d}"
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    js = (
        "// Generated by update_data.py from acb.com — do not edit by hand.\n"
        f"const SEASON = {json.dumps(season_name)};\n"
        f"const UPDATED = {json.dumps(updated)};\n"
        f"const TEAMS = {json.dumps(sorted(teams.values(), key=lambda t: t['name']), ensure_ascii=False)};\n"
        f"const GAMES = {json.dumps(games, ensure_ascii=False, separators=(',', ':'))};\n"
        f"const MODEL = {json.dumps(model_json)};\n"
        f"const NEW_TEAMS = {json.dumps(new_teams)};\n"
        f"const OFFICIAL = {json.dumps(official)};\n"
        f"const TEAM_STATS = {json.dumps(team_stats, separators=(',', ':'))};\n"
        f"const AVAILABILITY = {json.dumps(availability, separators=(',', ':'))};\n"
    )
    OUT.write_text(js, encoding="utf-8")
    print(f"Wrote {OUT} ({len(js) // 1024} KB)")


if __name__ == "__main__":
    main()
