"""Run with `.venv/bin/python -m unittest discover -s tests`."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "tools"))

import catalog
from subcomponents import along_x, along_y, bldc_motor, get, timing_pulley


def new_scene(name):
    spec = importlib.util.spec_from_file_location(name, APP / "template/cad/scene.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ComponentsTest(unittest.TestCase):
    def setUp(self):
        catalog.reset()

    def test_catalogue_discovery_does_not_load_cad(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys, subcomponents; "
             "subcomponents.get('motor/MN5008'); "
             "assert 'build123d' not in sys.modules; "
             "assert not subcomponents.catalog.USED"],
            env={**os.environ, "PYTHONPATH": str(APP / "tools")},
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mirrored_motors_and_cached_local_geometry(self):
        component = get("motor/MN5008")
        local = component.solid()
        self.assertIs(local, component.solid())
        self.assertIs(component.solid(along_x()), component.solid(along_x()))
        for rotate, axis in ((along_x, "X"), (along_y, "Y")):
            positive = component.solid(rotate(1)).bounding_box()
            negative = component.solid(rotate(-1)).bounding_box()
            self.assertAlmostEqual(getattr(positive.max, axis), 21.5)
            self.assertAlmostEqual(getattr(negative.min, axis), -21.5)
            self.assertAlmostEqual(getattr(positive.min, axis), -13.5)
        self.assertAlmostEqual(local.bounding_box().max.Z, 21.5)
        self.assertFalse(catalog.USED)

    def test_cutter_and_envelope_contain_motor(self):
        component = get("motor/MN5008")
        shape = component.solid()
        self.assertAlmostEqual((shape - component.envelope()).volume, 0)
        for gap in (0, 0.2, 0.6):
            cut = component.cutter({"HARDWARE_CLEARANCE": gap})
            self.assertAlmostEqual(cut.bounding_box().size.X, 55.6 + 2 * gap)
            self.assertAlmostEqual((shape - cut).volume, 0)
        with self.assertRaises(ValueError):
            component.cutter({"HARDWARE_CLEARANCE": -0.1})

    def test_reuse_across_scenes_and_bom_counts(self):
        component = get("motor/MN5008")
        scenes = [new_scene("design_a"), new_scene("design_b")]
        from build123d import Box
        for scene in scenes:
            scene.body("custom_host", Box(10, 10, 10))
            for i in range(3):
                component.attach(scene, f"unit_{i}", "custom_host", origin=(i * 80, 0, 0))
            self.assertEqual(len(scene.SCENE.decor), 3)
            self.assertAlmostEqual(sum(d.mass for d in scene.SCENE.decor), 0.405)
            self.assertIs(scene.SCENE.decor[0].part, component.solid())
        self.assertEqual(catalog.bom()[0].qty, 6)
        self.assertEqual(scenes[0].SCENE.decor[2].origin, (160, 0, 0))
        self.assertEqual(component.solid().bounding_box().center().X, 0)
        catalog.reset()
        self.assertFalse(catalog.bom())

    def test_failed_attachment_does_not_count_hardware(self):
        scene = new_scene("failed_design")
        from build123d import Box
        scene.body("host", Box(10, 10, 10))
        component = get("motor/MN5008")
        for name, parent, kw in (("unit", "missing", {}), ("host", "host", {}),
                                 ("unit", "host", {"origin": (0, 0)}),
                                 ("unit", "host", {"rotation": (0, float('nan'), 0)})):
            with self.assertRaises(ValueError):
                component.attach(scene, name, parent, **kw)
        self.assertFalse(catalog.USED)
        self.assertFalse(scene.SCENE.decor)
        component.attach(scene, "unit", "host")
        with self.assertRaises(ValueError):
            component.attach(scene, "unit", "host")
        self.assertEqual(catalog.bom()[0].qty, 1)

    def test_all_promoted_geometry_is_valid(self):
        for id in ("motor/MN5008", "motor/GB36-1", "board/ODrive-S1",
                   "pulley/GT2-15T-9", "pulley/GT2-16T-9",
                   "pulley/GT2-30T-9", "pulley/GT2-90T-9", "bearing/608ZZ"):
            with self.subTest(id=id):
                component = get(id)
                self.assertTrue(component.solid().is_valid)
                self.assertGreater(component.solid().volume, 0)
                self.assertAlmostEqual((component.solid() - component.envelope()).volume, 0)
        board = get("board/ODrive-S1")
        self.assertAlmostEqual(board.cutter().bounding_box().size.Z, 16.4)
        with self.assertRaisesRegex(ValueError, "no shared cutter"):
            get("pulley/GT2-15T-9").cutter()
        with self.assertRaisesRegex(ValueError, "no shared solid"):
            get("belt/GT2-9").solid()

    def test_parameter_validation(self):
        for args in ((-1, 27, 6, 8), (55, 27, 60, 8), (55, 27, 6, float("inf"))):
            with self.assertRaises(ValueError):
                bldc_motor(*args)
        for args in ((15.5, 9, 8), (15, 9, 100), (15, 9, -1)):
            with self.assertRaises(ValueError):
                timing_pulley(*args)
        with self.assertRaises(ValueError):
            along_y(0)

    def test_example_exports_and_bom_matches_scene_mass(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            shutil.copytree(APP / "template/cad", workspace / "cad")
            shutil.copyfile(APP / "examples/hardware.py", workspace / "cad/model.py")
            env = {**os.environ, "WORKSPACE": folder, "CAD_PYTHON": sys.executable,
                   "APP_DIR": str(APP)}
            for command in (("export",), ("bom", "--json")):
                result = subprocess.run([str(APP / "bin/caliper"), *command],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            scene = json.loads((workspace / "out/scene.json").read_text())
            bom = json.loads((workspace / "out/bom.json").read_text())
            self.assertEqual(len(scene["decor"]), 4)
            self.assertFalse(scene["joints"])
            self.assertEqual(bom["items"], 4)
            self.assertEqual({line["id"]: line["qty"] for line in bom["lines"]},
                             {"motor/MN5008": 2, "board/ODrive-S1": 1, "bearing/608ZZ": 1})
            self.assertAlmostEqual(scene["bodies"][0]["mass"], 0.5 + bom["mass_kg"], places=4)
            for artifact in ("model.glb", "model.step", "collision.json"):
                self.assertGreater((workspace / "out" / artifact).stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
