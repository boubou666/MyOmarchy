#!/usr/bin/env python3
"""Local web interface for MyOmarchy. Binds only to loopback."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.parse import parse_qs, urlsplit

import catalog
import myomarchy
import versions


ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
HTML = (ROOT / "web/index.html").read_text(encoding="utf-8")


class Job:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.name = ""
        self.running = False
        self.exit_code: int | None = None
        self.logs: list[str] = []

    def snapshot(self) -> dict:
        with self.lock:
            return {"name": self.name, "running": self.running,
                    "exit_code": self.exit_code, "logs": self.logs[-400:]}

    def start(self, name: str, command: list[str]) -> None:
        with self.lock:
            if self.running:
                raise myomarchy.ToolError("A job is already running")
            self.name = name
            self.running = True
            self.exit_code = None
            self.logs = []

        def worker() -> None:
            code = 1
            try:
                process = subprocess.Popen(
                    command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, encoding="utf-8", errors="replace"
                )
                assert process.stdout is not None
                for line in process.stdout:
                    with self.lock:
                        self.logs.append(line.rstrip("\n"))
                        self.logs = self.logs[-400:]
                code = process.wait()
            except Exception as exc:
                with self.lock:
                    self.logs.append(f"Error: {exc}")
            finally:
                with self.lock:
                    self.exit_code = code
                    self.running = False

        threading.Thread(target=worker, daemon=True).start()


JOB = Job()
CATALOGS = {channel: catalog.Catalog(myomarchy.WORK / f"catalog-{channel}.json", channel)
            for channel in catalog.MIRRORS}
# Preserve the first version of the cache created before channel selection.
if not CATALOGS["stable"].packages:
    old_catalog = catalog.Catalog(myomarchy.WORK / "catalog.json")
    CATALOGS["stable"].packages = old_catalog.packages
    CATALOGS["stable"].names = old_catalog.names
    CATALOGS["stable"].updated_at = old_catalog.updated_at
TARGET_FILE = ROOT / "target.txt"


def saved_target() -> versions.Target:
    try:
        return versions.get_target(TARGET_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return versions.TARGETS["stable"]
DOCKER_LOCK = threading.Lock()
DOCKER_SNAPSHOT = {"checked_at": 0.0, "installed": shutil.which("docker") is not None,
                   "desktop_available": False, "ready": False, "mode": ""}


def docker_desktop_available() -> bool:
    if not DOCKER_SNAPSHOT["installed"]:
        return False
    try:
        return subprocess.run(["docker", "desktop", "--help"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def docker_status(force: bool = False) -> dict:
    with DOCKER_LOCK:
        if not force and time.monotonic() - DOCKER_SNAPSHOT["checked_at"] < 5:
            return dict(DOCKER_SNAPSHOT)
        DOCKER_SNAPSHOT["checked_at"] = time.monotonic()
        if DOCKER_SNAPSHOT["installed"]:
            try:
                result = subprocess.run(["docker", "info", "--format", "{{.OSType}}"],
                                        capture_output=True, text=True, timeout=4)
                DOCKER_SNAPSHOT["mode"] = result.stdout.strip() if result.returncode == 0 else ""
                DOCKER_SNAPSHOT["ready"] = DOCKER_SNAPSHOT["mode"] == "linux"
            except (OSError, subprocess.TimeoutExpired):
                DOCKER_SNAPSHOT["mode"] = ""
                DOCKER_SNAPSHOT["ready"] = False
        return dict(DOCKER_SNAPSHOT)


def built_isos() -> list[dict]:
    release = myomarchy.CHECKOUT / "release"
    if not release.is_dir():
        return []
    found = []
    for iso in sorted(release.glob("omarchy-custom-*.iso"),
                      key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            report = myomarchy.verified_release(iso)
        except myomarchy.ToolError:
            continue
        found.append({"name": iso.name, "size": iso.stat().st_size,
                      "packages": [item["name"] for item in report["packages"]]})
    return found


def usb_disks() -> list[dict]:
    if sys.platform != "linux":
        return []
    result = subprocess.run(
        ["lsblk", "--json", "--bytes", "--output", "PATH,TYPE,RM,TRAN,SIZE,MODEL,SERIAL,MOUNTPOINTS"],
        text=True, capture_output=True, check=True
    )
    candidates = []
    for disk in json.loads(result.stdout)["blockdevices"]:
        if disk.get("type") == "disk" and str(disk.get("rm")) in ("1", "True", "true") and disk.get("tran") == "usb":
            candidates.append({"path": disk["path"], "size": disk["size"],
                               "model": disk.get("model") or "", "serial": disk.get("serial") or ""})
    return candidates


class Handler(BaseHTTPRequestHandler):
    server_version = "MyOmarchy/0.1"

    def json_response(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        route = urlsplit(self.path)
        if route.path == "/":
            content = HTML.replace("__TOKEN__", TOKEN).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(content)
        elif route.path == "/api/state":
            try:
                packages = myomarchy.packages_from(ROOT / "packages.txt")
            except myomarchy.ToolError:
                packages = []
            self.json_response(200, {
                "packages": packages, "job": JOB.snapshot(), "isos": built_isos(),
                "usb": usb_disks(), "docker": docker_status(),
                "target": saved_target().key,
                "targets": [{"key": target.key, "label": target.label,
                             "channel": target.channel, "pinned": bool(target.source_commit)}
                            for target in versions.TARGETS.values()],
                "catalogs": {channel: item.status() for channel, item in CATALOGS.items()},
            })
        elif route.path == "/api/catalog":
            try:
                target = versions.get_target(parse_qs(route.query).get("target", ["stable"])[0])
            except ValueError as exc:
                self.json_response(400, {"error": str(exc)})
                return
            selected_catalog = CATALOGS[target.channel]
            selected_catalog.start_refresh()
            query = parse_qs(route.query).get("q", [""])[0]
            self.json_response(200, {"packages": selected_catalog.search(query),
                                     "catalog": selected_catalog.status()})
        else:
            self.json_response(404, {"error": "Not found"})

    def do_POST(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin != f"http://127.0.0.1:{self.server.server_port}" or self.headers.get("X-MyOmarchy-Token") != TOKEN:
            self.json_response(403, {"error": "Invalid local request"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 65536:
                raise myomarchy.ToolError("Request is too large")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise myomarchy.ToolError("Invalid request")
            if self.path == "/api/packages":
                if JOB.snapshot()["running"]:
                    raise myomarchy.ToolError("Cannot change packages during a job")
                value = body.get("packages")
                target = versions.get_target(body.get("target", "stable"))
                selected_catalog = CATALOGS[target.channel]
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise myomarchy.ToolError("Expected a package list")
                content = "\n".join(value) + "\n"
                temporary = ROOT / "packages.txt.tmp"
                temporary.write_text(content, encoding="utf-8")
                try:
                    selected = myomarchy.packages_from(temporary)
                    if selected_catalog.status()["count"]:
                        unknown = [name for name in selected if not selected_catalog.contains(name)]
                        if unknown:
                            raise myomarchy.ToolError(f"Not found in current {target.channel} repositories: {', '.join(unknown)}")
                    temporary.replace(ROOT / "packages.txt")
                    TARGET_FILE.write_text(target.key + "\n", encoding="utf-8")
                finally:
                    temporary.unlink(missing_ok=True)
                self.json_response(200, {"ok": True})
            elif self.path == "/api/build":
                myomarchy.packages_from(ROOT / "packages.txt")
                if not docker_status(force=True)["ready"]:
                    raise myomarchy.ToolError("Docker is not ready with Linux containers")
                target = saved_target()
                JOB.start(f"Building {target.label} ISO", [sys.executable, str(ROOT / "myomarchy.py"),
                                                           "build", "--target", target.key])
                self.json_response(202, {"ok": True})
            elif self.path == "/api/docker/start":
                if not DOCKER_SNAPSHOT["desktop_available"]:
                    raise myomarchy.ToolError("Docker Desktop CLI is unavailable on this computer")
                if docker_status(force=True)["ready"]:
                    self.json_response(200, {"ok": True, "already_running": True})
                else:
                    JOB.start("Starting Docker Desktop", ["docker", "desktop", "start", "--timeout", "180"])
                    self.json_response(202, {"ok": True})
            elif self.path == "/api/catalog/refresh":
                target = versions.get_target(body.get("target", "stable"))
                CATALOGS[target.channel].start_refresh(force=True)
                self.json_response(202, {"ok": True})
            elif self.path == "/api/flash":
                name, device, confirmation = body.get("iso"), body.get("device"), body.get("confirmation")
                if not all(isinstance(v, str) for v in (name, device, confirmation)):
                    raise myomarchy.ToolError("ISO, USB disk, and confirmation are required")
                if Path(name).name != name or name not in [item["name"] for item in built_isos()]:
                    raise myomarchy.ToolError("Choose a built ISO")
                if confirmation != f"ERASE {device}":
                    raise myomarchy.ToolError("Confirmation does not match the USB disk")
                myomarchy.device_info(device)
                iso = myomarchy.CHECKOUT / "release" / name
                JOB.start("Writing USB", [sys.executable, str(ROOT / "myomarchy.py"), "flash",
                                          "--iso", str(iso), "--device", device, "--confirm", confirmation])
                self.json_response(202, {"ok": True})
            else:
                self.json_response(404, {"error": "Not found"})
        except (myomarchy.ToolError, ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            self.json_response(400, {"error": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser automatically")
    args = parser.parse_args()
    DOCKER_SNAPSHOT["desktop_available"] = docker_desktop_available()
    CATALOGS[saved_target().channel].start_refresh()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"MyOmarchy: http://127.0.0.1:{args.port}", flush=True)
    if not args.no_open:
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
