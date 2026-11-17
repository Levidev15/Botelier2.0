// Test-only CSS fixtures for Next 14's NEXT_FONT_GOOGLE_MOCKED_RESPONSES hook.
// All four app font requests use the already-installed Next package's bundled
// Noto Sans file as a local stand-in; no Google Fonts request is made.
const path = require("node:path");

const nextPackage = require.resolve("next/package.json");
const bundledFont = path.join(
  path.dirname(nextPackage),
  "dist",
  "compiled",
  "@vercel",
  "og",
  "noto-sans-v27-latin-regular.ttf",
);

function fontCss(family, style, weight) {
  return `/* latin */\n@font-face {\n  font-family: '${family}';\n  font-style: ${style};\n  font-weight: ${weight};\n  src: url(${bundledFont}) format('truetype');\n}\n`;
}

module.exports = Object.freeze({
  "https://fonts.googleapis.com/css2?family=Inter:wght@100..900&display=swap":
    fontCss("Inter", "normal", "100 900"),
  "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;500;600;700&display=swap":
    fontCss("Cormorant Garamond", "normal", "300 700"),
  "https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&display=swap":
    fontCss("Syne", "normal", "400 800"),
  "https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,100..1000;1,100..1000&display=swap":
    [
      fontCss("DM Sans", "normal", "100 1000"),
      fontCss("DM Sans", "italic", "100 1000"),
    ].join("\n"),
});
