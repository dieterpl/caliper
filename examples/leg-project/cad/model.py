"""Named scene entry point for both standalone export and parent reuse."""
import scene
from subcomponents.project import load_scene

load_scene(scene, __file__)
