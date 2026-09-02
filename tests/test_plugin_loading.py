import subprocess
import sys
from pathlib import Path
from unittest import TestCase


class PluginLoadingTests(TestCase):
    def test_plugin_loads_with_maibot_runner_package_layout(self) -> None:
        plugin_dir = Path(__file__).resolve().parents[1]
        script = """
import importlib.util
import sys
from pathlib import Path

plugin_dir = Path(sys.argv[1])
plugin_path = plugin_dir / "plugin.py"
module_name = "maibot_ext_qianqian_plugins"
spec = importlib.util.spec_from_file_location(
    module_name,
    plugin_path,
    submodule_search_locations=[str(plugin_dir)],
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[module_name] = module
sys.path.insert(0, str(plugin_dir.parent))
spec.loader.exec_module(module)
assert type(module.create_plugin()).__name__ == "QianqianPlugin"
"""

        result = subprocess.run(
            [sys.executable, "-I", "-c", script, str(plugin_dir)],
            cwd=plugin_dir.parent,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
