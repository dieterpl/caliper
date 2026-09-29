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
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [], requests = [], previewBodies = [];
let simulationChecked = false, cadChecked = false;
page.on("pageerror", e => errors.push(e.message));
page.on("request", r => { requests.push(r.url()); if (r.url().endsWith("/project-preview") && r.method() === "POST") previewBodies.push(r.postDataJSON()); });
try {
  await page.goto(`${base}/#/prototype`);
  await page.getByRole("heading", { name: "Live design", exact: true }).waitFor();
  await page.waitForTimeout(700);
  await page.screenshot({ path: join(output, "prototype.png") });
  await page.getByRole("button", { name: /^Components/ }).click();
  await page.getByRole("button", { name: "Hip link", exact: true }).click();
  await page.getByLabel("Length", { exact: true }).fill("135");
  await page.getByRole("button", { name: "Files", exact: true }).click();
  await page.getByRole("button", { name: "kits/leg/motor.py", exact: true }).click();
  await page.getByLabel("Component source draft").waitFor();
  await page.getByRole("button", { name: /^Changes/ }).click();
  await page.getByRole("button", { name: /^Scene presets/ }).click();
  await page.getByRole("button", { name: "Wide stance", exact: true }).click();
  await page.getByRole("button", { name: "Use in workspace", exact: true }).click();
  await page.getByRole("button", { name: "Workbench", exact: true }).click();
  await page.getByRole("heading", { name: "Live design", exact: true }).waitFor();
  await page.getByRole("button", { name: "Add prototype session", exact: true }).click();
  await page.getByLabel("Agent or CLI").selectOption("Codex");
  await page.getByRole("button", { name: "Add demo pane", exact: true }).click();
  await page.getByLabel("Try a request in the prototype").fill("Check motor clearance");
  await page.getByRole("button", { name: "Send demo request", exact: true }).click();
  await page.getByText("Demo: request attached to Live design. No CLI command was executed.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Review notes", exact: true }).click();
  await page.getByLabel("Review feedback").fill("Scene presets are clearer; check inspector width.");
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await page.reload();
  await page.getByRole("heading", { name: "Live design", exact: true }).waitFor();
  assert.equal(await page.getByLabel("Live scene", { exact: true }).inputValue(), "wide");
  await page.setViewportSize({ width: 900, height: 800 });
  await page.screenshot({ path: join(output, "prototype-900.png") });

  // Read the real app without mutating designs or starting agents/processes.
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto(`${base}/#/`);
  await page.getByRole("heading", { name: "Designs", exact: true }).waitFor();
  const rows = await page.evaluate(async () => (await (await fetch("/api/workspaces")).json()).workspaces);
  const design = rows.find(w => w.slug === "odrive-quad") || rows.find(w => w.id != null);
  if (design) {
    await page.goto(`${base}/#/ws/${design.slug}`);
    const stage = page.locator('[aria-label="Agent session"]');
    await stage.waitFor();
    await stage.evaluate(el => { el.dataset.reviewIdentity = "persistent"; });
    await page.getByRole("button", { name: "Library", exact: true }).click();
    await page.getByLabel("Find definition").waitFor();
    await page.getByRole("button", { name: "Agents", exact: true }).waitFor();
    if (process.env.REVIEW_CAD === "1") {
      const definitions = await page.evaluate(async slug => {
        const data = await (await fetch(`/api/workspaces/${slug}/project`)).json();
        return Object.entries(data.manifest.components).slice(-2).map(([id,d]) => ({ id, label: typeof d === "string" ? id : d.label || id }));
      }, design.slug);
      cadChecked = definitions.length > 0;
      for (const definition of definitions) {
        const button = page.getByRole("button", { name: definition.label, exact: true });
        assert.equal(await button.isEnabled(), true, "CAD work must not lock definition navigation");
        await button.click();
        await page.getByRole("heading", { name: definition.label, exact: true }).waitFor();
        await page.getByRole("button", { name: "Expand properties", exact: true }).click();
        await page.getByRole("button", { name: "Save changes", exact: true }).waitFor();
        assert.equal(await page.getByRole("button", { name: "Save changes", exact: true }).isEnabled(), false);
        await page.getByRole("button", { name: /^(Rebuild preview|Build preview)$/ }).waitFor();
      }
      const preset = await page.evaluate(async slug => {
        const data = await (await fetch(`/api/workspaces/${slug}/project`)).json();
        const entry = Object.entries(data.manifest.scenes).find(([id]) => id !== (data.manifest.active_scene || data.manifest.default_scene));
        return entry ? {id: entry[0], label: typeof entry[1] === "string" ? entry[0] : entry[1].label || entry[0]} : null;
      }, design.slug);
      if (preset) {
        await page.getByRole("button", {name: "Scenes", exact: true}).click();
        await page.getByRole("button", {name: preset.label, exact: true}).click();
        await page.getByRole("heading", {name: preset.label, exact: true}).waitFor();
        await page.getByRole("button", {name: "Expand properties", exact: true}).click();
        await page.getByRole("button", {name: /^(Build preview|Rebuild preview)$/}).waitFor();
        assert.equal(await page.getByRole("button", {name: "Use in workspace", exact: true}).isEnabled(), true);
      }
      const rootModels = requests.filter(url => url.includes(`/w/${design.slug}/out/`) && /model\.glb\?v=/.test(url));
      // Main and isolated-part views share a single model download.
      assert.equal(rootModels.length, 1, `Live geometry was downloaded ${rootModels.length} times`);
    }
    assert.equal(previewBodies.every(body => body.build === false), true, "Browsing must only look up cached geometry, never start CAD");
    assert.equal(await stage.getAttribute("data-review-identity"), "persistent", "Library navigation must preserve the live terminal element");
    await page.getByRole("button", { name: "Files & Git", exact: true }).click();
    await page.getByRole("tab", { name: "Files", exact: true }).last().waitFor();
    await page.getByRole("button", { name: "Add", exact: true }).click();
    for (const provider of ["Codex", "Claude", "Gemini"]) await page.getByRole("button", { name: new RegExp(`^${provider}`) }).waitFor();
    await page.screenshot({ path: join(output, "workspace-library.png") });
    let signInCommand;
    await page.route("**/butai/api/workspaces/*/processes", async route => {
      signInCommand = route.request().postDataJSON();
      await route.fulfill({status: 201, contentType: "application/json", body: JSON.stringify({pane: 99999})});
    });
    await page.getByRole("button", {name: /^Sign in to Codex/}).click();
    await page.getByText("Open the link in the terminal and sign in with your ChatGPT account. Then add Codex.", {exact: true}).waitFor();
    assert.deepEqual(signInCommand, {name: "Codex sign-in", command: "codex login --device-auth"}, "Account sign-in must use the Codex CLI without an API key");
    await page.unroute("**/butai/api/workspaces/*/processes");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Model", exact: true }).click();
    assert.equal(await stage.getAttribute("data-review-identity"), "persistent");
    // Panel sizes remain percentages after the resizable-panels API upgrade.
    const projectPanel = page.locator("#project-panel");
    const agentPanel = page.locator("#agent-panel");
    assert.ok((await projectPanel.boundingBox()).width > 200, "Project panel must not shrink to pixel-sized defaults");
    assert.ok((await agentPanel.boundingBox()).width > 300, "Agent panel must keep its desktop width");
    for (const [panel, toggle] of [
      [projectPanel, page.getByTitle("Toggle project panel")],
      [agentPanel, page.getByRole("button", { name: "Agents", exact: true })],
    ]) {
      await toggle.click();
      await page.waitForFunction(id => document.getElementById(id).getBoundingClientRect().width < 2, await panel.getAttribute("id"));
      await page.waitForFunction(button => button.getAttribute("aria-expanded") === "false", await toggle.elementHandle());
      await toggle.click();
      await page.waitForFunction(id => document.getElementById(id).getBoundingClientRect().width > 200, await panel.getAttribute("id"));
      await page.waitForFunction(button => button.getAttribute("aria-expanded") === "true", await toggle.elementHandle());
    }
    const initialWidth = (await projectPanel.boundingBox()).width;
    const handle = await page.locator(".workspace-project-handle").boundingBox();
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
    await page.mouse.down();
    await page.mouse.move(handle.x + 60, handle.y + handle.height / 2, { steps: 8 });
    await page.mouse.up();
    assert.ok((await projectPanel.boundingBox()).width > initialWidth + 30, "Dragging must resize the panel");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator(".compact-project.compact-agents").waitFor();
    await page.getByTitle("Toggle project panel").click();
    assert.equal(await page.getByRole("navigation", { name: "Project tools" }).isVisible(), true);
    await page.getByTitle("Toggle project panel").click();
    await page.getByRole("button", { name: "Agents", exact: true }).click();
    await page.waitForFunction(() => document.getElementById("agent-panel").getBoundingClientRect().width > 300);
    assert.equal(await stage.getAttribute("data-review-identity"), "persistent");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: join(output, "workspace-mobile-agents.png") });
    await page.getByRole("button", { name: "Agents", exact: true }).click();
    await page.setViewportSize({ width: 1600, height: 1000 });
    assert.equal(requests.some(url => /\/physics(?:-[^/]+)?\.js/.test(url)), false, "Browsing must not download the physics engine");
    if (process.env.REVIEW_SIMULATION === "1" && design.joints) await page.getByRole("button", { name: "Simulate", exact: true }).waitFor({ timeout: 30000 });
    if (process.env.REVIEW_SIMULATION === "1" && await page.getByRole("button", { name: "Simulate", exact: true }).count()) {
      simulationChecked = true;
      await page.getByRole("button", { name: "Simulate", exact: true }).click();
      await page.getByRole("button", { name: "Pause", exact: true }).waitFor({ timeout: 30000 });
      await page.waitForTimeout(450);
      await page.getByRole("button", { name: "Pause", exact: true }).click();
      await page.getByRole("button", { name: "Reset", exact: true }).click();
      assert.equal(requests.some(url => /\/physics(?:-[^/]+)?\.js/.test(url)), true);
    }
  }
  const alternate = rows.find(w => w.id != null && w.exported && w.slug !== design?.slug);
  if (alternate && design) {
    await page.evaluate(slug => { location.hash = `/ws/${slug}`; }, alternate.slug);
    await page.waitForFunction(() => {
      const stage = document.querySelector('[aria-label="Agent session"]');
      return stage && stage.dataset.reviewIdentity !== "persistent";
    });
    assert.equal(await page.getByLabel("Project", {exact: true}).inputValue(), alternate.slug);
  }
  if (process.env.REVIEW_SIMULATION !== "1") assert.equal(requests.some(url => /\/physics(?:-[^/]+)?\.js/.test(url)), false, "Browsing must not download the physics engine");
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: "passed", checks: "prototype editing/files/scenes/provider panes/feedback/persistence, live workspace terminal continuity/provider menus, desktop panel sizing/collapse/drag and mobile overlays, cache-only part and scene browsing, one shared live GLB download, deferred physics", screenshots: output, cadChecked, simulationChecked }));
} finally { await browser.close(); }
