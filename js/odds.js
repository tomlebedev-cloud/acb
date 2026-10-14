// Bookmaker odds published with the site (winner, overtime included), used when you
// haven't typed your own for a game on the Betting page. Update by hand before each round:
// game code -> { ml: [home, away], hcp: [home line, home, away], tot: [line, over, under] }
// The game code is the number at the end of the game's address on the site (#game/105401).
const BOOK_ODDS = {
  source: "TopSport",
  taken: "2026-10-14",
  games: {
    // round 2, postponed game (taken 2026-10-14)
    105384: { ml: [1.26, 3.95] },  // Joventut – Andorra
    // round 4 (taken 2026-10-14)
    105402: { ml: [2.24, 1.53] },  // Manresa – Unicaja
    105403: { ml: [1.62, 2.07] },  // Andorra – Breogán
    105404: { ml: [1.44, 2.45] },  // Burgos – Obradoiro
    105405: { ml: [1.44, 2.45] },  // Girona – Coruña
    105406: { ml: [1.34, 2.80] },  // Zaragoza – Lleida
    105407: { ml: [1.11, 4.90] },  // Real Madrid – Bilbao Basket
    105408: { ml: [1.19, 3.85] },  // Valencia Basket – UCAM Murcia
    105409: { ml: [1.53, 2.24] },  // Tenerife – Baskonia
    105410: { ml: [1.62, 2.07] },  // Joventut – Barça
  },
};
