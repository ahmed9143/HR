# HR Enterprise v18 — Offline Deployment

## End-user requirement
The hospital PC does **not** need Python, pip, Node.js, Git, or Internet access to run the released Windows build.

GitHub Actions installs build/test dependencies on the CI runner, then PyInstaller packages the Python runtime and application dependencies into `dist/HR Enterprise`. The installer/portable ZIP is the only artifact copied to the hospital PCs.

## Recommended LAN deployment

```text
                 Windows Server / HR Server
                 HR Enterprise + PostgreSQL*
                          |
          +---------------+---------------+
          |               |               |
        PC-01           PC-02           PC-03
       Browser          Browser         Browser
```

`* PostgreSQL remains a separate production-validation track until the CI job proves the complete application against PostgreSQL.`

## Single-PC deployment
Use the Windows installer. Data is stored under:

`C:\ProgramData\HR Enterprise\Data`

The application EXE is not the database. Upgrading the application does not replace the data directory.

## First login

- Username: `admin`
- Default password: `Admin@12345`
- No random password is generated.
- A new installation may require the first-run password change for security. Existing installations keep their current password.
- If the admin password is lost, sign in with another SuperAdmin and use **Admin Password Recovery**, or use the documented recovery procedure for the server.

## Building

1. Push the repository to GitHub.
2. Open **Actions**.
3. Run **HR Enterprise — Test, Build, Release**.
4. For a release, create a tag matching `VERSION.txt`, e.g. `v18.0.0`.
5. Download the generated installer or portable ZIP from the workflow artifact/release.

CI verifies that the end-user bundle does not contain `python.exe`, `pip.exe`, `node.exe`, runtime databases, or generated secret keys.

## Backups
Back up the encrypted HR backup files and keep the backup/secret recovery material in a separate offline protected location. Never commit keys, databases, `.env` files, or employee data to Git.
