import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import os
import sys
import importlib.util
from types import SimpleNamespace

from test_subcomponents import APP, new_scene
import catalog
from subcomponents.project import Project


class ProjectsTest(unittest.TestCase):
    def setUp(self):
        catalog.reset()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.leg = self.seed("leg", "leg-project")
        self.quad = self.seed("quad", "quad-project")

    def seed(self, name, example):
        workspace = self.folder / name
        shutil.copytree(APP / "template/cad", workspace / "cad")
        shutil.copytree(APP / "examples" / example / "cad", workspace / "cad", dirs_exist_ok=True)
        (workspace / ".gitignore").write_text("out/\n__pycache__/\n*.pyc\n")
        return workspace

    def git(self, workspace, *args):
        result = subprocess.run(["git", "-C", str(workspace),
                                 "-c", "user.name=Caliper test", "-c", "user.email=test@example.invalid",
                                 *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def cli(self, workspace, *args, success=True):
        result = subprocess.run([str(APP / "bin/caliper"), *args],
                                env={**os.environ, "WORKSPACE": str(workspace),
                                     "CAD_PYTHON": sys.executable, "APP_DIR": str(APP)},
                                capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def include_leg(self):
        shutil.copytree(self.leg, self.quad / "cad/kits/leg")

    def test_nested_quad_scenes_and_configurations(self):
        self.include_leg()
        project = Project(self.quad)
        scene = new_scene("quad_assembled")
        assembly = project.assemble(scene, "", config={"length": 125})
        self.assertEqual(len(scene.SCENE.bodies), 13)
        self.assertEqual(len(scene.SCENE.decor), 8)
        self.assertEqual(len(scene.SCENE.joints), 12)
        self.assertEqual(catalog.bom()[0].qty, 8)
        self.assertEqual(set(catalog.bom()[0].where),
                         {f"{leg}/{motor}_motor" for leg in ("fl", "fr", "bl", "br")
                          for motor in ("hip", "knee")})
        self.assertIn("fl/hip", assembly.joints)
        self.assertEqual(scene.SCENE.bodies[1].origin, (80, 65, 265))
        catalog.reset()
        alternative = new_scene("quad_alternative")
        project.assemble(alternative, "", scene="links_only", config={"hip_span": 180})
        self.assertFalse(alternative.SCENE.decor)
        self.assertFalse(catalog.USED)
        self.assertEqual(alternative.SCENE.bodies[1].origin, (80, 90, 235))
        self.assertEqual(scene.SCENE.bodies[1].origin, (80, 65, 265))

    def test_transforms_joint_graph_and_namespaces(self):
        project = Project(self.leg)
        scene = new_scene("transformed_project")
        first = project.assemble(scene, "left", origin=(10, 20, 300), rotation=(0, 0, 90))
        second = project.assemble(scene, "right", config={"length": 150, "side": -1},
                                  origin=(100, 0, 400))
        self.assertEqual(first.bodies["thigh"], "left/thigh")
        self.assertEqual(second.bodies["thigh"], "right/thigh")
        hip, knee = scene.SCENE.joints[:2]
        self.assertEqual(hip.a, "left/mount")
        self.assertEqual(hip.b, "left/thigh")
        self.assertEqual(knee.anchor, (10, 20, 190))
        for actual, expected in zip(hip.axis, (-1, 0, 0)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(hip.limits, (-0.9, 0.9))
        self.assertGreater(hip.motor["stiffness"], 0)
        self.assertEqual(scene.SCENE.decor[0].parent, "left/mount")
        for actual, expected in zip(scene.SCENE.decor[0].origin, (-25, 20, 300)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(catalog.bom()[0].qty, 4)
        self.assertEqual(first.config["length"], 110)
        self.assertEqual(second.config["length"], 150)

    def test_failures_are_atomic(self):
        scene = new_scene("atomic_project")
        project = Project(self.leg)
        project.assemble(scene, "existing")
        before = (len(scene.SCENE.bodies), len(scene.SCENE.decor), len(scene.SCENE.joints),
                  len(catalog.USED))
        for name, kw in (("existing", {}), ("bad", {"scene": "missing"}),
                         ("bad", {"config": {"typo": 10}}),
                         ("bad", {"config": {"length": 1}}),
                         ("../escape", {})):
            with self.assertRaises(ValueError):
                project.assemble(scene, name, **kw)
            self.assertEqual(before, (len(scene.SCENE.bodies), len(scene.SCENE.decor),
                                      len(scene.SCENE.joints), len(catalog.USED)))
        self.include_leg()
        (self.quad / "cad/kits/leg/cad/scenes/leg.py").write_text(
            "from subcomponents import get\n"
            "def assembled(scene, config):\n"
            "    get('motor/MN5008').entry\n"
            "    raise ValueError('broken child')\n")
        with self.assertRaises(ValueError):
            Project(self.quad).assemble(scene, "broken")
        self.assertEqual(len(scene.SCENE.bodies), before[0])
        self.assertEqual(len(catalog.USED), before[3])

    def test_project_imports_are_isolated(self):
        other = self.seed("other-leg", "leg-project")
        (other / "cad/scenes/leg.py").write_text(
            "from ..parts.links import links\n"
            "def assembled(scene, config):\n"
            "    links(scene, 170, 12)\n")
        scene = new_scene("isolated_projects")
        Project(self.leg).assemble(scene, "first")
        Project(other).assemble(scene, "second")
        self.assertEqual(scene.SCENE.bodies[2].origin, (0, 0, -110))
        self.assertEqual(scene.SCENE.bodies[5].origin, (0, 0, -170))
        self.assertEqual(len(scene.SCENE.decor), 2)

    def test_manifest_saves_trigger_watcher(self):
        spec = importlib.util.spec_from_file_location("test_watcher", APP / "template/cad/watch.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        triggered = []
        handler = module.Handler(SimpleNamespace(trigger=lambda: triggered.append(True)))
        for type, source, destination in (("modified", "cad/project.json", ""),
                                           ("moved", "cad/tmp", "cad/project.json"),
                                           ("modified", "cad/__pycache__/model.py", ""),
                                           ("opened", "cad/project.json", ""),
                                           ("modified", "cad/unrelated.json", "")):
            handler.on_any_event(SimpleNamespace(is_directory=False, event_type=type,
                                                src_path=source, dest_path=destination))
        self.assertEqual(len(triggered), 2)

    def test_git_pins_clone_and_named_scene_export(self):
        for workspace in (self.leg, self.quad):
            self.git(workspace, "init", "-q")
            self.git(workspace, "add", ".")
            self.git(workspace, "commit", "-qm", "seed project")
        revision = self.git(self.leg, "rev-parse", "HEAD")
        self.cli(self.quad, "sub", "add", "leg")
        self.git(self.quad, "commit", "-qm", "pin leg project")
        self.assertIn("../leg", (self.quad / ".gitmodules").read_text())
        self.assertTrue(self.git(self.quad, "ls-tree", "HEAD", "cad/kits/leg").startswith("160000"))
        copy = self.folder / "clone"
        self.git(self.folder, "-c", "protocol.file.allow=always", "clone", "-q", str(self.quad), str(copy))
        self.cli(copy, "sub", "sync")
        self.assertEqual(self.git(copy / "cad/kits/leg", "rev-parse", "HEAD"), revision)
        self.cli(copy, "sub", "status")
        self.assertIn("wide", self.cli(copy, "scenes").stdout)
        self.cli(copy, "export", "--scene", "wide", "--set", "length=125")
        scene = json.loads((copy / "out/scene.json").read_text())
        self.assertEqual(len(scene["bodies"]), 13)
        self.assertEqual(len(scene["decor"]), 8)
        self.assertEqual(scene["bodies"][1]["origin"], [80, 90, 265])
        self.cli(copy, "bom", "--scene", "wide", "--set", "length=125", "--json")
        bom = json.loads((copy / "out/bom.json").read_text())
        self.assertEqual(bom["items"], 8)
        self.cli(copy, "export", "--scene", "links_only")
        alternative = json.loads((copy / "out/scene.json").read_text())
        self.assertFalse(alternative["decor"])
        self.assertEqual(alternative["bodies"][1]["origin"], [80, 65, 235])
        self.assertEqual(alternative["project"]["scene"], "links_only")
        # A bundle must build its requested configuration, despite a newer
        # viewer export belonging to a different scene.
        self.cli(copy, "bundle", "--scene", "wide", "--set", "hardware=false", "--formats", "step")
        from build123d import import_step
        bundled = import_step(copy / "out/export/clone.step")
        self.assertGreater(bundled.bounding_box().size.Y, 180)
        self.cli(copy, "bundle", "--scene", "wide", "--formats", "glb", success=False)
        self.cli(copy, "bundle", "--scene", "links_only", "--formats", "glb")
        self.cli(copy, "export", "--scene", "missing", success=False)
        self.cli(copy, "export", "--set", "length=oops", success=False)


if __name__ == "__main__":
    unittest.main()
