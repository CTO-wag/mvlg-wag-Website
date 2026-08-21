/* Puppeteer soll bei "npm install" KEINEN eigenen Chromium herunterladen.
 *
 * Der Download ist rund 200 MB und bricht in Schulnetzen oder hinter einem
 * Virenscanner gerne mittendrin ab. Zurueck bleibt ein halber Ordner, und
 * jedes weitere "npm install" scheitert dann mit
 *   "The browser folder exists but the executable is missing"
 * weil Puppeteer den vorhandenen Ordner fuer eine fertige Installation haelt.
 *
 * Statt dessen benutzt dienst.js den Browser, der auf jedem Windows-Rechner
 * ohnehin liegt (Edge oder Chrome) - siehe browserPfad() in dienst.js.
 * Wer doch einen eigenen Chromium will:
 *   npx puppeteer browsers install chrome
 * Der wird dann automatisch bevorzugt.
 */
module.exports = {
  skipDownload: true,
};
