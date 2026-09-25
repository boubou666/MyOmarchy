#!/usr/bin/env python3
"""Build and write an Omarchy ISO with additional offline pacman packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import versions


ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".build"
CHECKOUT = WORK / "omarchy-iso"
UPSTREAM = "https://github.com/omacom/omarchy-iso.git"
BRANCH = "quattro"
OMARCHY_REPO = "https://github.com/omacom/omarchy.git"
PKGS_REPO = "https://github.com/omacom/omarchy-pkgs.git"
PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9@._+\-]*$")
COPY_BASE = 'cp "${base_pkg_lists[0]}" "$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-base.packages"'
COPY_OTHER = 'cp "${base_pkg_lists[1]}" "$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-other.packages"'
SOURCE_LIST = 'grep -hv \'^#\\|^$\' "${base_pkg_lists[@]}"'
SHIPPED_LIST = (
    'grep -hv \'^#\\|^$\' '
    '"$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-base.packages" '
    '"$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-other.packages"'
)
ISO_BUILD_LINE = 'mkarchiso -v -w "$build_cache_dir/work/" -o /out/ "$build_cache_dir/"'
ISO_VERIFICATION = """# MyOmarchy: inspect the finished ISO, not just the builder staging tree.
myomarchy_build_marker=$(mktemp)
mkarchiso -v -w "$build_cache_dir/work/" -o /out/ "$build_cache_dir/"
myomarchy_iso=$(find /out -maxdepth 1 -type f -name '*.iso' -newer "$myomarchy_build_marker" -print -quit)
rm -f "$myomarchy_build_marker"
if [[ -z $myomarchy_iso ]]; then
  echo "ERROR: no newly built ISO to verify" >&2
  exit 1
fi
pacman --noconfirm -S --needed python
python /builder/myomarchy-verify.py "$myomarchy_iso" /builder/myomarchy.packages"""
INSTALLER_CALL = "installer.add_additional_packages(_runtime_package_list(ctx))"
INJECTION = """# MyOmarchy: include selected packages in the target install list.
# The T2 repository removed apple-bcm-firmware. Keep the optional offline
# inventory resolvable with its on-disk firmware fetcher replacement.
if grep -Fxq apple-bcm-firmware "$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-other.packages"; then
  sed -i 's/^apple-bcm-firmware$/apple-bcm-firmware-fetcher/' "$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-other.packages"
  echo "Note: apple-bcm-firmware is unavailable; bundling apple-bcm-firmware-fetcher instead. T2 Mac firmware setup is unverified."
fi
if [[ -s /builder/myomarchy.packages ]]; then
  printf '\\n' >> "$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-base.packages"
  cat /builder/myomarchy.packages >> "$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-base.packages"
