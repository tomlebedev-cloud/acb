# ACB Hub

A simple Liga Endesa (Spanish ACB) basketball website with real data: teams, players, statistics, schedule and
predictions. English or Lithuanian (EN / LT switch in the header, remembered by the browser).
Plain HTML, CSS and JavaScript, plus Python scripts that download the data.
It is the sister site of the Euroleague Hub and works the same way.

## Pages

| Page | What it shows |
|------|---------------|
| **Home** | Latest results, next games (with predicted scores), standings, stat leaders |
| **Standings** | Full table: games, wins, losses, points for/against, +/-, last 5 games, and the season forecast |
| **Stats** | Players: per-game averages, shooting percentages (2P%, 3P%, FT%), turnovers and +/−. Teams: points per 100 possessions scored and allowed, pace, eFG%, rebounds and more. Click a column to sort |
| **Teams** | All 18 teams. Click one to see coach, team statistics with league rank, roster with season averages, and all 34 games |
| **Player** | Click any player's name: season averages with league rank, shooting, and his game log |
| **Schedule** | Go round by round through all 34 rounds, filter by team |
| **Game** | Played: quarter scores and full box score for both teams. Upcoming: prediction, earlier meetings, both rosters |
| **Predictions** | Win probability and predicted score for the next two rounds, plus a "pick any two teams" tool |
| **Betting** | Next round simulated 40,000 times per game; compare with bookmaker odds, find value bets, keep a bet log |
| **Ticket** | Suggested ticket for the next round with the reasons for each pick: value singles, a combo only when every leg has value, and the minimum odds each pick needs |

## Run it

Open `index.html` in your browser (double-click it). If your browser blocks it, serve the folder:

```
python -m http.server 8001
```

and open http://localhost:8001.

## Updating the data

```
python update_data.py
```

This reads everything from the public pages of acb.com and writes `js/data.js`: clubs, rosters, coaches,
all games, and box scores of every played game. Player season averages are calculated from those box
scores. Run it after each round to get new results.

- acb.com has no open API. `acb.py` downloads the same pages a browser does and takes the data that is
  already inside them. If acb.com changes how its pages are built, `acb.py` is the only file to fix.
- Finished box scores are cached in `.cache/` so later runs only download new games.
- If the site is busy, the script waits automatically and continues.
- It always shows the season acb.com is showing now.

Requires Python 3 (standard library only, nothing to install).

### Automatic daily update

On GitHub, the workflow in `.github/workflows/update-data.yml` keeps `js/data.js` current and the website
(GitHub Pages) redeploys by itself after every change:

- **After games:** every half hour from 11:00 to 23:00 UTC it runs `update_data.py --if-new`, which opens
  the calendar page once to see whether a game has finished since the last update and only then does the
  full update.
- **Every morning** (05:23 UTC) it runs a full update, which also picks up roster and schedule changes.

GitHub starts scheduled jobs late when it is busy (sometimes by hours), so results can take a while to
appear. To update right away: **Actions → Update ACB data → Run workflow**.

Notes: GitHub pauses scheduled workflows in repositories with no activity for 60 days (e.g. in the
summer off-season); re-enable it from the Actions tab. The workflow has not run on GitHub yet: if acb.com
refuses requests from GitHub's servers, run `python update_data.py` on your own computer and push.

## How predictions work

The model lives in `model.py` and runs inside `update_data.py`; the website only reads its output.
It is the Euroleague Hub model with every setting measured again on Liga Endesa seasons.

- **Attack and defence ratings.** Each team gets an attack rating (points scored vs. an average team) and a
  defence rating (points allowed), estimated from all games with a ridge regression, so they are
  **adjusted for opponent strength**.
- **Preseason starting point.** Ratings begin at 55% of last season's level, adjusted for **summer
  transfers**: the last-season Liga Endesa PIR of players who arrived minus players who left, compared with
  the league's average change (1 point per 1000 PIR). Promoted teams start at the usual level of promoted
  teams, about 6.5 points per game below average. This starting point is worth about 30 games of evidence,
  so early-season predictions lean on it and this season's results gradually take over.
- **Game prediction.** Predicted score = league average + attack + opponent's defence, with +2.4 points for
  the home team. The margin becomes a win chance with a logistic curve.

### Accuracy (backtested)

`backtest.py` replays past seasons game by game, predicting each game using only earlier games
(playoffs included):

| 2023-24 → 2025-26 (978 games) | Winner right | Log loss | Brier | Margin error |
|---|---|---|---|---|
| Always pick the home team | 59.7% | | | |
| Simple model (season points per game) | 66.9% | 0.608 | 0.210 | 9.9 pts |
| **Current model** | **70.1%** | **0.576** | **0.197** | **9.5 pts** |

