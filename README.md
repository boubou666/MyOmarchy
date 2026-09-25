# MyOmarchy

MyOmarchy is a local web page for building an Omarchy installer ISO with extra pacman packages. It puts those packages and their dependencies in the ISO's offline mirror, so the **destination computer can install without internet**. The computer that builds the ISO needs internet.

This is an experimental project. It has not yet completed a full ISO build and offline installation test. Verify a generated ISO in a VM before using it on a machine you care about.

## Requirements

- Windows, macOS, or Linux host with Python 3.10 or newer, Git, Docker running **Linux containers**, internet during the build, and enough free disk space for the ISO and package mirror.
- Docker Desktop on Windows or macOS. Linux may use Docker Desktop or Docker Engine.
- An x86_64 destination computer. On Apple Silicon hosts, the builder uses `linux/amd64` emulation, which can be slow and remains untested.

The build container uses privileged mode because Omarchy's official builder runs `mkarchiso`. Docker must support this mode. The page can start an installed Docker Desktop through `docker desktop start`; on Linux with Docker Engine alone, start the engine through your system's service manager.

## Use the web page

1. Clone this repository and start the local server:

   ```bash
   git clone https://github.com/boubou666/MyOmarchy.git
   cd MyOmarchy
   python3 web.py
   ```

   On Windows, `python web.py` may be the right command. The default address is <http://127.0.0.1:8765/>. The server binds only to `127.0.0.1`.

2. Pick **Current Stable**, **Current Release Candidate**, **Current Development**, or a pinned numbered release. Search packages with autocomplete and save your choices. The catalog comes from the selected channel's real pacman databases and is cached for 24 hours.
3. Start Docker Desktop from the page if needed, then click **Build custom ISO**. Watch the Activity panel. The ISO and `.sha256` file appear in `.build/omarchy-iso/release/`.
4. Write the ISO to a USB drive. On Linux, the page can list a removable USB disk, write it, and verify the result after you type the exact `ERASE /dev/...` confirmation. On Windows or macOS, use an ISO writer such as [balenaEtcher](https://etcher.balena.io/) with the generated ISO.
5. Boot the destination computer from the USB and use Omarchy's installer. No network connection should be needed during that installation.

The page stays within one browser viewport. Its package panel and Activity panel scroll internally when necessary.

## Version choices

The channel choices follow Omarchy's current **Stable**, **RC**, and **Development** package repositories, so their contents can change. The pinned **4.0.4** and **4.0.3** choices check out the corresponding Omarchy source tag and the official package recipes that pin `omarchy` and `omarchy-settings` to that source commit. Those two packages are built into the ISO's offline mirror.

For a pinned release, other Arch and Omarchy packages still come from the **current Stable** repository. Thus the Omarchy runtime version is pinned, but the result is not a complete historical snapshot of all dependencies or an unmodified official ISO. Older versions will only be added after checking their recipes and installer compatibility.

## Command line

The web page writes your selection to the ignored local `packages.txt`. For command line use, create that file yourself:

```bash
cp packages.example.txt packages.txt
python3 myomarchy.py plan
python3 myomarchy.py build --target v4.0.3
```

On Windows, use `copy packages.example.txt packages.txt` and `python` if appropriate. Available build targets: `stable`, `rc`, `edge`, `v4.0.4`, `v4.0.3`. The default is `stable`.

On Linux, the USB writer can also be used directly:

```bash
python3 myomarchy.py flash --iso .build/omarchy-iso/release/YOUR-ISO.iso --device /dev/sdX
```

The tool can copy a locally available Omarchy ISO builder checkout rather than cloning it:

```bash
python3 myomarchy.py prepare --source /path/to/omarchy-iso
```

The source checkout is copied into `.build/omarchy-iso`; it is not edited. Without `--source`, the tool clones the official `quattro` branch. `.build/manifest.json` records the builder revision, selected target, source revisions, and packages. The build writes the ISO and its SHA256 sidecar to `.build/omarchy-iso/release/`.

## How it works and limits

The tool patches a private copy of [Omarchy's ISO builder](https://github.com/omacom/omarchy-iso) to append selected packages to the target install list and resolve them into the offline mirror. Omarchy's installer [reads that shipped list](https://github.com/omacom/omarchy-iso/blob/quattro/configs/airootfs/usr/share/omarchy-iso/orchestrator/phases_impl.py). The integration stops if the upstream build steps change in ways it does not recognize.

Scope: x86_64, pacman packages in the chosen channel, and one package selection per ISO. AUR packages, Flatpaks, downloads an application may perform on first launch, and unattended disk configuration are not bundled. Docker Desktop does not automatically expose a host USB disk to the build container.

The builder verifies that target packages resolve from the ISO's offline mirror. For a fuller check, boot the ISO in a VM with networking disabled and complete an installation. This remains to be done for this project.

## Changelog and releases

Changes are recorded in [CHANGELOG.md](CHANGELOG.md). Before each release, move relevant entries from **Unreleased** into a dated version section and create a matching annotated `vX.Y.Z` Git tag. Tags identify releases of **MyOmarchy**; the Omarchy versions in the selector are upstream versions.
