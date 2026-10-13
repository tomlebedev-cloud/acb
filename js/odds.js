// Bookmaker odds published with the site (winner, overtime included), used when you
// haven't typed your own for a game on the Betting page. Update by hand before each round:
// game code -> { ml: [home, away], hcp: [home line, home, away], tot: [line, over, under] }
// The game code is the number at the end of the game's address on the site (#game/105401).
const BOOK_ODDS = {
  source: "",   // the bookmaker's name, e.g. "TopSport"
  taken: "",    // the day the odds were taken, e.g. "2026-10-11"
  games: {
  },
};
