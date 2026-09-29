import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// The tab title with no design open. Keep it in step with <title> in
// index.html, which is what the browser shows before React mounts.
export const HUB_TITLE = "caliper — agentic CAD";
