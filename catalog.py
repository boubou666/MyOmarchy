"""Searchable package catalog from Omarchy's pacman repository channels."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile
import threading
import time
from urllib.request import Request, urlopen


MIRRORS = {"stable": "stable-mirror.omarchy.org", "rc": "rc-mirror.omarchy.org",
           "edge": "mirror.omarchy.org"}


def repositories(channel: str) -> dict[str, str]:
    mirror = MIRRORS[channel]
    return {**{repo: f"https://{mirror}/{repo}/os/x86_64/{repo}.db"
               for repo in ("core", "extra", "multilib")},
            "omarchy": f"https://pkgs.omarchy.org/{channel}/x86_64/omarchy.db"}
MAX_DATABASE_BYTES = 30 * 1024 * 1024
CACHE_AGE_SECONDS = 24 * 60 * 60


def fields_from_desc(content: str) -> dict[str, str]:
    lines = content.splitlines()
    fields = {}
    for index, line in enumerate(lines[:-1]):
        if line.startswith("%") and line.endswith("%") and lines[index + 1]:
            fields[line.strip("%")] = lines[index + 1]
    return fields


def parse_database(data: bytes, repo: str) -> list[dict]:
    packages = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for item in archive:
            if not item.isfile() or not item.name.endswith("/desc"):
                continue
            stream = archive.extractfile(item)
            if stream is None:
                continue
            fields = fields_from_desc(stream.read().decode("utf-8", errors="replace"))
            name = fields.get("NAME", "")
            if name:
                packages.append({"name": name, "version": fields.get("VERSION", ""),
                                 "description": fields.get("DESC", ""), "repo": repo})
    return packages


def fetch_database(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "MyOmarchy/0.1"})
    with urlopen(request, timeout=30) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_DATABASE_BYTES:
            raise ValueError(f"Repository database is unexpectedly large: {url}")
        data = response.read(MAX_DATABASE_BYTES + 1)
    if len(data) > MAX_DATABASE_BYTES:
        raise ValueError(f"Repository database is unexpectedly large: {url}")
    return data


class Catalog:
    def __init__(self, cache_path: Path, channel: str = "stable") -> None:
        self.cache_path = cache_path
        self.channel = channel
        self.sources = repositories(channel)
        self.lock = threading.Lock()
        self.packages: list[dict] = []
        self.names: set[str] = set()
        self.updated_at = 0.0
        self.refreshing = False
        self.error = ""
        self.load_cache()

    def load_cache(self) -> None:
        try:
            cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if cached.get("sources") != self.sources:
                return
            packages = cached["packages"]
            if not isinstance(packages, list):
                return
            self.packages = packages
            self.names = {item["name"] for item in packages}
            self.updated_at = float(cached["updated_at"])
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def start_refresh(self, force: bool = False) -> bool:
        with self.lock:
            if self.refreshing or (not force and self.packages and time.time() - self.updated_at < CACHE_AGE_SECONDS):
                return False
            self.refreshing = True
            self.error = ""
        threading.Thread(target=self._refresh, daemon=True).start()
        return True

    def _refresh(self) -> None:
        try:
            packages = []
            for repo, url in self.sources.items():
                packages.extend(parse_database(fetch_database(url), repo))
            if not packages:
                raise ValueError("Repository databases contained no packages")
            packages.sort(key=lambda item: (item["name"].casefold(), item["repo"]))
            payload = {"sources": self.sources, "updated_at": time.time(), "packages": packages}
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            temporary.replace(self.cache_path)
            with self.lock:
                self.packages = packages
                self.names = {item["name"] for item in packages}
                self.updated_at = payload["updated_at"]
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
        finally:
            with self.lock:
                self.refreshing = False

    def status(self) -> dict:
        with self.lock:
            runtime = next((item["version"] for item in self.packages
                            if item["name"] == ("omarchy-dev" if self.channel == "edge" else "omarchy")), "")
            return {"count": len(self.packages), "updated_at": self.updated_at,
                    "refreshing": self.refreshing, "error": self.error,
                    "omarchy_version": runtime}

    def contains(self, name: str) -> bool:
        with self.lock:
            return name in self.names

    def search(self, query: str, limit: int = 30) -> list[dict]:
        query = query.strip().casefold()[:100]
        with self.lock:
            packages = self.packages
            if not query:
                return packages[:limit]
            matches = [item for item in packages if query in item["name"].casefold() or
                       query in item["description"].casefold()]
        matches.sort(key=lambda item: (
            0 if item["name"].casefold() == query else
            1 if item["name"].casefold().startswith(query) else
            2 if query in item["name"].casefold() else 3,
            item["name"].casefold(), item["repo"]
        ))
        return matches[:limit]
