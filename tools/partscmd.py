"""`caliper parts` -- the shared catalogue: browse it, and search it by fit.

The query that matters is not "show me bearings". It is **what fits the 8 mm
shaft I already have**, which a name search cannot answer and which the
provides/requires vocabulary answers directly:

    caliper parts                     everything, by family
    caliper parts bearing             name or family substring
    caliper parts --fits 8            what offers or needs a Ø8 feature
    caliper parts --guessed           the entries nobody has measured yet
    caliper parts --show bearing/608ZZ   one entry in full

This reads the catalogue only, so it never imports the model and never needs a
workspace -- it answers the same from anywhere.
"""

from __future__ import annotations

import argparse
import sys

import catalog as cat


def one_line(p: cat.Part) -> str:
    prov = {"measured": "measured", "datasheet": "sheet", "guessed": "GUESS"}[p.provenance]
    price = "—" if p.price is None else f"{p.price:.2f}"
    return f"  {p.id:<24} {prov:<9} {price:>7}  {p.note}"


def show(p: cat.Part) -> None:
    print(f"\n{p.id}   {p.family}")
    print(f"  {p.note}" if p.note else "")
    print(f"  spec        " + ", ".join(f"{k}={v}" for k, v in p.spec.items()))
    print(f"  mass        {p.mass * 1000:.1f} g")
    if p.provides:
        print("  provides    " + "\n              ".join(str(i) for i in p.provides))
    if p.requires:
        print("  requires    " + "\n              ".join(str(i) for i in p.requires))
    stamp = p.provenance + (f", {p.verified}" if p.verified else "")
    print(f"  provenance  {stamp}")
    if p.source:
        print("  source      " + ", ".join(f"{k}={v}" for k, v in p.source.items()))
    have = [n for n, v in (("solid", p.solid), ("cutter", p.cutter),
                           ("envelope", p.envelope)) if v]
    print(f"  geometry    {', '.join(have) if have else '— drawn by the design'}")
    print()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="caliper parts",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("query", nargs="?", default="",
                    help="substring of the id or family")
    ap.add_argument("--fits", type=float, metavar="D",
                    help="parts with a Ø D interface, either side")
    ap.add_argument("--guessed", action="store_true",
                    help="only entries whose numbers are a guess")
    ap.add_argument("--show", metavar="ID", help="one entry, in full")
    ap.add_argument("--geometry", action="store_true",
                    help="only entries with reusable shared solids")
    args = ap.parse_args(argv)

    if args.show:
        try:
            show(cat.get(args.show))
        except KeyError as e:
            print(f"caliper parts: {e}", file=sys.stderr)
            return 2
        return 0

    found = cat.all_parts()
    if args.geometry:
        found = [p for p in found if p.solid is not None]
    if args.query:
        q = args.query.lower()
        found = [p for p in found if q in p.id.lower() or q in p.family.lower()]
    if args.fits is not None:
        d = args.fits
        found = [p for p in found
                 if any(abs(i.d - d) < 1e-6 for i in (*p.provides, *p.requires))]
    if args.guessed:
        found = [p for p in found if p.provenance == "guessed"]

    if not found:
        print("  nothing matches. `caliper parts` with no arguments lists everything.")
        return 0

    # group by family, so `transmission` is one heading and not two: the
    # catalogue itself sorts by id, which interleaves families that share a top.
    found.sort(key=lambda p: (p.family, p.id))
    fam = None
    for p in found:
        top = p.family.split("/")[0]
        if top != fam:
            print(f"\n{top}")
            fam = top
        print(one_line(p))

    print(f"\n  {len(found)} of {len(cat.all_parts())} parts", end="")
    if args.fits is not None:
        print(f" · offering or needing Ø{args.fits:g}", end="")
    guesses = [p for p in found if p.provenance == "guessed"]
    print(f" · {len(guesses)} still a guess" if guesses else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
