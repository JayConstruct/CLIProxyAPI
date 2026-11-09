# Fork installer

`cliproxyapi-installer` installs or upgrades releases from
`JayConstruct/CLIProxyAPI` into `~/cliproxyapi`. It preserves the existing
installation layout, `config.yaml`, authentication files, and systemd user service.
The script is adapted from `router-for-me/cliproxyapi-installer` at commit
`69e14232cc73ebc24d1f624aa7d2cbdee76315d3`.

The fork publishes Linux amd64 archives for GLIBC 2.17 or newer by default.
Other architectures and no-plugin variants require separately published assets.
Dependencies are Bash, tar, curl or wget, and sha256sum or shasum. The wget fallback
requires support for `--retry-on-http-error`.

## Install or upgrade

From a checkout:

```bash
bash scripts/cliproxyapi-installer upgrade
```

After the script has been pushed to `main`, download it directly from this fork:

```bash
cpa_installer=$(mktemp) &&
  curl -fsSL --retry 5 --retry-delay 2 \
    https://raw.githubusercontent.com/JayConstruct/CLIProxyAPI/refs/heads/main/scripts/cliproxyapi-installer \
    -o "$cpa_installer" &&
  bash "$cpa_installer" upgrade
rm -f -- "$cpa_installer"
```

`install` and `upgrade` both install the latest release when no installation exists.
Use `status` to inspect the installed version and `--help` for other commands.

Downloads reject HTTP errors, retry temporary failures, and reject empty files.
The installer downloads `checksums.txt` from the same release, verifies the exact
archive's SHA-256 checksum, and checks its tar.gz contents before stopping the
existing service. A download or validation failure leaves the running installation
untouched. Temporary cleanup removes only the directory created by this installer.

## Validation

```bash
bash -n scripts/cliproxyapi-installer
python3 scripts/test_installer.py
```

The regression tests use a local HTTP server and an isolated installation directory.
Service and process operations are stubbed; the tests do not update a real installation.
