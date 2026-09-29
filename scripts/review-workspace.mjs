// UI smoke checks against the Docker app, without launching real CLI sessions.
// CALIPER_URL=http://localhost:8017 node scripts/review-ui.mjs
// Optional: PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/path/to/chrome
import assert from "node:assert/strict";
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
const output = process.env.REVIEW_OUTPUT || "/tmp/caliper-ui-review";
mkdirSync(output, { recursive: true });
// Read real CAD and Butai sessions. Intercept writes so existing designs and
// paid agent sessions receive no test edits or prompts.
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [], previewRequests = [];
page.on("pageerror", error => errors.push(error.message));
page.on("request", request => { if (request.url().endsWith("/project-preview")) previewRequests.push(request.postDataJSON()); });
try {
  await page.goto(`${base}/#/`);
  const rows = await page.evaluate(async () => (await (await fetch("/api/workspaces")).json()).workspaces);
  const workspace = rows.find(row => row.exported && row.agents >= 2) || rows.find(row => row.exported && row.id != null);
  assert.ok(workspace, "Needs an exported design");
  await page.goto(`${base}/#/ws/${workspace.slug}`);
  const stage = page.locator('[aria-label="Agent session"]');
  await stage.waitFor();
  await stage.evaluate(element => { element.dataset.identity = "retained"; });
  const canvas = page.locator('[aria-label="Live model viewport"] canvas');
  await canvas.waitFor();
  await canvas.evaluate(element => { element.dataset.identity = "retained"; });
  await page.waitForFunction(() => document.querySelector('[aria-label="Model structure"]')?.textContent.includes("Structure") && document.querySelectorAll('[aria-label="Model structure"] section').length > 0);
  assert.equal(await page.locator('[aria-label="Selection inspector"]').count(), 0);
  const agents = page.getByRole("group", { name: "Project agents" }).locator('button[title^="agent ·"]');
  const detail = await page.evaluate(async id => (await (await fetch(`/butai/api/workspaces/${id}`)).json()), workspace.id);
  if (detail.agents.length >= 2) {
    const inputs=[];
    await page.route("**/butai/api/workspaces/*/panes/*/input",async route=>{
      inputs.push({url:route.request().url(),body:route.request().postDataJSON()});
      await route.fulfill({contentType:"application/json",body:"{}"});
    });
    await agents.nth(1).click();
    await page.getByLabel("Agent terminal").click();await page.keyboard.type("test");await page.keyboard.press("Enter");
    await page.waitForTimeout(500);
    assert.equal(inputs.length,5);
    assert.ok(inputs.every(input=>input.url.includes(`/panes/${detail.agents[1].pane}/input`)));
    assert.equal(await page.getByLabel("Input to selected session").count(),0);
  }
  await page.screenshot({ path: join(output, "implemented-workspace.png") });
  const bounds = await canvas.boundingBox();
  await page.mouse.click(bounds.x + bounds.width * .5, bounds.y + bounds.height * .5);
  await page.getByRole("region", { name: "Selection inspector" }).waitFor().catch(async () => {
    // A section with aria-label is also selectable directly across browsers.
    await page.locator('[aria-label="Selection inspector"]').waitFor();
  });
  await page.getByRole("button", { name: "Close inspector" }).click();
  await page.getByRole("button", { name: "Library", exact: true }).click();
  const original = await page.evaluate(async slug => (await (await fetch(`/api/workspaces/${slug}/project`)).json()), workspace.slug);
  const definition = Object.entries(original.manifest.components).find(([, value]) => typeof value === "object" && value.source && Object.values(value.parameters || {}).some(value => typeof value === "number"));
  assert.ok(definition, "Needs an editable component");
  const [id, component] = definition;
  await page.getByRole("button", { name: component.label || id, exact: true }).last().click();
  assert.equal(await page.getByRole("button", { name: "Expand properties" }).getAttribute("aria-expanded"), "false");
  await page.getByRole("button", { name: "Expand properties" }).click();
  const [parameter, value] = Object.entries(component.parameters).find(([, value]) => typeof value === "number");
  await page.getByLabel(parameter, { exact: true }).fill(String(value + .01));
  assert.equal(await page.getByRole("button", { name: "Rebuild preview", exact: true }).isEnabled().catch(() => page.getByRole("button", { name: "Build preview", exact: true }).isEnabled()), false);
  await page.waitForFunction(() => document.querySelector('[aria-label="Live scene"]')?.disabled);
  assert.equal(await page.getByLabel("Live scene").isEnabled(), false);
  await page.getByRole("button", { name: "Files & Git", exact: true }).click();
  await page.getByRole("button", { name: "Library", exact: true }).click();
  assert.equal(await page.getByLabel(parameter, { exact: true }).inputValue(), String(value + .01));
  let mutation, savedSource;
  let response = structuredClone(original);
  await page.route("**/api/workspaces/*/project", async route => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataJSON();
    if (body.action === "save_definition") { mutation = body; response.manifest.components[body.name] = body.definition; }
    else if (body.action === "save_source") savedSource = body;
    else throw new Error(`Unexpected write: ${body.action}`);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  });
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll("button")].find(button => button.textContent.trim() === "Save changes")?.disabled);
  assert.equal(mutation.name, id); assert.equal(mutation.kind, "component"); assert.equal(mutation.revision, original.revision); assert.equal(mutation.build, false);
  assert.equal(mutation.definition.parameters[parameter], value + .01);
  await page.getByRole("button", { name: "Source", exact: true }).click();
  const source = page.getByLabel("Component source", { exact: true });
  await source.waitFor();
  await page.waitForFunction(() => document.querySelector('[aria-label="Component source"]').value.length > 0);
  const sourceText = await source.inputValue();
  await source.fill(sourceText + "\n# UI browser check\n");
  await page.getByRole("button", { name: "Files & Git", exact: true }).click();
  await page.getByRole("button", { name: "Library", exact: true }).click();
  assert.equal(await source.inputValue(), sourceText + "\n# UI browser check\n");
  await page.getByRole("button", { name: "Save source", exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll("button")].find(button => button.textContent.trim() === "Save source")?.disabled);
  assert.equal(savedSource.path, component.source); assert.equal(savedSource.text, sourceText + "\n# UI browser check\n"); assert.equal(savedSource.build, false);
  await page.getByRole("button", { name: "Back to 3D", exact: true }).click();
  await page.getByRole("button", { name: "Model", exact: true }).click();
  assert.equal(await canvas.getAttribute("data-identity"), "retained");
  assert.equal(await stage.getAttribute("data-identity"), "retained");
  assert.ok(previewRequests.every(request => request.build === false), "Browsing must not queue CAD builds");
  await page.getByRole("button", { name: "Close inspector" }).click();
  await page.setViewportSize({ width: 900, height: 800 });
  await page.screenshot({ path: join(output, "implemented-900.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Toggle project panel" }).click();
  assert.equal(await page.getByRole("navigation", { name: "Project tools" }).isVisible(), true);
  const backdrop = page.getByRole("button", { name: "Close open panel" });
  const backdropBounds = await backdrop.boundingBox();
  await backdrop.click({ position: { x: backdropBounds.width - 5, y: 100 } });
  await page.getByRole("button", { name: "Agents", exact: true }).click();
  assert.equal(await page.getByRole("group", { name: "Project agents" }).isVisible(), true);
  assert.equal(await stage.getAttribute("data-identity"), "retained");
  await page.screenshot({ path: join(output, "implemented-mobile-agents.png") });
  await page.getByRole("button", { name: "Agents", exact: true }).click();
  await page.screenshot({ path: join(output, "implemented-mobile.png") });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  const canvasBounds = await canvas.boundingBox(); assert.ok(canvasBounds.width > 300);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: "passed", workspace: workspace.slug, checks: "actual geometry picking, real agent selection, direct terminal input and pane routing, retained terminal/canvas, library parameter/source edit payloads, cache-only browsing, responsive panels", writes: "intercepted; existing projects and paid sessions untouched", screenshots: output }));
} finally { await browser.close(); }
