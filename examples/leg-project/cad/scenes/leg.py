"""Two scene variants compose the same link subassembly."""
from ..parts.links import links
from subcomponents import along_y, get


def links_only(scene, config):
    links(scene, config["length"], config["radius"])


def assembled(scene, config):
    if config["side"] not in (-1, 1):
        raise ValueError("side must be -1 or 1")
    links_only(scene, config)
    side = config["side"]
    get("motor/MN5008").attach(scene, "hip_motor", "mount",
                              origin=(0, side * 35, 0), rotation=along_y(-side),
                              color="#334155", group="motors")
    get("motor/MN5008").attach(scene, "knee_motor", "thigh",
                              origin=(0, side * 35, -config["length"]),
                              rotation=along_y(-side), color="#334155", group="motors")
