# Changelog

All notable changes to MyOmarchy are recorded here. This file follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, and MyOmarchy releases use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## 0.1.1 - 2026-09-25

### Added

- Finished ISO verification of selected install-list entries, offline package archives, repository checksums, and the live filesystem checksum.
- Per-ISO verification reports; the page lists only completed verified builds and checks the ISO checksum before Linux USB writing.
- Compatibility mapping for the T2 repository's replacement of `apple-bcm-firmware` with `apple-bcm-firmware-fetcher`, with an explicit T2 limitation.
- Successful Stable ISO build with `firefox` and `emacs-nox`, with both package archives checked in the finished image.

### Changed

- Documented how the local repository supplies packages that Omarchy installs into the destination system.

### Known limitations

- A complete network-disabled installation has not yet been tested in a VM.
- T2 Mac firmware setup and installation have not been verified offline.

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