Lower log loss / Brier means better win probabilities. With the Euroleague Hub's settings the same model
scored 68.8% and 0.595, so tuning for this league was worth it. Rating settings were tuned on 2023-24 and
2024-25 and checked on 2025-26 (log loss 0.614 → 0.604 on that unseen season); the probability scale was
fitted on all three seasons. Run `python backtest.py` to reproduce, `python backtest.py --tune` to search
settings, `python backtest.py --promoted` to see how promoted teams did.

The site also shows the model's live track record for the current season round by round (next to
"home team won" and the bookmaker's favourite, with the most confident miss of each round), and on every
finished game what it predicted before tip-off.

### Betting page

For each game of the next round the page simulates 40,000 final scores: margin and total are drawn
around the model's prediction with the spread measured on past seasons (`python backtest.py --spread`,
stored in `model.SIM`: margin ±12.1, total ±17.2 points). Ties go to overtime. From the simulations it
shows fair odds, a fair handicap and total, and model chances at nearby lines.

Type in a bookmaker's decimal odds (winner, handicap, total). The page removes the bookmaker margin,
blends the model's chance with the bookmaker's ("model weight", default 50%, because the bookmaker knows
about injuries and news), and shows the expected value and a stake (¼ Kelly, at most 2% of the bankroll).
Odds, settings and the bet log are saved in your browser only, separately from the Euroleague Hub's;
bet results settle automatically after the data update.

**Published odds.** `js/odds.js` holds bookmaker odds for the next round, typed in by hand from the
bookmaker's site; they fill in every game you haven't entered your own odds for, and count in the odds
history. It starts empty: fill it in before each round (the game code is the number at the end of the
game's address, e.g. `#game/105401`).

**Odds template.** "Copy template" gives a plain-text form with every game of the round
(`Win: home away`, `Hcp: line home away`, `Tot: line over under`); fill in the bookmaker's odds and paste it
back with "Apply" (or paste it into a chat).

**Odds history.** Every set of odds you type is saved with the model's chances at that moment (edits within
30 minutes replace the last save, later ones are added, so line moves are kept). Odds lock at tip-off. For
finished games the page compares the model's and the bookmaker's log loss per market, and the result of
1 € on every value bet. Everything stays in the browser; **Export / Import** moves it to another device
or keeps a backup.

**Line-ups.** Each team's three most productive regulars (PIR per game, early in the season leaning on
last season) are its key players. Every key player who doesn't play costs his team 1.2 points of margin.
Players who left the club are counted out; everyone else you tick yourself from the injury news. Players
who missed the team's latest game only get a "missed last game" hint: assuming they stay out made the
predictions worse on past seasons, because players often return. Measured with
`python backtest.py --absences` on 2023-24 to 2025-26 box scores (downloaded once into `.cache/history/`,
about 980 pages): the effect was 1.1–1.3 points in every season, but the overall gain is small and
uneven (better in two seasons, worse in one), and that is with the real line-ups known.

**Pace.** Adding points to the predicted total for fast teams helps in the EuroLeague but did not here
(`python backtest.py --pace`: total-points error 13.58 → 13.95, 13.67 → 13.69 and 13.41 → 13.38), so it is
switched off (`model.PACE`). Counting recent games more than old ones did not help either.

The model has a real edge over a coin flip on winners and margins, but totals are weak (mean error 13.5
points), and no test against real bookmaker odds has been done. Treat "value" as a signal to look closer,
not a sure thing.

### Season forecast

The Standings page also shows each team's chance of finishing in the top 8 (playoffs) or in the last two
places (relegation) and its expected final wins. `update_data.py` plays out the rest of the regular season
10,000 times (`model.simulate_season`): every game's margin is drawn around the model's prediction, and in
each run every team's strength is also shifted by a random 2.5 points, because the ratings are uncertain
themselves.

`python backtest.py --season` forecasts the last three seasons before round 1 and after rounds 4, 10 and 20
and compares with how they ended. Brier score for "finishes top 8": 0.112, against 0.247 for giving every
team the same chance. Calibration is good: teams given 50–70% made it 65% of the time, those given 70–90%
made it 84%. Final wins were off by 3.5 on average before round 1 and 1.5 after round 20. Ties are ordered
by point difference, not the official head-to-head rule.

Standings follow the official Liga Endesa order (downloaded with the data), which applies the league's
tie-breakers such as head-to-head results. If the official table is behind the results shown, the site
falls back to wins, then point difference. Only regular-season games count.

## Project structure

```
index.html       page layout and navigation
css/style.css    styles (light + dark mode)
js/app.js        pages, standings and stats
js/betting.js    betting page: simulation, odds comparison, bet log
js/ticket.js     ticket page: suggested bets and the reasons for them
js/odds.js       bookmaker odds for the next round (edit by hand)
js/data.js       generated data — don't edit by hand
update_data.py   builds js/data.js
acb.py           reads acb.com pages (clubs, games, box scores, rosters, standings)
model.py         prediction model
backtest.py      measures prediction accuracy on past seasons
```

Not affiliated with the ACB. Data and team logos belong to their owners.
