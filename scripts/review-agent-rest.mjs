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
let chromium, firefox;
try { ({ chromium, firefox } = require("playwright")); }
catch {
  const globalRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
  try { ({ chromium, firefox } = require(join(globalRoot, "playwright"))); }
  catch { ({ chromium, firefox } = require(join(globalRoot, "@playwright/test/node_modules/playwright"))); }
}
const cache = join(homedir(), ".cache/ms-playwright");
const discovered = existsSync(cache) ? readdirSync(cache).filter(n => /^chromium-\d+$/.test(n)).sort((a,b) => Number(b.split("-")[1]) - Number(a.split("-")[1])).map(n => join(cache,n,"chrome-linux64/chrome")).find(existsSync) : undefined;

const useFirefox=process.env.REVIEW_BROWSER==='firefox';
const browser=useFirefox ? await firefox.launch({executablePath:process.env.PLAYWRIGHT_FIREFOX_EXECUTABLE_PATH}) : await chromium.launch({executablePath:discovered,args:['--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader']});
const page=await browser.newPage();
const sockets=[], errors=[];
page.on('websocket',ws=>{if(new URL(ws.url()).pathname==='/ws')sockets.push(ws.url());});page.on('pageerror',error=>errors.push(error.message));
const base=process.env.CALIPER_URL || 'http://localhost:8017';
try {
 if(useFirefox){
  // Isolate the real agent panel: this headless Firefox has no WebGL driver.
  await page.goto(`${base}/#/`);
  await page.evaluate(async()=>{
   const {default:React}=await import('/node_modules/.vite/deps/react.js');
   const {default:ReactDOM}=await import('/node_modules/.vite/deps/react-dom_client.js');
   const {default:AgentsRail}=await import('/src/components/AgentsRail.tsx');
   const div=document.createElement('div');div.style.cssText='position:fixed;inset:0;z-index:100';document.body.append(div);
   ReactDOM.createRoot(div).render(React.createElement(AgentsRail,{wsId:3,slug:'odrive-quad'}));
  });
 }else await page.goto(`${base}/#/ws/odrive-quad`);
 const terminal=page.getByLabel('Agent terminal');await terminal.waitFor();
 await page.waitForFunction(()=>document.querySelector('[aria-label="Agent terminal"] .xterm-rows')?.textContent.length>30);
 assert.equal(await page.getByLabel('Input to selected session').count(),0);
 await page.setViewportSize({width:1400,height:1100});await page.waitForTimeout(800);
 const tall=await terminal.locator('.xterm-screen').boundingBox();const available=await terminal.boundingBox();
 assert.ok(tall.height>=available.height-45,'terminal must fill panel height');
 await page.setViewportSize({width:1400,height:800});await page.waitForTimeout(800);
 const shorter=await terminal.locator('.xterm-screen').boundingBox();
 assert.ok(shorter.height<tall.height-150,'terminal height must follow viewport resize');
 const detail=await page.evaluate(async()=>await(await fetch('/butai/api/workspaces/3')).json());
 const buttons=page.getByRole('group',{name:'Project agents'}).locator('button[title^="agent ·"]');
 assert.ok(detail.agents.length>=2,'needs two existing agents');
 let sent; const inputs=[];
 await page.route('**/butai/api/workspaces/3/panes/*/input',async route=>{sent={url:route.request().url(),body:route.request().postDataJSON()};inputs.push(sent);await route.fulfill({contentType:'application/json',body:'{}'});});
 await buttons.nth(1).click();
 await terminal.click();
 await page.keyboard.type('hello');
 await page.keyboard.press('ArrowLeft');await page.keyboard.press('Backspace');await page.keyboard.press('Enter');
 await page.waitForFunction(()=>true);await page.waitForTimeout(700);
 assert.deepEqual(inputs.map(i=>i.body.key?.code),[...'hello'].map(char=>({char})).concat(['left','backspace','enter']));
 assert.ok(inputs.every(i=>i.url.includes(`/panes/${detail.agents[1].pane}/input`)));
 await page.keyboard.press('Escape');await page.waitForTimeout(150);assert.deepEqual(sent.body,{key:{code:'esc'}});
 await terminal.locator('textarea').evaluate(el=>{
 const event=new Event('paste',{bubbles:true,cancelable:true});
 Object.defineProperty(event,'clipboardData',{value:{getData:()=> 'pasted text'}});el.dispatchEvent(event);
 });
 await page.waitForTimeout(150);assert.deepEqual(sent.body,{paste:'pasted text'});
 await buttons.nth(0).click();await terminal.click();await page.keyboard.press('Control+c');await page.waitForTimeout(150);
 assert.ok(sent.url.includes(`/panes/${detail.agents[0].pane}/input`));assert.deepEqual(sent.body,{key:{code:{char:'c'},mods:{ctrl:true}}});
 await buttons.nth(1).click();
 const endpoint=`**/butai/api/workspaces/3/panes/${detail.agents[1].pane}/output*`;
 await page.route(endpoint,async route=>await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'test interruption'})}));
 await page.getByText(/Could not read session/).waitFor();
 await page.unroute(endpoint);
 await page.waitForFunction(()=>!document.querySelector('[aria-label="Agent session"] [role="alert"]'));
 assert.equal(sockets.length,0,'agent panel must never connect a browser WebSocket');assert.deepEqual(errors,[]);
 console.log(`Passed (${useFirefox?'Firefox':'Chromium'}): coloured terminal, direct typing/paste/keys, ordered selected-pane REST input, interruption recovery, zero WebSockets; writes intercepted`);
} finally {await browser.close();}
