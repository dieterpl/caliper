# caliper — design guideline

What the app should look like and why, so a change made in one component does
not invent a second look. The tokens live in `web/src/index.css` and
`web/tailwind.config.ts`; this document says what they are *for*.

If you are adding UI, read §2 (colour), §3 (type) and §6 (patterns). Everything
else is reference.

---

## 1. Principles

**The model is the subject. Chrome recedes.** The viewport is the only place
with saturated colour, because the only saturated thing in it is the design. The
surround is near-black, the rails are one step lighter, and text that is not the
answer to a question is `muted-foreground`. If a control competes with the
render for attention, the control is wrong.

**One dark theme, on purpose.** There is no light mode, no `prefers-color-scheme`
branch and no toggle. `index.html` hardcodes `class="dark"`, `App.tsx` hardcodes
`<Toaster theme="dark">`, and every token sits on `:root` with no `.dark {}`
override. A 3D viewport wants a dark surround; committing to it means one
palette to keep honest instead of two. Do not add a light theme without changing
this document first.

**The UI is conditional on capability, never on a name.** `tools/` is shared by
every workspace and may not know one model's vocabulary — the same rule binds
the app. The Play button, the clock and the step counter appear when
`scene.json` has joints and stay away when it does not. A design with two parts
and no motors must not show a paused simulator. When you add a control, ask what
it does on that design.

**One project panel, one model, one agent session.** Model, Library and Files & Git
share the same left panel. The center holds the live viewport, an isolated
preview, or the open source/diff. Part properties appear only on selection as a
dismissible overlay; they never form a permanent extra sidebar. The right panel
keeps a compact agent status list above the live Butai output. Agent output and input use HTTP REST,
which the backend relays over Butai’s Unix socket. On small screens,
panels open over the viewport and keep their children mounted.

**Density over comfort.** `html { font-size: 14px }` shrinks the whole rem-based
scale to roughly 88%. This is a workbench that shows a file tree, a render, an
editor and a live terminal at once; fitting them beats generous padding.

---

## 2. Colour

Every colour is an HSL triple on `:root` in `web/src/index.css`, mapped to a
Tailwind name in `tailwind.config.ts`. Use the Tailwind name (`bg-card`,
`text-muted-foreground`), never the raw value.

| Token | Value | What it is for |
| --- | --- | --- |
| `background` | `222 41% 6%` | The page, and the viewport surround. The darkest surface. |
| `foreground` | `213 40% 93%` | Body text and the answer to whatever the row is asking. |
| `card` | `218 33% 11%` | Every rail, header, footer and card — one step up from the page. This is what separates chrome from content. |
| `popover` | `218 33% 12%` | Dialogs, menus, anything floating above a rail. |
| `primary` | `217 91% 60%` | **The brand colour.** Selection, focus, the active thing, the one accent in the logo. Also the primary button. |
| `secondary` | `218 30% 16%` | A pressed or active toggle (`Files`/`Agents` in the workspace header). |
| `muted` | `218 30% 15%` | Inert chips and count bubbles. |
| `muted-foreground` | `215 22% 62%` | Labels, units, paths, timestamps — everything that is context rather than content. |
| `accent` | `218 32% 18%` | Hover on a ghost control. Nothing else. |
| `border` / `input` | `218 36% 21%` | Every hairline. `*` gets `border-border` globally, so a bare `border` class is already correct. |
| `ring` | `217 91% 60%` | Focus ring — same blue as `primary`, deliberately. |
| `destructive` | `3 92% 63%` | Removal, failure, a red diff line. |
| `good` | `142 71% 45%` | Running, healthy, an added diff line. |
| `warn` | `41 74% 49%` | Waiting on a human. |

`good` and `warn` are caliper's additions to the shadcn set; they exist because
this app reports state (daemon up, agent working, sim running) constantly.

**Never hardcode a hex in a component.** Two places are exempt, and only two:

- `index.css` `.c-*` and `.code-layer` rules — those are a *syntax theme*, not
  UI chrome, and they are tuned against each other rather than against the
  tokens.
- `LOGIN_HTML` in `web/server.py` — it is served before any CSS pipeline exists.
  It mirrors the palette by hand and says so in a comment. If you change a token
  above, change that string too.

For a tint of a token, use Tailwind's slash syntax (`bg-primary/15`,
`hover:border-primary/60`) rather than a new variable.

---

## 3. Type

The root is 14px, so Tailwind's rem-based scale computes smaller than its docs
suggest. The real sizes:

| Class | rem | actual |
| --- | --- | --- |
| `text-[10px]` | — | 10px — count bubbles only |
| `text-xs` | 0.75 | **10.5px** — labels, units, stats strips, footers |
| `text-sm` | 0.875 | **12.25px** — the body default, and `size="sm"` buttons |
| `text-base` | 1 | 14px |
| `text-lg` | 1.125 | **15.75px** — the one page heading (`Designs`) |

Weights: `font-medium` for a name you can act on (a design, a file, a rail
title), `font-semibold` for the wordmark and page headings, normal for
everything else. `tracking-tight` only on the wordmark.

**Mono is for things people compare column-wise** — file paths, counts, sizes,
the Hub's vitals strip, code. The stack is in `tailwind.config.ts` under
`fontFamily.mono`. Prose in mono is a mistake; a number in prose is fine in the
body font if it is not being compared to another number.

