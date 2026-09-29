"""`caliper bom` -- what to buy, counted from the model rather than remembered.

Importing the model runs every `use()` the design declares, so the quantity of
each part is however many times that line actually executed. Place a fifth leg
and the bearing count goes up here in the same second it goes up in the render;
delete a leg and it goes down. That is the whole argument for the tier: the
hand-multiplied number in a BOM comment is the one thing in a design that has no
way of being wrong out loud.

    caliper bom                 the table, the totals and the checks
    caliper bom --check         only the problems; exits non-zero if any fail
    caliper bom --geometry      which entries the design still draws itself
    caliper bom --json          write out/bom.json as well

`cad/printing.py` is imported too when it exists: fasteners and inserts are
declared where their bosses are cut, which is there rather than in the model.
"""

from __future__ import annotations

import argparse
import json
import sys

from paths import CAD, OUT, ROOT, require_cad

import catalog as cat


def _load_model() -> tuple[bool, bool]:
    """Import the workspace's model (and printing, if present). -> (ok, printed)."""
    require_cad()
    if str(CAD) not in sys.path:
        sys.path.insert(0, str(CAD))
    cat.reset()

    import model  # noqa: F401  -- populates SCENE and cat.USED as a side effect

    printed = False
    try:
        import printing  # noqa: F401
        printed = True
    except ImportError:
        pass                      # a design with nothing printed is a design
    except Exception as exc:      # noqa: BLE001 - a broken printing.py must not
        print(f"bom: cad/printing.py did not import ({exc.__class__.__name__}: "
              f"{exc}); fasteners declared there are not counted.\n", file=sys.stderr)
    return True, printed


def spec_line(p: cat.Part) -> str:
    s = p.spec
    fam = p.family.split("/")[0]
    if fam == "bearing":
        return f"Ø{s['od']:g}×{s['width']:g} ⌀{s['bore']:g} {s['shield']}"
    if p.family.endswith("pulley"):
        return f"{s['teeth']}T {s['width']:g} mm, ⌀{s['bore']:g}"
    if p.family.endswith("belt"):
        return f"{s['width']:g} mm {s['profile']}"
    if fam == "actuator":
        return f"Ø{s['d']:g}×{s['length']:g}, {s['kv']} kv"
    if fam == "electronics":
        return f"{s['w']:g}×{s['h']:g}×{s['t']:g}"
    if p.family.endswith("screw"):
        return f"M{s['size']}×{s['length']}"
    if p.family.endswith("insert"):
        return f"M{s['size']}, Ø{s['bore']:g} bore"
    return ", ".join(f"{k} {v}" for k, v in list(s.items())[:2])


def print_bom(rows: list[cat.Row]) -> None:
    if not rows:
        print("nothing declared. A design says what hardware it uses with\n"
              "  from catalog import use\n"
              "  use(\"bearing/608ZZ\", 2, where=\"hip fork plates\")")
        return

    w_id = max(len(r.part.id) for r in rows)
    w_sp = max(len(spec_line(r.part)) for r in rows)
    bar = "─" * (w_id + w_sp + 34)

    print(f"  {'part':<{w_id}}  {'spec':<{w_sp}}  {'qty':>4} {'each':>8} {'total':>9}   where")
    print("  " + bar)

    fam = None
    total = 0.0
    unknown = False
    for r in rows:
        top = r.part.family.split("/")[0]
        if fam is not None and top != fam:
            print()
        fam = top
        each = "—" if r.part.price is None else f"{r.part.price:8.2f}"
        if r.cost is None:
            cost, unknown = "—", True
        else:
            cost, total = f"{r.cost:9.2f}", total + r.cost
        where = ", ".join(r.where) if r.where else ""
        if len(where) > 42:
            where = where[:41] + "…"
        mark = " " if r.part.provenance != "guessed" else "?"
        print(f"{mark} {r.part.id:<{w_id}}  {spec_line(r.part):<{w_sp}}  "
              f"{r.qty:>4} {each:>8} {cost:>9}   {where}")

    print("  " + bar)
    items = sum(r.qty for r in rows)
    suppliers = len({r.part.source.get("supplier", r.part.family.split("/")[0]) for r in rows})
    print(f"  {len(rows)} lines · {items} items · {cat.total_mass():.3f} kg of hardware"
          f" · {suppliers} families")
    print(f"  est. {total:.2f}" + (" (+ items with no price)" if unknown else ""))


def print_checks(problems: list[cat.Problem]) -> int:
    if not problems:
        print("\n  checks: nothing to report — every used part is measured or "
              "from a sheet, and every declared mate fits.")
        return 0
    print()
    fails = [p for p in problems if p.level == "fail"]
    for p in problems:
        tag = "FAIL" if p.level == "fail" else "warn"
        print(f"  {tag}  {p.what}\n        {p.detail}")
    print(f"\n  {len(fails)} fail, {len(problems) - len(fails)} warn")
    return 1 if fails else 0


def print_geometry(rows: list[cat.Row]) -> None:
    """Which entries carry shared geometry and which the design still draws.

    A part with no `solid` is not broken -- the design draws it, exactly as it
    did before there was a catalogue. It is just not shared yet, and this is the
    list of what is left.
    """
    print(f"  {'part':<24} solid  cutter  envelope   provenance")
    print("  " + "─" * 62)
    for r in rows:
        p = r.part
        m = lambda x: "  ✓   " if x else "  —   "   # noqa: E731
        stamp = p.provenance + (f" {p.verified}" if p.verified else "")
        print(f"  {p.id:<24}{m(p.solid)} {m(p.cutter)} {m(p.envelope)}    {stamp}")
    drawn = [r.part.id for r in rows if r.part.solid is None]
    if drawn:
        print(f"\n  {len(drawn)} of {len(rows)} still drawn by the design: "
              f"{', '.join(drawn[:4])}{'…' if len(drawn) > 4 else ''}")


def write_json(rows: list[cat.Row], problems: list[cat.Problem]) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "bom.json").write_text(json.dumps({
        "design": ROOT.name,
        "lines": [{
            "id": r.part.id, "mpn": r.part.mpn, "family": r.part.family,
            "qty": r.qty, "spec": r.part.spec,
            "unit_price": r.part.price, "total_price": r.cost,
            "mass_kg": round(r.mass, 4),
            "provenance": r.part.provenance, "verified": r.part.verified,
            "where": r.where,
        } for r in rows],
        "items": sum(r.qty for r in rows),
        "mass_kg": round(cat.total_mass(), 4),
        "problems": [{"level": p.level, "what": p.what, "detail": p.detail}
                     for p in problems],
    }, indent=2))
    print(f"\n  wrote {OUT / 'bom.json'}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="caliper bom", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="only the problems")
    ap.add_argument("--geometry", action="store_true",
                    help="which entries the design still draws itself")
    ap.add_argument("--json", action="store_true", help="also write out/bom.json")
    args = ap.parse_args(argv)

    _load_model()
    rows = cat.bom()
    problems = cat.check()

    if args.geometry:
        print_geometry(rows)
        return 0
    if not args.check:
        print(f"\n{ROOT.name} — bought hardware, counted from the model\n")
        print_bom(rows)
    rc = print_checks(problems)
    if args.json:
        write_json(rows, problems)
    return rc if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
