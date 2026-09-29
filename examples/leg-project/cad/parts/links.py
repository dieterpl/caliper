"""Reusable subassembly; dimensions arrive from each instance's config."""
from build123d import Cylinder, Pos, Sphere


def links(scene, length, radius):
    if length <= 2 * radius or radius <= 0:
        raise ValueError("length must exceed twice the positive link radius")
    scene.body("mount", Cylinder(radius * 2, 8), mass=0.1,
               color="#64748b", group="mounts")
    scene.body("thigh", Pos(0, 0, -length / 2) * Cylinder(radius, length),
               mass=0.35, color="#94a3b8", group="links")
    shank = Pos(0, 0, -length / 2) * Cylinder(radius * 0.8, length)
    shank += Pos(0, 0, -length) * Sphere(radius * 1.5)
    scene.body("shank", shank, origin=(0, 0, -length), mass=0.25,
               color="#475569", group="links", friction=1.5)
    servo = scene.motor(stiffness=9e4, damping=4.5e3)
    scene.revolute("mount", "thigh", anchor=(0, 0, 0), axis=(0, 1, 0),
                   name="hip", motor=servo, limits=(-0.9, 0.9))
    scene.revolute("thigh", "shank", anchor=(0, 0, -length), axis=(0, 1, 0),
                   name="knee", motor=servo, limits=(-2, 0.05))
