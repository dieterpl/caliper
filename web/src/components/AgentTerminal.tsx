import { useEffect, useRef, useState } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { toast } from "sonner";
import { butai } from "@/lib/api";
import { keyMsg, isPassthrough } from "../../vendor/butai/protocol.js";

interface Props {
  wsId: number;
  pane: number | null;
  pasteRequest?: { pane: number; text: string; sequence: number } | null;
}

export default function AgentTerminal({ wsId, pane, pasteRequest }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal>();
  const displayRows = useRef(24);
  const target = useRef({ wsId, pane, generation: 0 });
  const queue = useRef(Promise.resolve());
  const inputVersion = useRef(0);
  const handledPaste = useRef<number>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  function send(input: unknown) {
    const selected = { ...target.current };
    if (selected.pane == null) return;
    // Keep keystrokes and paste in order, and cancel queued input on selection.
    queue.current = queue.current.then(async () => {
      if (target.current.generation !== selected.generation) return;
      try {
        await butai.paneInput(selected.wsId, selected.pane!, input);
        inputVersion.current++;
      } catch (failure) {
        target.current.generation++;
        toast.error("Terminal input failed: " + (failure as Error).message);
      }
    });
  }

  useEffect(() => {
    if (!host.current) return;
    const term = new Terminal({
      fontSize: 13, fontFamily: "ui-monospace, monospace", cursorBlink: true,
      scrollback: 0, theme: { background: "#0e1116", foreground: "#d7dde5" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host.current);
    const measure = () => {
      if (!host.current?.clientHeight || !host.current.clientWidth) return;
      const size = fit.proposeDimensions();
      if (size) displayRows.current = Math.max(6, size.rows - 1);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(host.current);
    measure();
    terminal.current = term;
    term.attachCustomKeyEventHandler(event => {
      if (event.type !== "keydown") return true;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c" && term.hasSelection()) return true;
      if (isPassthrough(event)) return true;
      if (event.isComposing || event.key === "Process") return true;
      const message = keyMsg(event);
      if (message) { event.preventDefault(); send(message.input); return false; }
      return true;
    });
    const data = term.onData(text => {
      // Normal keyboard events are handled above. This receives paste and IME.
      if (text === "\u0003" && term.hasSelection()) return;
      send({ paste: text });
    });
    return () => { observer.disconnect(); target.current.generation++; data.dispose(); term.dispose(); terminal.current = undefined; };
  }, []);

  useEffect(() => {
    const term = terminal.current;
    if (!term) return;
    target.current = { wsId, pane, generation: target.current.generation + 1 };
    term.reset();
    term.options.disableStdin = pane == null;
    setError(""); setLoading(pane != null);
    if (pane == null) { term.write("Select an agent or process to open its terminal."); return; }
    let cancelled = false;
    let timer: number | undefined;
    let controller: AbortController | undefined;
    let previous = "";
    let version = inputVersion.current;
    const read = async () => {
      timer = undefined;
      controller = new AbortController();
      const deadline = window.setTimeout(() => controller?.abort(), 8000);
      try {
        const result = await butai.paneScreen(wsId, pane, controller.signal);
        if (cancelled) return;
        const rows = Math.max(result.rows, displayRows.current);
        const snapshot = JSON.stringify([result.cols, rows, result.lines, result.cursor]);
        if (snapshot !== previous) {
          previous = snapshot;
          let history: string[] = [];
          if (rows > result.rows) {
            // Fill spare vertical space with earlier output when available,
            // keeping the live screen and its cursor at their exact positions.
            try {
              const older = await butai.paneHistory(wsId, pane, rows, controller.signal);
              if (cancelled) return;
              const plain = (line: string) => line.replace(/\x1b\[[0-9;:]*m/g, "").trimEnd();
              let end = result.lines.length;
              while (end && !plain(result.lines[end - 1])) end--;
              const tail = older.lines.slice(-end);
              if (end && tail.length === end && tail.every((line, index) => plain(line) === plain(result.lines[index]))) {
                history = older.lines.slice(0, -end).slice(-(rows - result.rows));
              }
            } catch { /* The live screen still works if history is unavailable. */ }
          }
          if (cancelled) return;
          if (term.cols !== result.cols || term.rows !== rows) term.resize(result.cols, rows);
          // Screen snapshots contain SGR styling; repaint in place without
          // generating local scrollback or resizing the agent's real PTY.
          const position = result.cursor ? `\x1b[${result.cursor[1]+history.length+1};${result.cursor[0]+1}H\x1b[?25h` : "\x1b[?25l";
          term.write("\x1b[?7l\x1b[?25l\x1b[H" + [...history, ...result.lines].map(line => line + "\x1b[0m\x1b[K").join("\r\n") + "\x1b[J" + position);
        }
        setError(""); setLoading(false);
      } catch (failure) {
        if (!cancelled) { setLoading(false); setError((failure as Error).message); }
      } finally { window.clearTimeout(deadline); }
      if (!cancelled) timer = window.setTimeout(read, document.hidden ? 4000 : 350);
    };
    // Refresh promptly after input, without overlapping output requests.
    const feedback = window.setInterval(() => {
      if (version !== inputVersion.current && timer != null) {
        version = inputVersion.current; window.clearTimeout(timer); timer = undefined; void read();
      }
    }, 80);
    const initialRead = async () => { timer = undefined; await read(); };
    void initialRead();
    return () => { cancelled = true; controller?.abort(); window.clearTimeout(timer); window.clearInterval(feedback); };
  }, [wsId, pane]);

  useEffect(() => {
    if (!pasteRequest || pasteRequest.pane !== pane || handledPaste.current === pasteRequest.sequence) return;
    handledPaste.current = pasteRequest.sequence;
    send({ paste: pasteRequest.text });
    terminal.current?.focus();
    toast("Context added to terminal — press Enter to send.");
  }, [pasteRequest, pane]);

  return <div role="region" aria-label="Agent session" className="flex h-full min-h-0 flex-col bg-background">
    {error && <p role="alert" className="flex-none px-3 py-2 text-xs text-destructive">Could not read session: {error}. Retrying…</p>}
    {loading && <p role="status" className="flex-none px-3 py-2 text-xs text-muted-foreground">Loading terminal…</p>}
    <div ref={host} aria-label="Agent terminal" className="min-h-0 flex-1 overflow-auto p-2" onClick={() => terminal.current?.focus()}/>
  </div>;
}
