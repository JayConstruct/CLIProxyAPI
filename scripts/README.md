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

## Switch between official and fork releases

Use the same installer and installation directory for both sources:

```bash
# Install or switch to the latest official release.
bash scripts/cliproxyapi-installer upgrade --source official

# Install or switch back to the latest JayConstruct release (the default).
bash scripts/cliproxyapi-installer upgrade --source fork
```

For a downloaded script, append `--source official` or `--source fork` to the
`bash "$cpa_installer" upgrade` command above. The selection applies to that
invocation; omitting `--source` always selects the fork.

The official installer and this script share `~/cliproxyapi`, `version.txt`,
`asset-variant.txt`, `config.yaml`, the executable name, and the systemd user service
name `cliproxyapi.service`. Existing official installations, including older ones
without asset metadata, can be adopted without reinstalling configuration or
credentials. You can also run the official installer against an installation
updated by this script. Run only one installer at a time.
Keep the fork's `-jay.<n>` release suffix: the unmodified official installer uses
the version and asset variant to decide whether an installation is up to date.

An additional `release-source.txt` file records the source, version, variant, and
installed binary checksum. It does not change the official version files. If the
official installer replaces the binary and leaves this record behind, its checksum
no longer matches; this script then verifies and installs the selected release
instead of incorrectly reporting that it is already up to date. Unknown legacy
installations are reinstalled once to establish their source.

Switching sources can install an older release when that source's latest version
is older. Configuration and credentials are preserved, but that alone does not
guarantee runtime compatibility across major versions or with options added in a
newer release. Keep a backup when downgrading. Go shared-library plugins also need
to match the selected server build; see [Go's plugin compatibility notes](https://pkg.go.dev/plugin).

This is one installation with one active server. Running both servers concurrently
requires separate installation directories, service names, and listening ports.

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
