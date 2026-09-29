// A deliberately small regex tokenizer for the dock editor — comments, strings,
// numbers, keywords and call names. Good enough to read code by; not a parser.
// Ported verbatim from the old dock.js.

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const KEYWORDS = new Set(
  (
    "async await break case catch class const continue def del elif else export " +
    "extends false finally fn for from function if import impl in is let loop match " +
    "mut new None not or pub return self static struct super switch this throw trait " +
    "true try type typeof use var void while with yield and as enum interface public " +
    "private protected package where move ref unsafe crate dyn Box Vec Option Result"
  ).split(" "),
);

export function langOf(path: string): string {
  const ext = (path.split(".").pop() || "").toLowerCase();
  if (["md", "markdown", "txt", "log"].includes(ext)) return "text";
  return ext;
}

export function highlight(code: string, lang: string): string {
  if (lang === "text") return esc(code);
  const lineCmt = ["py", "sh", "toml", "yaml", "yml"].includes(lang) ? "#" : "//";
  let out = "";
  let i = 0;
  const n = code.length;
  const isWord = (c: string) => /[A-Za-z0-9_$]/.test(c);
  while (i < n) {
    const c = code[i];
    const two = code.slice(i, i + 2);
    if (two === lineCmt || (lineCmt === "#" && c === "#")) {
      let j = code.indexOf("\n", i);
      if (j < 0) j = n;
      out += `<span class="c-comment">${esc(code.slice(i, j))}</span>`;
      i = j;
      continue;
    }
    if (two === "/*") {
      let j = code.indexOf("*/", i);
      j = j < 0 ? n : j + 2;
      out += `<span class="c-comment">${esc(code.slice(i, j))}</span>`;
      i = j;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      let j = i + 1;
      while (j < n && code[j] !== c) {
        if (code[j] === "\\") j++;
        j++;
      }
      j = Math.min(j + 1, n);
      out += `<span class="c-string">${esc(code.slice(i, j))}</span>`;
      i = j;
      continue;
    }
    if (/[0-9]/.test(c) && !isWord(code[i - 1] || "")) {
      let j = i;
      while (j < n && /[0-9a-fA-FxX._]/.test(code[j])) j++;
      out += `<span class="c-num">${esc(code.slice(i, j))}</span>`;
      i = j;
      continue;
    }
    if (isWord(c)) {
      let j = i;
      while (j < n && isWord(code[j])) j++;
      const word = code.slice(i, j);
      if (KEYWORDS.has(word)) out += `<span class="c-key">${esc(word)}</span>`;
      else if (code[j] === "(") out += `<span class="c-fn">${esc(word)}</span>`;
      else out += esc(word);
      i = j;
      continue;
    }
    out += esc(c);
    i++;
  }
  return out;
}

export function renderPatch(patch: string): string {
  return patch
    .split("\n")
    .map((line) => {
      let cls = "";
      if (line.startsWith("+")) cls = "add";
      else if (line.startsWith("-")) cls = "del";
      else if (line.startsWith("@@")) cls = "hunk";
      else if (/^(diff |index |--- |\+\+\+ )/.test(line)) cls = "meta";
      return `<span class="${cls}">${esc(line)}</span>`;
    })
    .join("\n");
}
