"""Integration checks for persisted library definitions and staged CAD previews."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from test_subcomponents import APP, new_scene
from subcomponents.project import Project
import projectio

class EditorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/"design"
        shutil.copytree(APP/"template/cad", self.root/"cad")
        (self.root/"cad/model.py").write_text('from build123d import Box\nimport scene\nscene.body("link", Box(20,10,5), mass=0.2)\n')
        self.cli("project", "discover")
        projectio.upgrade(self.root, APP)
    def cli(self, *args, success=True):
        result = subprocess.run([str(APP/"bin/caliper"), *args], env={**os.environ, "WORKSPACE":str(self.root), "APP_DIR":str(APP), "CAD_PYTHON":sys.executable}, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)
        return result
    def save(self, data):
        projectio.validate(data, self.root); projectio.write(self.root/"cad/project.json", data)
    def test_legacy_part_preview_source_and_failed_export_retains_geometry(self):
        self.cli("export")
        active = (self.root/"out/model.glb").read_bytes()
        self.cli("project", "preview", "--kind", "component", "--name", "link", "--config", '{"scale":2}', "--out", str(self.root/"out/isolated"))
        data=json.loads((self.root/"out/isolated/scene.json").read_text())
        self.assertEqual(len(data["bodies"]),1)
        self.assertEqual(data["bodies"][0]["mass"],1.6)
        self.assertEqual(data["bodies"][0]["source"],"cad/legacy_model.py")
        self.assertEqual((self.root/"out/model.glb").read_bytes(), active)
        (self.root/"cad/legacy_model.py").write_text('raise ValueError("broken source")\n')
        self.cli("export", success=False)
        self.assertEqual((self.root/"out/model.glb").read_bytes(),active)
    def test_nested_instances_scenes_interfaces_and_cycle_rejection(self):
        data=projectio.manifest(self.root)
        name=projectio.new_component(self.root,data,"Motor", "motor")
        data["components"][name]["interfaces"]={"shaft":{"body":"part","anchor":[0,0,35],"axis":[0,0,1]}}
        data["assemblies"]={"leg":{"instances":[{"name":"drive","component":"motor","origin":[10,0,0]},{"name":"link","component":"link","origin":[10,0,40]}],"joints":[{"name":"hip","type":"revolute","a":"@drive/shaft","b":"link/part","anchor":[0,0,0]}]},"quad":{"instances":[{"name":"fl","assembly":"leg","origin":[50,0,0]},{"name":"fr","assembly":"leg","origin":[-50,0,0]}]}}
        data["scenes"]["standing"]={"assembly":"quad","parameters":{},"environment":{"ground":True}}
        data["active_scene"]="standing"; self.save(data)
        self.cli("export")
        exported=json.loads((self.root/"out/scene.json").read_text())
        self.assertEqual(len(exported["bodies"]),5)
        self.assertEqual(len(exported["joints"]),2)
        self.assertEqual(exported["joints"][0]["anchor"],[60,0,35])
        self.assertEqual(exported["interfaces"]["assembly/fl/drive/shaft"]["anchor"],[60,0,35])
        data["assemblies"]["leg"]["instances"].append({"name":"loop","assembly":"quad"})
        with self.assertRaisesRegex(ValueError,"cyclic"): projectio.validate(data,self.root)
    def test_source_builder_parameters_and_manifest_owner(self):
        data=projectio.manifest(self.root)
        name=projectio.new_component(self.root,data,"Long link", "box")
        data["components"][name]["parameters"]["length"]=180; self.save(data)
        self.cli("project", "preview", "--kind", "component", "--name", name,"--out", str(self.root/"out/part"))
        idx=json.loads((self.root/"out/part/project-index.json").read_text())
        self.assertEqual(idx["nodes"][0]["size"],[180,30,20])
        self.assertEqual(idx["nodes"][0]["source"],"cad/components/long_link.py")
        with self.assertRaises(ValueError): projectio.project_root(self.root,"../other")
        with self.assertRaisesRegex(ValueError,"unknown configuration"): Project(self.root).assemble(new_scene("invalidconfig"),"",kind="component",scene=name,config={"made_up":1})

    def test_extracted_subassembly_retains_its_own_hardware_usage(self):
        (self.root/"cad/legacy_model.py").write_text('from build123d import Box\nimport scene\nfrom catalog import use\ndef leg(name):\n    scene.body(name+"_link", Box(20,10,5))\n    use("motor/MN5008", where="hip reduction")\nleg("fl")\nleg("fr")\n')
        (self.root/"cad/assemblies").mkdir(exist_ok=True)
        (self.root/"cad/assemblies/leg.py").write_text('from pathlib import Path\nfrom subcomponents.editor import original_assembly\ndef build(scene, config):\n    original_assembly(scene, Path(__file__).resolve().parents[1], ["fl_link"], prefix="fl_")\n')
        data=projectio.manifest(self.root)
        data["assemblies"]={"leg":{"builder":"assemblies.leg:build"}}
        data["scenes"]["pair"]={"instances":[{"name":"left","assembly":"leg"},{"name":"right","assembly":"leg"}]}
        self.save(data)
        result=self.cli("bom", "--scene", "pair")
        self.assertIn("MN5008", result.stdout)
        # Both original legs are built to recover geometry, but only the
        # selected leg's hardware is copied into each reusable instance.
        scene=new_scene("extracted_bom")
        import catalog
        catalog.reset()
        Project(self.root).assemble(scene,"",scene="pair")
        self.assertEqual(catalog.bom()[0].qty,2)
        self.assertEqual(set(catalog.bom()[0].where),{"left/hip reduction","right/hip reduction"})