Sentence case everywhere. No ALL-CAPS labels, no title case on buttons.

---

## 4. Space and density

- **Radius** comes from `--radius: 0.5rem`. `rounded-md` is the default for
  controls, `rounded-lg` for cards and dialogs, `rounded` for a chip.
- **Header / toolbar**: `flex flex-none items-center gap-2 border-b px-3 py-2`.
  The Hub's page header uses `px-4 py-2.5 gap-3` because it is the outermost
  frame; every rail toolbar uses the tighter one.
- **Rail shell**: `flex h-full flex-col bg-card`, its own `border-b` toolbar on
  top, the scrollable body below. `FilesRail`, `AgentsRail` and `Dock` are all
  built this way — copy one rather than inventing a fourth.
- **Panels** are `react-resizable-panels`; collapsible ones need `collapsedSize={0}`
  and a `min-w-0` class while collapsed, or the content fights the handle.
- **Spacer** between a left group and a right group is `<span className="flex-1" />`,
  not `justify-between` — the toolbars have three groups more often than two.
- Body padding is `p-5` for a page, `p-2`/`p-3` inside a rail.

---

## 5. Icons

`lucide-react` only. Buttons size them automatically — `button.tsx` carries
`[&_svg]:size-4` — so pass the icon bare: `<Button size="sm"><RefreshCw /> Reload</Button>`.

An icon in a header is paired with its label. Icon-only is allowed where space is
genuinely tight (the viewport overlay, a row action) and then `title` is
required. Stroke width is lucide's default 2 everywhere, which is also what the
logo uses — that is the whole reason the mark sits beside them cleanly.

---

## 6. Component patterns

**Status is a badge with a dot.** `<Badge variant="muted" className="gap-1.5">`
with a 2×2 `rounded-full` span coloured by `good` / `warn` /
`muted-foreground` / `destructive`, then a word. The Hub's daemon health, the
workspace branch, the sim state in the stats strip all use it. Colour alone
never carries the meaning — the word is always there too.

**Counts are chips, not badges.** `rounded bg-muted px-1.5 text-xs
text-muted-foreground` next to a rail title; `bg-primary/20 text-primary` when
the count is something changed and unsaved.

**A stats strip** (`Viewport.tsx`, the Hub footer) is
`border-t bg-card px-3 py-1.5 text-xs text-muted-foreground` with `gap-x-4`, each
item `label <b className="text-foreground">value</b>`. Em dash for a value that
is not known yet, never `0` and never blank.

**Cards** are `Card` from `ui/card` — `rounded-lg border bg-card shadow-sm`. A
clickable card gets `hover:border-primary/60 transition-colors`, not a
background change.

**Toasts** are sonner, dark, bottom-centre, configured once in `App.tsx`. Use one
when something happened *elsewhere* than where the user clicked — a save that
triggers a re-export, a checkout waiting on a rebuild. Do not toast a result the
user is already looking at.

**Empty and pending states** carry the mark at `opacity-20` with `mono`, above
one sentence saying what would fill the space and how. Never a bare spinner and
never a blank panel.

---

## 7. The mark

`web/src/components/Logo.tsx` exports `Logo` (mark) and `Wordmark` (lockup).

A geometric **C** derived from a caliper: the spine is the beam, the two
horizontals are the jaws, and the blue extension on the top jaw is the reach
being measured. It is drawn on lucide's grid — 24×24 viewBox, `fill="none"`,
`stroke-width="2"`, round caps and joins — so it shares a skeleton with every
other icon in the app.

```
M14 4H8a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h6     the beam and jaws, currentColor
M14 4h5                                       the reach, hsl(var(--primary))
```

- **Two-tone by default.** The C takes `currentColor` and inherits from its
  container; only the reach is blue.
- **`mono`** drops the reach to `currentColor`. Use it for the favicon, for
  watermarks, and anywhere the mark must survive in one colour.
- **Sizes**: 20 in a header, 28 in a rail placeholder, 40–56 as an empty-state
  watermark, 16 minimum. Below 16 the corner radii disappear.
- **Clear space**: half the mark's height on every side.
- **Lockup**: mark + `caliper` in `font-semibold tracking-tight`, `gap-2`. The
  `· agentic CAD` tagline appears on the Hub and the login screen — the two
  places someone arrives — and nowhere else.

Copies of the path data live in `web/index.html` (favicon) and `LOGIN_HTML` in
`web/server.py`. There are exactly three; if the mark changes, change all three.

Don't: recolour the C, fill it, add a shadow or a gradient, put it in a circle,
stretch it non-uniformly, or set it in a different weight from the icons beside
it.

---

## 8. Do / don't

| Do | Don't |
| --- | --- |
| `bg-card` for chrome, `bg-background` for the render | Invent a third surface level |
| `text-muted-foreground` for labels and units | Grey out something the user needs to read |
| Show a control when the capability exists | Show a disabled control for a capability this design lacks |
| Say the state in a word beside the dot | Rely on dot colour alone |
| Reuse a rail's shell and toolbar classes | Hand-roll a fourth panel layout |
| Em dash for an unknown value | `0`, `null`, or an empty cell |
| Sentence case | Title Case Buttons, or ALL CAPS LABELS |
| Mono for paths, counts and code | Mono for prose |
| Toast what happened out of view | Toast what is already on screen |
| Keep the three copies of the mark in step | Add a fourth |
