// Capture the current production UI from a disposable Docker stack.
// npm install -g playwright && playwright install chromium
// CALIPER_URL=http://localhost:18017 WS=sample-quadruped node scripts/shoot.mjs
// OUT selects the image directory; PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH selects Chromium.
// Use exported sample designs only: gallery cards, file names and terminal output
// are visible. This script never creates designs, builds CAD or starts agents.
// The backend and Butai must run inside Docker. Host resource status is omitted.
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); }
catch {
  const globalRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
  try { ({ chromium } = require(join(globalRoot, "playwright"))); }
  catch { ({ chromium } = require(join(globalRoot, "@playwright/test/node_modules/playwright"))); }
}
const cache = join(homedir(), ".cache/ms-playwright");
const discovered = existsSync(cache) ? readdirSync(cache).filter(n => /^chromium-\d+$/.test(n)).sort((a,b) => Number(b.split("-")[1]) - Number(a.split("-")[1])).map(n => join(cache,n,"chrome-linux64/chrome")).find(existsSync) : undefined;
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || discovered, args: ["--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader"] });
const base = process.env.CALIPER_URL || "http://localhost:8017";
const output = process.env.OUT || "docs/images";
const workspace = process.env.WS || "sample-quadruped";
mkdirSync(output, { recursive: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
async function capture(name) {
  await page.locator("[data-private]").evaluateAll(nodes => nodes.forEach(node => node.remove()));
  await page.screenshot({ path: join(output, `${name}.png`) });
  console.log(`${name}: ${join(output, `${name}.png`)}`);
}
async function openWorkspace() {
  await page.goto(`${base}/#/ws/${encodeURIComponent(workspace)}`);
  await page.getByRole("button", { name: "Simulate", exact: true }).waitFor();
  await page.locator("canvas").first().waitFor();
  await page.waitForTimeout(2500);
}
try {
  await page.goto(`${base}/#/`);
  await page.getByRole("heading", { name: "Designs", exact: true }).waitFor();
  await page.getByText(workspace, { exact: true }).waitFor();
  await page.waitForTimeout(1500);
  await page.setViewportSize({ width: 1000, height: 500 });
  await capture("hub");
  await page.setViewportSize({ width: 1600, height: 1000 });
  await openWorkspace();
  await capture("robot-workbench");
  const collapsedGroups = page.getByLabel("Model structure").getByRole("button", { expanded: false });
  while (await collapsedGroups.count()) await collapsedGroups.first().click();
  await capture("robot-parts");
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
  await page.getByRole("button", { name: "Pause", exact: true }).waitFor();
  await page.waitForTimeout(300);
  await capture("robot-sim");
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await page.getByTitle("Reset simulation").click();
  await page.getByRole("button", { name: "Library", exact: true }).click();
  await page.getByLabel("Find definition").waitFor();
  const component = page.getByLabel("Project library").getByRole("button", { name: "chassis", exact: true });
  if (await component.count()) {
    await component.click();
    await page.getByRole("button", { name: "Expand properties", exact: true }).click();
  }
  await page.waitForTimeout(1500);
  await capture("workspace-library");
  await page.getByRole("button", { name: "Files & Git", exact: true }).click();
  await page.getByRole("tab", { name: "Files", exact: true }).last().waitFor();
  await page.waitForTimeout(1000);
  await capture("workspace-files");
  await page.goto(`${base}/#/prototype`);
  await page.getByRole("heading", { name: "Live design", exact: true }).waitFor();
  await page.waitForTimeout(1000);
  await capture("workspace-prototype");
  if (errors.length) throw new Error(errors.join("\n"));
} finally {
  await browser.close();
}
