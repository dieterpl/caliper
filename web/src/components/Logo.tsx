import { cn } from "@/lib/utils";

// The caliper mark: a geometric C drawn as a caliper's beam and jaws — the
// spine is the beam, the two horizontals are the jaws, and the blue extension
// on the top jaw is the reach being measured. It is drawn on lucide's grid
// (24x24, stroke 2, round caps) because it sits beside lucide icons in every
// header; a different stroke weight would read as a second icon set.
//
// `mono` drops the accent to currentColor, for the favicon and anywhere the
// mark has to survive in one colour. See docs/DESIGN.md for the usage rules.
export function Logo({
  size = 20,
  mono = false,
  className,
}: {
  size?: number;
  mono?: boolean;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("shrink-0", className)}
      aria-hidden="true"
      focusable="false"
    >
      <path d="M14 4H8a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h6" />
      <path d="M14 4h5" stroke={mono ? undefined : "hsl(var(--primary))"} />
    </svg>
  );
}

// Mark plus name. The tagline is optional so the workspace header can carry the
// lockup without repeating what the Hub already said.
export function Wordmark({
  tagline = false,
  size = 20,
  className,
}: {
  tagline?: boolean;
  size?: number;
  className?: string;
}) {
  return (
    <span className={cn("flex items-center gap-2", className)}>
      <Logo size={size} />
      <span className="font-semibold tracking-tight">caliper</span>
      {tagline && (
        <span className="font-normal text-muted-foreground">· agentic CAD</span>
      )}
    </span>
  );
}
