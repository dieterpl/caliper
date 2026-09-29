// SPDX-License-Identifier: MPL-2.0
// Vendored from https://github.com/dieterpl/butai — see NOTICE.
// butai client protocol — pure message builders + keyboard mapping.
//
// The daemon's framed protocol is externally-tagged, snake_case JSON (see
// crates/butai-protocol/src/lib.rs). These helpers produce exactly those shapes;
// nothing here touches the DOM or the socket.

export const PROTO_VERSION = 1;

// A `hello` message. `target: "default"` attaches to the most recent session,
// creating one if none exist — the whole workbench renders into our viewport.
export function helloMsg(cols, rows, cwd = "/") {
  return {
    hello: {
      proto_version: PROTO_VERSION,
      encoding: "json",
      cols,
      rows,
      target: "default",
      cwd,
    },
  };
}

export function resizeMsg(cols, rows) {
  return { resize: { cols, rows } };
}

export function pasteMsg(text) {
  return { input: { paste: text } };
}

export function mouseMsg(kind, x, y, alt = false) {
  // kind: "mouse_down" | "mouse_drag" | "mouse_up". `alt` forces a butai text
  // selection even over an app that grabbed the mouse (mouse_up carries no alt).
  const payload = kind === "mouse_up" ? { x, y } : { x, y, alt };
  return { input: { [kind]: payload } };
}

export function scrollMsg(up, x, y) {
  return { input: { [up ? "scroll_up" : "scroll_down"]: { x, y } } };
}

export function detachMsg() {
  return "detach";
}

// Named (non-character) keys → the protocol's KeyCode string variants.
const NAMED = {
  Enter: "enter",
  Escape: "esc",
  Backspace: "backspace",
  Tab: "tab",
  ArrowLeft: "left",
  ArrowRight: "right",
  ArrowUp: "up",
  ArrowDown: "down",
  Home: "home",
  End: "end",
  PageUp: "page_up",
  PageDown: "page_down",
  Delete: "delete",
  Insert: "insert",
};

// Map a browser KeyboardEvent to an `{input:{key:{code,mods}}}` message, or
// null for keys the protocol does not carry (bare modifiers, dead keys, etc.).
export function keyMsg(e) {
  const mods = {};
  if (e.ctrlKey) mods.ctrl = true;
  if (e.altKey) mods.alt = true;
  if (e.shiftKey) mods.shift = true;

  let code = null;
  const k = e.key;

  if (k === "Tab" && e.shiftKey) {
    code = "back_tab";
    delete mods.shift; // back_tab already encodes the shift
  } else if (NAMED[k]) {
    code = NAMED[k];
  } else if (/^F\d{1,2}$/.test(k)) {
    code = { f: parseInt(k.slice(1), 10) };
  } else if (k.length === 1) {
    // A single printable character (grapheme). Shift is already reflected in
    // the character itself, so don't also send the shift modifier.
    code = { char: k };
    delete mods.shift;
  } else {
    return null; // "Shift", "Control", "Meta", "Dead", ...
  }

  const key = { code };
  if (Object.keys(mods).length) key.mods = mods;
  return { input: { key } };
}

// True when we should let the browser handle the event natively (never send it).
// Deliberately narrow: Ctrl-C / Ctrl-D etc. MUST reach the pane (terminal
// interrupt/EOF). The daemon does its own copy from server-side selection and
// pushes it via `set_clipboard`, so we don't hijack Ctrl-C for copy. We only
// let through paste (so the `paste` event delivers the text), page reload, and
// the devtools keys.
export function isPassthrough(e) {
  const k = (e.key || "").toLowerCase();
  if ((e.ctrlKey || e.metaKey) && k === "v") return true; // native paste event
  if (e.key === "F5" || ((e.ctrlKey || e.metaKey) && k === "r")) return true;
  if (e.key === "F12") return true;
  if (e.ctrlKey && e.shiftKey && (k === "i" || k === "j" || k === "c")) return true;
  return false;
}
