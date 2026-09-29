"""Build project scenes and isolated subcomponent/assembly previews."""
import argparse
import json
from paths import CAD


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "preview", "discover"))
    parser.add_argument("--kind", choices=("component", "assembly", "scene"), default="scene")
    parser.add_argument("--name")
    parser.add_argument("--out")
    parser.add_argument("--config", default="{}")
    args = parser.parse_args()
    from subcomponents.editor import run
    run(CAD, args.action, kind=args.kind, name=args.name, destination=args.out, configuration=json.loads(args.config))


if __name__ == "__main__":
    main()
