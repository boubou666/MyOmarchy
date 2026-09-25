#!/usr/bin/env python3
"""Verify selected packages in the finished Omarchy ISO, inside the builder container."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory


SQUASHFS_MEMBER = "arch/x86_64/airootfs.sfs"
PACKAGE_LIST_MEMBER = "usr/share/omarchy-iso/omarchy-base.packages"
REPO_DB_MEMBER = "var/cache/omarchy/mirror/offline/offline.db.tar.gz"
REPO_PACKAGE_DIR = "var/cache/omarchy/mirror/offline"
INSTALLER_MEMBER = "usr/share/omarchy-iso/orchestrator/phases_impl.py"


class VerificationError(Exception):
    pass


def command_bytes(command: list[str]) -> bytes:
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise VerificationError(f"Could not read ISO member with {' '.join(command[:2])}: "
                                f"{result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def stream_hash(command: list[str], destination: Path | None, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        assert process.stdout is not None
        output = destination.open("wb") if destination else None
        try:
            for block in iter(lambda: process.stdout.read(4 * 1024 * 1024), b""):
                digest.update(block)
                if output:
                    output.write(block)
        finally:
            if output:
                output.close()
        if process.wait():
            raise VerificationError(f"Could not read ISO member with {' '.join(command[:2])}")
    return digest.hexdigest()


def repo_entries(database: bytes) -> dict[str, dict[str, str]]:
    entries = {}
    with tarfile.open(fileobj=io.BytesIO(database), mode="r:gz") as archive:
        for item in archive:
            if not item.isfile() or not item.name.endswith("/desc"):
                continue
            stream = archive.extractfile(item)
            if stream is None:
                continue
            fields = {}
            lines = stream.read().decode("utf-8").splitlines()
            for index, line in enumerate(lines[:-1]):
                if line.startswith("%") and line.endswith("%") and lines[index + 1]:
                    fields[line.strip("%")] = lines[index + 1]
            if "NAME" in fields:
                entries[fields["NAME"]] = fields
    return entries


def verify(iso: Path, selection: Path) -> dict:
    packages = [line.strip() for line in selection.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not packages:
        raise VerificationError("The selected package list is empty")
    with TemporaryDirectory(prefix="myomarchy-verify-") as directory:
        image = Path(directory) / "airootfs.sfs"
        expected = command_bytes(["bsdtar", "-xOf", str(iso), "arch/x86_64/airootfs.sha512"])
        try:
            expected_digest = expected.split(maxsplit=1)[0].decode("ascii")
        except (IndexError, UnicodeDecodeError) as exc:
            raise VerificationError("The ISO has no valid airootfs checksum") from exc
        if len(expected_digest) != 128 or any(char not in "0123456789abcdef" for char in expected_digest.lower()):
            raise VerificationError("The ISO has an invalid airootfs checksum")
        actual_digest = stream_hash(["bsdtar", "-xOf", str(iso), SQUASHFS_MEMBER], image, "sha512")
        if actual_digest != expected_digest.lower():
            raise VerificationError("The ISO's airootfs checksum does not match its SquashFS image")

        shipped = command_bytes(["unsquashfs", "-cat", str(image), PACKAGE_LIST_MEMBER]).decode("utf-8")
        shipped_names = {line.strip() for line in shipped.splitlines()
                         if line.strip() and not line.lstrip().startswith("#")}
        missing_list = sorted(set(packages) - shipped_names)
        if missing_list:
            raise VerificationError(f"Selected packages missing from ISO install list: {', '.join(missing_list)}")
        installer = command_bytes(["unsquashfs", "-cat", str(image), INSTALLER_MEMBER]).decode("utf-8")
        if (installer.count("installer.add_additional_packages(_runtime_package_list(ctx))") != 1 or
                installer.count('Path("/usr/share/omarchy-iso/omarchy-base.packages")') != 1):
            raise VerificationError("The ISO installer no longer installs the shipped package list")

        database = command_bytes(["unsquashfs", "-cat", str(image), REPO_DB_MEMBER])
        entries = repo_entries(database)
        checked = []
        for name in packages:
            entry = entries.get(name)
            if not entry or not entry.get("FILENAME") or not entry.get("SHA256SUM"):
                raise VerificationError(f"{name} is missing from the ISO's offline repository database")
            filename = entry["FILENAME"]
            if Path(filename).name != filename:
                raise VerificationError(f"Unsafe package filename in offline database: {filename}")
            actual = stream_hash(["unsquashfs", "-cat", str(image),
                                  f"{REPO_PACKAGE_DIR}/{filename}"], None, "sha256")
            if actual != entry["SHA256SUM"]:
                raise VerificationError(f"{name} archive in ISO does not match the offline repository database")
            checked.append({"name": name, "archive": filename, "sha256": actual})

    report = {"iso": iso.name, "airootfs_sha512": actual_digest, "packages": checked}
    report_path = iso.with_name(iso.name + ".verification.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(checked)} selected package archive(s) in {iso.name}", flush=True)
    return report


if __name__ == "__main__":
    try:
        verify(Path(sys.argv[1]), Path(sys.argv[2]))
    except (VerificationError, OSError, ValueError, tarfile.TarError) as exc:
        print(f"ISO verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
