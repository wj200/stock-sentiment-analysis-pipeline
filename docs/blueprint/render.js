// Renders blueprint.html -> ../sentinel-telegram-bot-blueprint.pdf using headless Chromium.
// Mermaid diagrams are rendered offline from a locally-installed mermaid bundle.
//
// Setup (once):   npm install            (installs playwright-core + mermaid)
//                 cp node_modules/mermaid/dist/mermaid.min.js ./mermaid.min.js
// Render:         node render.js
//
// If Playwright's bundled Chromium is unavailable, set CHROME_SHELL to a
// chrome/chromium/chrome-headless-shell binary path.
const { chromium } = require("playwright-core");
const path = require("path");
const fs = require("fs");

const SHELL = process.env.CHROME_SHELL || null; // null => use playwright's bundled browser
const HTML = path.resolve(__dirname, "blueprint.html");
const OUT = process.argv[2] || path.resolve(__dirname, "..", "sentinel-telegram-bot-blueprint.pdf");

(async () => {
  const launchOpts = { args: ["--no-sandbox"] };
  if (SHELL) launchOpts.executablePath = SHELL;
  const browser = await chromium.launch(launchOpts);
  const page = await browser.newPage();
  await page.goto("file://" + HTML, { waitUntil: "load" });

  const report = await page.evaluate(async () => {
    if (!window.mermaid) return { ok: false, msg: "mermaid.min.js not found next to blueprint.html" };
    const fails = [];
    const blocks = [...document.querySelectorAll("pre.mermaid")];
    for (let i = 0; i < blocks.length; i++) {
      try {
        const { svg } = await window.mermaid.render("mmd_" + i, blocks[i].textContent);
        const w = document.createElement("div");
        w.className = "mermaid-rendered";
        w.innerHTML = svg;
        blocks[i].replaceWith(w);
      } catch (e) { fails.push("diagram " + i + ": " + (e.message || e)); }
    }
    return { ok: fails.length === 0, fails, count: blocks.length };
  });
  console.log("mermaid:", JSON.stringify(report));

  await page.waitForTimeout(400);
  await page.emulateMedia({ media: "print" });
  await page.pdf({
    path: OUT, format: "A4", printBackground: true, displayHeaderFooter: true,
    margin: { top: "16mm", bottom: "16mm", left: "14mm", right: "14mm" },
    headerTemplate: `<div style="font-size:7px;color:#9aa4b2;width:100%;padding:0 14mm;font-family:Helvetica,Arial,sans-serif;">
        <span style="float:left;letter-spacing:.5px;">SENTINEL — STOCK SENTIMENT & MARKET-EVENT TELEGRAM BOT</span>
        <span style="float:right;">Technical Blueprint</span></div>`,
    footerTemplate: `<div style="font-size:7px;color:#9aa4b2;width:100%;padding:0 14mm;font-family:Helvetica,Arial,sans-serif;">
        <span style="float:left;">Design reference — verify live figures &amp; keys before relying on any number.</span>
        <span style="float:right;">Page <span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
  });
  await browser.close();
  console.log("wrote", OUT, fs.statSync(OUT).size, "bytes");
  if (!report.ok) process.exit(2);
})().catch((e) => { console.error("FATAL", e.message); process.exit(1); });
