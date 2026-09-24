# Build & Release — Windows application via GitHub Actions

## One-time setup

1. Create a GitHub repository and push this folder to it (branch `main`).
2. Nothing else: the workflow in `.github/workflows/windows-build.yml` runs on
   GitHub's own Windows machines. No secrets are required.

## What happens on every push

| Job | Runs on | Does |
|---|---|---|
| Release safety audit | Linux | no PII / DB / keys / bytecode; version consistent; everything compiles |
| Tests (Linux) | Linux | full suite incl. real-Chromium E2E |
| Tests (Windows) | Windows | full suite **on Windows**, plus a real NTFS ACL check on `backup.key` / `secret.key` |
| Build | Windows | PyInstaller → smoke-test the packaged app → Inno Setup installer → portable zip + SHA256SUMS |

The build only runs if **both** test jobs pass.

Download the result: repository → **Actions** → the run → **Artifacts** →
`HR-Enterprise-<version>`.

## Publishing a release

```
# 1. bump the version in BOTH places
#    VERSION.txt              -> 17.0.1
#    server.py  APP_VERSION   -> '17.0.1'
# 2. commit, then tag
git tag v17.0.1
git push origin v17.0.1
```

The workflow refuses to publish if the tag and `VERSION.txt` disagree. A
successful tagged run creates a GitHub Release containing:

- `HR-Enterprise-Setup-17.0.1.exe` — installer
- `HR-Enterprise-Portable-17.0.1.zip` — unzip-and-run
- `SHA256SUMS.txt`

## Building locally instead

On a Windows PC with Python 3.12:

```
BUILD_WINDOWS.bat               (tests, then build)
BUILD_WINDOWS.bat --skip-tests  (build only)
```

Install [Inno Setup 6](https://jrsoftware.org/isinfo.php) to also get the
installer; without it you get the portable build in `dist\HR Enterprise\`.

## Installed application

| | |
|---|---|
| Program files | `C:\Program Files\HR Enterprise\` |
| Data (DB, keys, backups, logs) | `C:\ProgramData\HR Enterprise\Data\` — **never removed** by uninstall or upgrade |
| First login | `admin` / `Admin@12345`, forced change on first login |
| Network mode | opt-in checkbox in the installer; adds firewall rules on the Private profile only |

## Why onedir, not a single EXE

A single-file EXE unpacks itself into `%TEMP%` on every launch; with hospital
antivirus that is several seconds before the app even opens. The onedir build
starts immediately.

## Known first-run caveats

- The Inno Setup script and the Windows jobs are linted (actionlint: clean) and
  mirror a build verified on Linux, but their **first real execution is your
  first push**. If a Windows-only step fails, the job log shows exactly which.
- The EXE is not code-signed, so Windows SmartScreen will warn on first launch
  ("More info" → "Run anyway"). Signing needs a purchased certificate.
