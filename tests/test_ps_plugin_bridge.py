#!/usr/bin/env python3
"""
Unit tests for bin/ps-plugin-bridge (enabledPlugins filtering, pruning, and context budget management).
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "ps-plugin-bridge"

import importlib.machinery
import importlib.util
loader = importlib.machinery.SourceFileLoader("ps_plugin_bridge", str(SCRIPT_PATH))
spec = importlib.util.spec_from_loader("ps_plugin_bridge", loader)
bridge_mod = importlib.util.module_from_spec(spec)
loader.exec_module(bridge_mod)


class TestPluginBridge(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.installed_json = self.tmp_path / "installed_plugins.json"
        self.settings_json = self.tmp_path / "settings.json"
        self.gemini_plugins_dir = self.tmp_path / "gemini_plugins"
        self.gemini_plugins_dir.mkdir(parents=True, exist_ok=True)

        # Setup mock installed plugins
        self.plugin_a = self.tmp_path / "cache" / "plugin-a"
        self.plugin_b = self.tmp_path / "cache" / "plugin-b"
        for p in [self.plugin_a, self.plugin_b]:
            p.mkdir(parents=True, exist_ok=True)
            (p / "plugin.json").write_text('{"name": "' + p.name + '"}', encoding="utf-8")
            skills_dir = p / "skills" / "my-skill"
            skills_dir.mkdir(parents=True, exist_ok=True)
            (skills_dir / "SKILL.md").write_text("# Skill", encoding="utf-8")

        installed_data = {
            "version": 2,
            "plugins": {
                "plugin-a@official": [{"installPath": str(self.plugin_a), "version": "1.0.0"}],
                "plugin-b@official": [{"installPath": str(self.plugin_b), "version": "2.0.0"}],
            }
        }
        self.installed_json.write_text(json.dumps(installed_data), encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_respects_enabled_plugins_pruning(self):
        # plugin-a enabled, plugin-b disabled
        settings_data = {
            "enabledPlugins": {
                "plugin-a@official": True,
                "plugin-b@official": False,
            }
        }
        self.settings_json.write_text(json.dumps(settings_data), encoding="utf-8")

        # Simulate plugin-b previously bridged
        target_b = self.gemini_plugins_dir / "plugin-b"
        target_b.symlink_to(self.plugin_b)
        self.assertTrue(target_b.is_symlink())

        bridge = bridge_mod.PluginBridge(
            installed_json=str(self.installed_json),
            claude_settings=str(self.settings_json),
            gemini_plugins_dir=str(self.gemini_plugins_dir),
            dry_run=False,
        )

        entries = bridge.get_plugin_entries()
        self.assertEqual(len(entries), 2)
        entry_a = next(e for e in entries if e["name"] == "plugin-a")
        entry_b = next(e for e in entries if e["name"] == "plugin-b")
        self.assertTrue(entry_a["enabled"])
        self.assertFalse(entry_b["enabled"])

        # Run sync
        ret = bridge.sync_plugins()
        self.assertEqual(ret, 0)

        # plugin-a should be symlinked
        target_a = self.gemini_plugins_dir / "plugin-a"
        self.assertTrue(target_a.is_symlink())
        self.assertEqual(target_a.resolve(), self.plugin_a.resolve())

        # plugin-b should be pruned from gemini_plugins_dir
        self.assertFalse(target_b.exists())
        self.assertFalse(target_b.is_symlink())

    def test_all_flag_bridges_disabled(self):
        settings_data = {
            "enabledPlugins": {
                "plugin-a@official": False,
                "plugin-b@official": False,
            }
        }
        self.settings_json.write_text(json.dumps(settings_data), encoding="utf-8")

        bridge = bridge_mod.PluginBridge(
            installed_json=str(self.installed_json),
            claude_settings=str(self.settings_json),
            gemini_plugins_dir=str(self.gemini_plugins_dir),
            dry_run=False,
            all_plugins=True,
        )

        ret = bridge.sync_plugins()
        self.assertEqual(ret, 0)
        self.assertTrue((self.gemini_plugins_dir / "plugin-a").is_symlink())
        self.assertTrue((self.gemini_plugins_dir / "plugin-b").is_symlink())

    def test_exclude_flag_skips_specified_plugin(self):
        settings_data = {
            "enabledPlugins": {
                "plugin-a@official": True,
                "plugin-b@official": True,
            }
        }
        self.settings_json.write_text(json.dumps(settings_data), encoding="utf-8")

        bridge = bridge_mod.PluginBridge(
            installed_json=str(self.installed_json),
            claude_settings=str(self.settings_json),
            gemini_plugins_dir=str(self.gemini_plugins_dir),
            dry_run=False,
            exclude=["plugin-a"],
        )

        ret = bridge.sync_plugins()
        self.assertEqual(ret, 0)
        self.assertFalse((self.gemini_plugins_dir / "plugin-a").exists())
        self.assertTrue((self.gemini_plugins_dir / "plugin-b").is_symlink())


if __name__ == "__main__":
    unittest.main()
