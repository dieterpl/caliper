// How the Dock should present a file, by extension. `code` is the default —
// the syntax-highlighted editor; `grid`, `svg` and `image` get their own
// rendered view with the raw source one toggle away (an image has no source
// toggle — its bytes are not text).

export type FileKind = "grid" | "svg" | "image" | "code";

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "avif"]);

export function kindOf(path: string): FileKind {
  const ext = (path.split(".").pop() || "").toLowerCase();
  if (ext === "art") return "grid";
  if (ext === "svg") return "svg";
  if (IMAGE_EXTS.has(ext)) return "image";
  return "code";
}
