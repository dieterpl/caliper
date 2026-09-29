"""Four differently configured instances of one Git-pinned leg project."""
from pathlib import Path

from build123d import Box
from subcomponents.project import Project


def build(scene, config):
    length, span = config["length"], config["hip_span"]
    if length <= 30 or span <= 60:
        raise ValueError("length must exceed 30 mm and hip_span must exceed 60 mm")
    height = 2 * length + 15
    scene.body("chassis", Box(220, span, 30), origin=(0, 0, height + 15),
               mass=3, color="#2f4f7f", group="frame")
    leg = Project(Path(__file__).resolve().parents[1] / "kits/leg")
    for name, front, side in (("fl", 1, 1), ("fr", 1, -1),
                              ("bl", -1, 1), ("br", -1, -1)):
        instance = leg.assemble(scene, name,
                                scene="assembled" if config["hardware"] else "links_only",
                                config={"length": length, "side": side},
                                origin=(front * 80, side * span / 2, height))
        scene.fixed("chassis", instance.bodies["mount"],
                    anchor=(front * 80, side * span / 2, height))