fi"""


class ToolError(Exception):
    pass


def packages_from(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ToolError(f"Package list not found: {path}") from exc
    packages = []
    seen = set()
    for number, raw in enumerate(lines, 1):
        value = raw.split("#", 1)[0].strip()
        if not value:
            continue
        if not PACKAGE_NAME.fullmatch(value):
            raise ToolError(f"Invalid package name on {path}:{number}: {value!r}")
        if value not in seen:
            packages.append(value)
            seen.add(value)
    if not packages:
        raise ToolError(f"Select at least one package in {path}")
    return packages


def run(*args: str, cwd: Path | None = None) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def normalize_lf_tree(root: Path) -> None:
    """Undo Windows Git CRLF conversion in private, container-mounted sources."""
    if sys.platform != "win32":
        return
    changed = 0
    for base, directories, filenames in os.walk(root):
        directories[:] = [name for name in directories if name not in (".git", "release", "test-runs")]
        for name in filenames:
            path = Path(base) / name
            if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
                continue
            data = path.read_bytes()
            if b"\r\n" not in data or b"\x00" in data:
                continue
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            path.write_bytes(data.replace(b"\r\n", b"\n"))
            changed += 1
    if changed:
        print(f"Restored Unix line endings in {changed} private source file(s) under {root}.", flush=True)


def patch_builder(original: str) -> str:
    """Fail closed if upstream changes the package-list handoff."""
    if original.count(COPY_BASE) != 1 or original.count(COPY_OTHER) != 1:
        raise ToolError("Upstream ISO builder changed its package-copy step; review the integration")
    if original.count(SOURCE_LIST) != 1:
        raise ToolError("Upstream ISO builder changed its mirror package list; review the integration")
    if original.count(ISO_BUILD_LINE) != 1:
        raise ToolError("Upstream ISO builder changed its ISO output step; review the integration")
    if original.count(SHIPPED_LIST) or "# MyOmarchy:" in original:
        raise ToolError("The upstream builder is already customized")
    patched = original.replace(COPY_OTHER, COPY_OTHER + "\n" + INJECTION, 1)
    patched = patched.replace(SOURCE_LIST, SHIPPED_LIST, 1)
    patched = patched.replace(ISO_BUILD_LINE, ISO_VERIFICATION, 1)
    return patched


def prepare(package_file: Path, source: Path | None, target: versions.Target | None = None) -> list[str]:
    target = target or versions.TARGETS["stable"]
    packages = packages_from(package_file)
    WORK.mkdir(exist_ok=True)
    if not CHECKOUT.exists():
        if source:
            source = source.resolve()
            if not (source / "bin/omarchy-iso-make").is_file():
                raise ToolError(f"Not an Omarchy ISO checkout: {source}")
            print(f"Copying ISO source from {source}")
            shutil.copytree(source, CHECKOUT, ignore=shutil.ignore_patterns("release", "test-runs"))
        else:
            run("git", "-c", "core.autocrlf=false", "clone", "--depth", "1", "--branch", BRANCH,
                "--recurse-submodules", UPSTREAM, str(CHECKOUT))
    elif source:
        raise ToolError("A prepared checkout already exists; --source applies only to a fresh checkout")

    builder = CHECKOUT / "builder/build-iso.sh"
    original_file = WORK / "upstream-build-iso.sh"
    if not original_file.exists():
        original = builder.read_text(encoding="utf-8")
        # Validate before saving it as the pristine upstream copy.
        patch_builder(original)
        original_file.write_text(original, encoding="utf-8", newline="\n")
    original = original_file.read_text(encoding="utf-8")
    builder.write_text(patch_builder(original), encoding="utf-8", newline="\n")
    installer = CHECKOUT / "configs/airootfs/usr/share/omarchy-iso/orchestrator/phases_impl.py"
    installer_source = installer.read_text(encoding="utf-8")
    if installer_source.count(INSTALLER_CALL) != 1 or installer_source.count(
        'Path("/usr/share/omarchy-iso/omarchy-base.packages")'
    ) != 1:
        raise ToolError("Upstream installer changed how it installs the shipped package list")
    (CHECKOUT / "builder/myomarchy.packages").write_text(
        "\n".join(packages) + "\n", encoding="utf-8", newline="\n"
    )
    shutil.copyfile(ROOT / "verify_iso.py", CHECKOUT / "builder/myomarchy-verify.py")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=CHECKOUT, text=True,
        capture_output=True, check=True
    ).stdout.strip()
    (WORK / "manifest.json").write_text(
        json.dumps({"upstream_revision": revision, "target": target.key,
                    "omarchy_source_revision": target.source_commit,
                    "package_recipes_revision": target.recipes_commit,
                    "packages": packages}, indent=2) + "\n",
        encoding="utf-8"
    )
    print(f"Prepared Omarchy {revision[:12]} with {len(packages)} selected package(s).")
    return packages


def release_sources(target: versions.Target) -> tuple[Path, Path] | None:
    if not target.source_commit:
        return None
    release_root = WORK / "releases" / target.key
    omarchy_source = release_root / "omarchy"
    recipes_source = release_root / "omarchy-pkgs"
    release_root.mkdir(parents=True, exist_ok=True)
    if not omarchy_source.exists():
        run("git", "-c", "core.autocrlf=false", "clone", "--depth", "1", "--branch", target.key,
            OMARCHY_REPO, str(omarchy_source))
    if not (recipes_source / ".git").exists():
        recipes_source.mkdir(exist_ok=True)
        run("git", "init", cwd=recipes_source)
        run("git", "remote", "add", "origin", PKGS_REPO, cwd=recipes_source)
    if not (recipes_source / "pkgbuilds" / "omarchy" / "PKGBUILD").exists():
        run("git", "fetch", "--depth", "1", "origin", target.recipes_commit, cwd=recipes_source)
        run("git", "-c", "core.autocrlf=false", "checkout", "--detach", "FETCH_HEAD", cwd=recipes_source)
    for path, expected in ((omarchy_source, target.source_commit),
                           (recipes_source, target.recipes_commit)):
        actual = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                                text=True, capture_output=True, check=True).stdout.strip()
        if actual != expected:
            raise ToolError(f"Cached {path.name} checkout does not match {target.key}")
    for package in ("omarchy", "omarchy-settings"):
        recipe = (recipes_source / "pkgbuilds" / package / "PKGBUILD").read_text(encoding="utf-8")
        if (f"_tag='{target.key}'" not in recipe or
                f"_commit='{target.source_commit}'" not in recipe or
                f"pkgver={target.key.removeprefix('v')}" not in recipe):
            raise ToolError(f"Official {package} recipe does not match {target.key}")
    return omarchy_source, recipes_source


def build(package_file: Path, source: Path | None, target: versions.Target | None = None) -> None:
    target = target or versions.TARGETS["stable"]
    if shutil.which("docker") is None:
        raise ToolError("Docker is required to build the ISO")
    info = subprocess.run(["docker", "info", "--format", "{{.OSType}}"],
                          capture_output=True, text=True)
    if info.returncode != 0:
        raise ToolError("Docker is not running. Start Docker Desktop or Docker Engine and try again")
    if info.stdout.strip() != "linux":
        raise ToolError("Docker must be switched to Linux containers")
    packages = prepare(package_file, source, target)
    run("git", "-c", "core.autocrlf=false", "submodule", "update", "--init", "--recursive", "--jobs=8", cwd=CHECKOUT)
    sources = release_sources(target)
    normalize_lf_tree(CHECKOUT)
    if sources:
        for item in sources:
            normalize_lf_tree(item)
    release = CHECKOUT / "release"
    release.mkdir(exist_ok=True)
    cache = WORK / "offline-mirror-cache" / target.key
    cache.mkdir(parents=True, exist_ok=True)
    before = {p: p.stat().st_mtime_ns for p in release.glob("*.iso")}
    command = docker_build_command(CHECKOUT, release, cache, target, sources)
    run(*command, cwd=CHECKOUT)
    isos = [p for p in release.glob("*.iso")
            if p not in before or p.stat().st_mtime_ns != before[p]]
    if not isos:
        raise ToolError("Builder finished but did not produce a new ISO")
    iso = max(isos, key=lambda p: p.stat().st_mtime_ns)
    report_path = iso.with_name(iso.name + ".verification.json")
    if not report_path.is_file():
        raise ToolError("Builder did not leave an ISO verification report")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (report.get("iso") != iso.name or
            {item["name"] for item in report.get("packages", [])} != set(packages)):
        raise ToolError("ISO verification report does not match the selected packages")
    revision = json.loads((WORK / "manifest.json").read_text(encoding="utf-8"))["upstream_revision"]
    selection_hash = hashlib.sha256("\n".join(packages).encode("utf-8")).hexdigest()[:8]
    final_iso = release / f"omarchy-custom-{target.key}-{revision[:8]}-{selection_hash}.iso"
    if iso != final_iso:
        iso.replace(final_iso)
        new_report = final_iso.with_name(final_iso.name + ".verification.json")
        report_path.replace(new_report)
        report_path = new_report
    iso = final_iso
    digest = sha256_file(iso)
    report["iso"] = iso.name
    report["iso_sha256"] = digest
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (iso.parent / (iso.name + ".sha256")).write_text(
        f"{digest}  {iso.name}\n", encoding="ascii"
    )
    print(f"Built: {iso}\nSHA256: {digest}")


def docker_build_command(checkout: Path, release: Path, cache: Path,
                         target: versions.Target | None = None,
                         sources: tuple[Path, Path] | None = None) -> list[str]:
    """Run upstream's Arch container without its Linux-only host wrapper."""
    target = target or versions.TARGETS["stable"]
    def mount(source: Path, target: str, readonly: bool = False) -> str:
        source = source.resolve()
        return f"type=bind,source={source},target={target}" + (",readonly" if readonly else "")

    command = ["docker", "run", "--rm", "--privileged", "--platform", "linux/amd64",
               "-e", f"OMARCHY_ISO_REF={target.iso_ref}", "-e", f"OMARCHY_MIRROR={target.channel}",
               "-e", "OMARCHY_INSTALL_DEBUG="]
    if sources:
        command += ["-e", "OMARCHY_RUNTIME_PACKAGE=omarchy",
                    "-e", "OMARCHY_SETTINGS_PACKAGE=omarchy-settings"]
    if hasattr(os, "getuid"):
        command += ["-e", f"HOST_UID={os.getuid()}", "-e", f"HOST_GID={os.getgid()}"]
    command += ["--mount", mount(release, "/out"),
               "--mount", mount(checkout / "archiso", "/archiso", True),
               "--mount", mount(checkout / "builder", "/builder", True),
               "--mount", mount(checkout / "configs", "/configs", True),
               "--mount", mount(cache, "/var/cache/airootfs/var/cache/omarchy")]
    if sources:
        command += ["--mount", mount(sources[0], "/omarchy-source", True),
                    "--mount", mount(sources[1], "/omarchy-pkgs", True)]
    command += ["archlinux/archlinux:latest", "/bin/bash", "/builder/build-iso.sh"]
    return command


