# OpenTalking Desktop

Electron desktop client for OpenTalking. The desktop app keeps Mock and Remote API modes available, keeps the existing WebUI entry compatible through the local proxy, and adds the P1 model package flow for ordinary users.

## P1 Scope

- Packaging uses `electron-builder` with the existing Vite builds for main, preload, and renderer.
- macOS outputs `dmg` and `zip`; Windows outputs `nsis` and `zip`.
- The main installer does not bundle Python, model weights, OmniRT, or QuickTalk weights.
- Common `ffmpeg` and `ffprobe` CLI binaries are loaded from `resources/extra/<platform>-<arch>/` when present.
- Model startup packages use `.otpkg` zip files with an `opentalking.package.json` manifest.
- First complete package target: `opentalking-quicktalk-local` for Windows WSL2 and Linux CUDA.
- macOS can import QuickTalk packages for compatibility checks, but QuickTalk local runtime is marked unsupported in P1.

## Install

```bash
cd apps/desktop
npm install
```

If Electron binary download is slow or blocked, use a mirror:

```bash
ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ npm install
```

## Run

```bash
cd apps/desktop
npm run dev
```

Dev mode builds the desktop app and starts Electron. To point the renderer at a separate Vite dev server, set:

```bash
OPENTALKING_DESKTOP_DEV_SERVER_URL=http://127.0.0.1:5185 npm run dev
```

## Backend Modes

- `managed-mock`: starts `scripts/quickstart/start_opentalking.sh --mock --api-port <port>`.
- `managed-local`: starts the local OpenTalking backend from the source checkout.
- `managed-package`: starts an installed `.otpkg` package through the package manifest.
- `remote`: connects to an existing API base URL and checks `/models`.

Default API port is `8010`. If it is busy, the controller scans `8011-8099`.

## Windows WSL2

Windows local QuickTalk is expected to run inside WSL2. The Electron app remains a native Windows app and calls:

```powershell
wsl.exe -d <distro> -- bash -lc "<package>/scripts/start.sh"
```

Readiness checks `http://127.0.0.1:<port>/models` first. If localhost forwarding fails, the app tries the WSL IP from `hostname -I` and returns a repair hint.

## Model Packages

An `.otpkg` is a zip archive with `opentalking.package.json` at the archive root. The required manifest fields are:

```json
{
  "schemaVersion": 1,
  "id": "opentalking-quicktalk-local",
  "title": "QuickTalk local package",
  "version": "1.0.0",
  "model": "quicktalk",
  "backend": "local",
  "platforms": [],
  "entry": {
    "start": "scripts/start.sh",
    "stop": "scripts/stop.sh"
  },
  "health": {
    "expectModel": "quicktalk"
  },
  "env": {},
  "resources": {
    "requiredFiles": []
  }
}
```

The QuickTalk package template lives in:

```text
apps/desktop/package-templates/quicktalk/
```

The template expects QuickTalk weights, HuBERT, InsightFace `buffalo_l`, scripts, and any offline runtime bootstrap to be placed inside the package before zipping.

## Extra Binaries

Prepare `ffmpeg` and `ffprobe` resources from the AIGCPanel-style shared binary repository:

```bash
cd apps/desktop
npm run prepare:binaries
```

Packaging scripts call this automatically. Manual preparation is useful when checking the resources before packaging. Expected output layout:

```text
resources/extra/mac-arm64/ffmpeg
resources/extra/mac-arm64/ffprobe
resources/extra/mac-x64/ffmpeg
resources/extra/mac-x64/ffprobe
resources/extra/win-x64/ffmpeg.exe
resources/extra/win-x64/ffprobe.exe
```

At runtime the app injects `OPENTALKING_FFMPEG_BIN` and prepends the binary directory to `PATH` when a binary is present.

## Build

```bash
npm run typecheck
npm run build
```

## Package

```bash
npm run package:mac
npm run make:mac
npm run make:mac:signed
npm run package:win
npm run make:win
```

Artifacts are written to `dist-release/`.

## macOS Signing And Notarization

`make:mac` and `package:mac` disable automatic certificate discovery and produce local development artifacts. For a distributable build that opens cleanly on another Mac, use `make:mac:signed` with a Developer ID Application certificate and Apple notarization credentials.

Enable notarization with:

```bash
OPENTALKING_MAC_NOTARIZE=1 npm run make:mac:signed
```

The notarization script supports one of these credential strategies.

Keychain profile:

```bash
xcrun notarytool store-credentials opentalking-notary
export APPLE_KEYCHAIN_PROFILE=opentalking-notary
```

App Store Connect API key:

```bash
export APPLE_API_KEY=/absolute/path/AuthKey_ABC123DEFG.p8
export APPLE_API_KEY_ID=ABC123DEFG
export APPLE_API_ISSUER=00000000-0000-0000-0000-000000000000
```

Apple ID app-specific password:

```bash
export APPLE_ID=developer@example.com
export APPLE_APP_SPECIFIC_PASSWORD=xxxx-xxxx-xxxx-xxxx
export APPLE_TEAM_ID=TEAMID
```

To force a specific signing identity in CI, use the standard `electron-builder` code signing variables such as `CSC_NAME`, `CSC_LINK`, `CSC_KEY_PASSWORD`, and `CSC_KEYCHAIN`.
