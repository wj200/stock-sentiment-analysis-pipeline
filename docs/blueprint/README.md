# Sentinel Blueprint (source)

`blueprint.html` is the canonical source for the project's technical blueprint.
The rendered PDF lives at `../sentinel-telegram-bot-blueprint.pdf` and is the
document referenced throughout the build.

Section 13 (Development Roadmap) carries a status pill on every milestone
(`TO BUILD` / `BUILT`). As milestones are completed, flip the pill in
`blueprint.html` and re-render so the PDF stays in sync with the code.

## Regenerate the PDF

```bash
cd docs/blueprint
npm install                 # installs playwright-core + mermaid, copies mermaid.min.js locally
npx playwright install chromium   # once, if the bundled browser is missing
npm run render              # writes ../sentinel-telegram-bot-blueprint.pdf
```

If you already have a Chrome/Chromium binary, skip the browser download and point at it:

```bash
CHROME_SHELL=/path/to/chrome node render.js
```

`node_modules/`, `mermaid.min.js`, and the intermediate render are gitignored;
only `blueprint.html`, `render.js`, this README, and the final PDF are tracked.
