import { existsSync, readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import type { Plugin } from "vite";

// Keep notices and the exact MPL-covered source with the browser distribution.
export function licenseNotices(): Plugin {
  const web = fileURLToPath(new URL(".", import.meta.url));
  const read = (path: string) => readFileSync(resolve(web, path), "utf8");
  return {
    name: "caliper-license-notices",
    apply: "build",
    generateBundle() {
      const emit = (fileName: string, source: string) =>
        this.emitFile({ type: "asset", fileName: `licenses/${fileName}`, source });
      emit("Apache-2.0.txt", read("../LICENSE"));
      emit("MPL-2.0.txt", read("vendor/butai/LICENSE"));
      emit("butai-protocol.js", read("vendor/butai/protocol.js"));
      const notices = [
        "Caliper source: https://github.com/dieterpl/caliper\n",
        read("../NOTICE"),
        "Browser distribution licence files (relative to this document):\n" +
          "Apache-2.0.txt — Caliper and Rapier\n" +
          "MPL-2.0.txt — Butai protocol helpers\n" +
          "butai-protocol.js — exact source of the bundled MPL-covered helpers\n",
        "Installed frontend dependencies (some may be omitted by tree-shaking):\n",
      ];
      const lock = JSON.parse(read("package-lock.json")) as {
        packages: Record<string, { version?: string; license?: string; dev?: boolean; optional?: boolean }>;
      };
      for (const [path, pkg] of Object.entries(lock.packages).sort()) {
        if (!path || pkg.dev) continue;
        const directory = resolve(web, path);
        if (!existsSync(directory) && pkg.optional) continue;
        const files = readdirSync(directory, { withFileTypes: true })
          .filter(entry => entry.isFile() && /^(licen[cs]e|copying|notice)([._-]|$)/i.test(entry.name))
          .map(entry => entry.name).sort();
        notices.push(`\n${path} ${pkg.version} (${pkg.license || "see notice"})\n`);
        if (files.length) {
          for (const file of files) notices.push(read(`${path}/${file}`));
        } else {
          // This npm package omits its upstream LICENSE from the tarball.
          const fallback = `vendor/${path.replace(/^node_modules\//, "")}/LICENSE`;
          if (!existsSync(resolve(web, fallback))) this.error(`Missing licence text for ${path}`);
          notices.push(read(fallback));
        }
      }
      emit("NOTICE.txt", notices.join("\n"));
    },
  };
}
