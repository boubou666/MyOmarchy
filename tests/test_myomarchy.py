from pathlib import Path
import unittest
from unittest.mock import patch

import myomarchy
import versions


BUILDER = """#!/bin/bash
cp "${base_pkg_lists[0]}" "$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-base.packages"
cp "${base_pkg_lists[1]}" "$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-other.packages"
mapfile -t all_packages < <(
  {
    cat "$build_cache_dir/packages.x86_64"
    grep -hv '^#\\|^$' "${base_pkg_lists[@]}"
  } | sort -u
)
mkarchiso -v -w "$build_cache_dir/work/" -o /out/ "$build_cache_dir/"
"""


class MyOmarchyTests(unittest.TestCase):
    def test_package_selection_validation_and_deduplication(self):
        path = Path("packages.txt")
        with patch.object(Path, "read_text", return_value="# comment\nfirefox\ngimp\nfirefox\n"):
            self.assertEqual(myomarchy.packages_from(path), ["firefox", "gimp"])
        with patch.object(Path, "read_text", return_value="firefox --overwrite /\n"):
            with self.assertRaises(myomarchy.ToolError):
                myomarchy.packages_from(path)

    def test_builder_bundles_and_installs_same_selection(self):
        patched = myomarchy.patch_builder(BUILDER)
        self.assertIn("cat /builder/myomarchy.packages >>", patched)
        self.assertIn("apple-bcm-firmware-fetcher", patched)
        self.assertIn(myomarchy.SHIPPED_LIST, patched)
        self.assertNotIn(myomarchy.SOURCE_LIST, patched)
        self.assertIn('python /builder/myomarchy-verify.py', patched)

    def test_builder_drift_fails_closed(self):
        with self.assertRaises(myomarchy.ToolError):
            myomarchy.patch_builder(BUILDER.replace(myomarchy.SOURCE_LIST, "echo changed"))
        with self.assertRaises(myomarchy.ToolError):
            myomarchy.patch_builder(BUILDER.replace(myomarchy.ISO_BUILD_LINE, "echo changed"))
        with self.assertRaises(myomarchy.ToolError):
            myomarchy.patch_builder(myomarchy.patch_builder(BUILDER))

    def test_docker_command_mounts_the_same_build_inputs_on_any_host(self):
        root = Path("/tmp/myomarchy")
        command = myomarchy.docker_build_command(root, root / "release", root / "cache")
        self.assertEqual(command[:6], ["docker", "run", "--rm", "--privileged", "--platform", "linux/amd64"])
        self.assertIn("OMARCHY_MIRROR=stable", command)
        self.assertIn("archlinux/archlinux:latest", command)
        self.assertEqual(command[-2:], ["/bin/bash", "/builder/build-iso.sh"])
        mounts = [command[i + 1] for i, value in enumerate(command[:-1]) if value == "--mount"]
        self.assertTrue(any("target=/builder,readonly" in item for item in mounts))
        self.assertTrue(any("target=/archiso,readonly" in item for item in mounts))
        self.assertTrue(any("target=/configs,readonly" in item for item in mounts))
        self.assertTrue(any("target=/out" in item for item in mounts))

    def test_release_command_pins_source_and_matching_recipes(self):
        root = Path("/tmp/myomarchy")
        target = versions.TARGETS["v4.0.3"]
        command = myomarchy.docker_build_command(
            root, root / "release", root / "cache", target,
            (root / "omarchy", root / "omarchy-pkgs")
        )
        self.assertIn("OMARCHY_ISO_REF=v4.0.3", command)
        self.assertIn("OMARCHY_MIRROR=stable", command)
        self.assertIn("OMARCHY_RUNTIME_PACKAGE=omarchy", command)
        mounts = [command[i + 1] for i, value in enumerate(command[:-1]) if value == "--mount"]
        self.assertTrue(any("target=/omarchy-source,readonly" in item for item in mounts))
        self.assertTrue(any("target=/omarchy-pkgs,readonly" in item for item in mounts))

    def test_usb_rejects_partition_and_fixed_disk(self):
        for entry in (
            {"path": "/dev/sdb", "type": "part", "rm": True, "tran": "usb"},
            {"path": "/dev/sdb", "type": "disk", "rm": False, "tran": "sata"},
            {"path": "/dev/sdb", "type": "disk", "rm": True, "tran": "usb", "children": [{"mountpoints": ["/media/usb"]}]},
        ):
            with self.subTest(entry=entry):
                with patch.object(myomarchy.sys, "platform", "linux"), \
                     patch.object(myomarchy.os.path, "realpath", return_value="/dev/sdb"), \
                     patch.object(myomarchy.subprocess, "run") as run:
                    run.return_value.stdout = '{"blockdevices": [' + __import__("json").dumps(entry) + ']}'
                    with self.assertRaises(myomarchy.ToolError):
                        myomarchy.device_info("/dev/sdb")


if __name__ == "__main__":
    unittest.main()
