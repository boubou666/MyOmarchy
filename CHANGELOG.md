# Changelog

All notable changes to MyOmarchy are recorded here. This file follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, and MyOmarchy releases use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## 0.1.0 - 2026-09-25

### Added

- Local single-page interface for selecting Omarchy releases and packages, starting Docker Desktop, building an offline ISO, and writing a USB disk on Linux.
- Searchable catalog sourced from Omarchy's Stable, RC, and Development pacman repositories.
- Pinned Omarchy 4.0.4 and 4.0.3 builds using their matching official package recipes.
- Cross-platform Docker build invocation and an offline package mirror in the resulting ISO.
- Build manifest, ISO checksum, and automated checks for package injection and local API behavior.

### Known limitations

- A complete ISO build and offline installation have not yet been verified in this project.
- USB writing from the page is available on Linux only.
- Pinned Omarchy versions use current Stable repositories for other packages.