def sha256_file(path: Path, limit: int | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        remaining = limit
        while remaining is None or remaining > 0:
            chunk = stream.read(min(4 * 1024 * 1024, remaining) if remaining is not None else 4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    if limit is not None and remaining:
        raise ToolError("USB readback ended before the ISO image size")
    return digest.hexdigest()


def verified_release(iso: Path, check_digest: bool = False) -> dict:
    """Require a matching report and sidecar before exposing or flashing an ISO."""
    if not iso.is_file() or not iso.name.startswith("omarchy-custom-") or iso.suffix != ".iso":
        raise ToolError("Choose a completed MyOmarchy ISO")
    report_path = iso.with_name(iso.name + ".verification.json")
    checksum_path = iso.with_name(iso.name + ".sha256")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        checksum = checksum_path.read_text(encoding="ascii").strip().split()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ToolError("ISO verification report or checksum is missing") from exc
    if (report.get("iso") != iso.name or not isinstance(report.get("packages"), list)
            or not report["packages"] or any(not isinstance(item, dict) or not item.get("name")
                                              for item in report["packages"])
            or len(checksum) != 2 or checksum[1] != iso.name
            or checksum[0] != report.get("iso_sha256")):
        raise ToolError("ISO verification report and checksum disagree")
    if check_digest and sha256_file(iso) != checksum[0]:
        raise ToolError("ISO checksum differs from the verified build")
    return report


def device_info(device: str) -> dict:
    if sys.platform != "linux":
        raise ToolError("USB writing is supported on Linux only")
    if not device.startswith("/dev/") or os.path.realpath(device) != device:
        raise ToolError("Pass the canonical whole-disk path, such as /dev/sdb")
    result = subprocess.run(
        ["lsblk", "--json", "--bytes", "--output", "PATH,TYPE,RM,TRAN,SIZE,MODEL,SERIAL,MOUNTPOINTS", device],
        text=True, capture_output=True, check=True
    )
    items = json.loads(result.stdout)["blockdevices"]
    if len(items) != 1:
        raise ToolError("Could not identify exactly one target disk")
    disk = items[0]
    if disk.get("path") != device or disk.get("type") != "disk":
        raise ToolError("Target must be a whole disk, not a partition")
    if str(disk.get("rm")) not in ("1", "True", "true") or disk.get("tran") != "usb":
        raise ToolError("Target must be a removable USB disk")
    def mounted(node: dict) -> bool:
        return bool([p for p in (node.get("mountpoints") or []) if p]) or any(
            mounted(child) for child in node.get("children", [])
        )
    if mounted(disk):
        raise ToolError("Unmount every partition on the USB disk before writing")
    return disk


def flash(iso: Path, device: str, confirmation: str | None = None) -> None:
    if not iso.is_file() or iso.suffix.lower() != ".iso":
        raise ToolError(f"ISO file not found: {iso}")
    verified_release(iso, check_digest=True)
    disk = device_info(device)
    if int(disk["size"]) < iso.stat().st_size:
        raise ToolError("USB disk is smaller than the ISO")
    print(f"ISO: {iso} ({iso.stat().st_size:,} bytes)")
    print(f"USB: {device}  {disk.get('model') or ''}  {disk.get('serial') or ''}  ({int(disk['size']):,} bytes)")
    if confirmation is None:
        confirmation = input(f"This erases the entire USB disk. Type ERASE {device} to continue: ")
    if confirmation != f"ERASE {device}":
        raise ToolError("USB write cancelled")
    # Recheck immediately before writing in case device state changed during prompt.
    again = device_info(device)
    if (again.get("serial"), again.get("size")) != (disk.get("serial"), disk.get("size")):
        raise ToolError("USB device changed after confirmation")
    run("dd", f"if={iso}", f"of={device}", "bs=4M", "status=progress", "conv=fsync")
    run("sync")
    if sha256_file(iso) != sha256_file(Path(device), iso.stat().st_size):
        raise ToolError("USB readback differs from the ISO")
    print("USB image written and verified.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_cmd = commands.add_parser("plan", help="Validate and show selected packages")
    prepare_cmd = commands.add_parser("prepare", help="Clone/copy and customize the upstream builder")
    build_cmd = commands.add_parser("build", help="Build the custom ISO with Docker")
    flash_cmd = commands.add_parser("flash", help="Write and verify the ISO on a removable Linux USB disk")
    for command in (plan_cmd, prepare_cmd, build_cmd):
        command.add_argument("--packages", type=Path, default=ROOT / "packages.txt")
    for command in (prepare_cmd, build_cmd):
        command.add_argument("--source", type=Path, help="Existing upstream Omarchy ISO checkout")
        command.add_argument("--target", choices=versions.TARGETS, default="stable")
    flash_cmd.add_argument("--iso", type=Path, required=True)
    flash_cmd.add_argument("--device", required=True)
    flash_cmd.add_argument("--confirm", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            for package in packages_from(args.packages):
                print(package)
        elif args.command == "prepare":
            prepare(args.packages, args.source, versions.TARGETS[args.target])
        elif args.command == "build":
            build(args.packages, args.source, versions.TARGETS[args.target])
        else:
            flash(args.iso, args.device, args.confirm)
    except (ToolError, subprocess.CalledProcessError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
