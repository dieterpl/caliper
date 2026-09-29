"""`caliper scenes` — named scenes and configuration defaults owned by Git."""

import argparse
import json
import sys

from paths import ROOT
from subcomponents.project import Project


def main(argv):
    parser = argparse.ArgumentParser(prog="caliper scenes", description=__doc__)
    parser.add_argument("project", nargs="?", default=str(ROOT),
                        help="project directory; defaults to the current workspace")
    args = parser.parse_args(argv)
    try:
        project = Project(args.project)
    except (ValueError, OSError) as exc:
        print(f"caliper scenes: {exc}", file=sys.stderr)
        return 2
    for name, definition in project.scenes.items():
        if isinstance(definition, str):
            definition = {"builder": definition}
        defaults = {**definition.get("parameters", project.parameters), **definition.get("config", {})}
        marker = " (default)" if name == project.default_scene else ""
        target = definition.get("builder") or ("assembly " + definition["assembly"] if "assembly" in definition else "declarative instances")
        active = " (active)" if name == project.manifest.get("active_scene", project.default_scene) else ""
        print(f"{name}{marker}{active}: {target}")
        print(f"  config: {json.dumps(defaults, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
