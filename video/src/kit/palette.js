/** Colours: the app's neo-brutal tokens (web/src/styles.css) plus a few for the 3D sets. */
export const P = {
  // the app
  paper: "#fff4dc",
  ink: "#111111",
  yellow: "#ffd23f",
  pink: "#ff8fb4",
  blue: "#3a6bff",
  lime: "#b6f25b",
  cyan: "#7ae3ff",
  orange: "#ff9f1c",
  red: "#ff5a5a",
  muzzle: "#ff9fbd",
  horn: "#ffe7b0",
  // people
  skin: ["#f6c9a4", "#e8b48a", "#c98d5f", "#8d5a3b", "#f2d1b8"],
  hair: { brown: "#4a2b1a", black: "#1b1714", blond: "#e3c16f", ginger: "#c0612b", grey: "#b9b4ad" },
  // sets
  snow: "#f4f8ff",
  night: "#0d1530",
  wood: "#a8693a",
  woodDark: "#6f4022",
  sauna: "#c98a4b",
  steel: "#c9d1d9",
  tile: "#eef3f6",
  grass: "#7fbf4d",
  barn: "#c8322f",
  cream: "#fff8e6",
  milk: "#fbfdff",
  // Valio-like pack colours (our own approximations, no logos)
  valio: "#1f4fbf",
  eila: "#5ab4f0",
  voi: "#f5c542",
  profeel: "#1b1f3a",
  aura: "#2b6cb0",
  olter: "#e85d2a",
};

/** Strip the # for three.js and canvas use. */
export const hex = (c) => Number.parseInt(c.slice(1), 16);
