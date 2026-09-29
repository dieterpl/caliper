"""Copy to a workspace's cad/model.py; run `caliper export` and `caliper bom`.

Static hardware layout demonstrating shared components, not a working drive.
"""

from build123d import Box

import scene
from subcomponents import get

scene.body("plate", Box(190, 150, 8), type="fixed", origin=(0, 0, 4),
           mass=0.5, color="#64748b")

# Reuse the same component twice; quantities and parent mass follow placement.
motor = get("motor/MN5008")
for side in (-1, 1):
    motor.attach(scene, f"motor_{side}", "plate", origin=(side * 60, -30, 21.5),
                 color="#334155", group="motors")

get("board/ODrive-S1").attach(scene, "controller", "plate", origin=(0, 35, 16),
                             color="#22c55e", group="controllers")
get("bearing/608ZZ").attach(scene, "bearing", "plate", origin=(80, 45, 11.5),
                            color="#cbd5e1", group="bearings")
