#!/usr/bin/env python3
"""Exercise installer downloads and upgrades without touching real services."""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


INSTALLER = Path(__file__).with_name("cliproxyapi-installer").resolve()
VERSION = "8.0.62-jay.1"
ASSET = f"CLIProxyAPI_{VERSION}_linux_amd64.tar.gz"
BINARY = b"#!/bin/sh\nprintf 'test release\\n'\n"


def make_archive(include_binary=True, binary=BINARY):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        files = {"config.example.yaml": b"api-keys: []\n"}
        if include_binary:
            files["cli-proxy-api"] = binary
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


class InstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routes = {}
        cls.requests = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                cls.requests[self.path] = cls.requests.get(self.path, 0) + 1
                responses = cls.routes.get(self.path, [(404, b"Not Found")])
                index = min(cls.requests[self.path] - 1, len(responses) - 1)
                status, payload = responses[index]
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.routes.clear()
        self.requests.clear()
        temporary = tempfile.TemporaryDirectory(prefix="cpa-installer-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.install = self.root / "installation with spaces"
        self.install.mkdir()
        (self.install / "version.txt").write_text("8.0.61-jay.1\n")
        (self.install / "asset-variant.txt").write_text("default\n")
        (self.install / "config.yaml").write_text("keep: user configuration\n")
        (self.install / "cli-proxy-api").write_bytes(b"old binary\n")
        self.auth = self.install / "auths" / "saved-credential.json"
        self.auth.parent.mkdir()
        self.auth.write_text('{"keep":"saved credential"}\n')
        self.marker = self.root / "service-events"
        self.temporary = self.root / "temporary"
        self.temporary.mkdir()
        self.sentinel = self.temporary / "tmp.unrelated"
        self.sentinel.write_text("keep this file\n")
        self.env = dict(os.environ, TMPDIR=str(self.temporary))
        self.archive = make_archive()
        self.release(self.archive)

    def release(self, payload, checksum=None, version=VERSION):
        asset = f"CLIProxyAPI_{version}_linux_amd64.tar.gz"
        self.asset_path = "/release/" + asset
        metadata = {"tag_name": "v" + version, "assets": [
            {"browser_download_url": self.base + self.asset_path}
        ]}
        self.routes["/latest"] = [(200, json.dumps(metadata).encode())]
        self.routes[self.asset_path] = [(200, payload)]
        checksum = checksum or hashlib.sha256(payload).hexdigest()
        self.routes["/release/checksums.txt"] = [
            (200, f"{checksum}  {asset}\n".encode())
        ]

    def bash(self, code, *args, env=None):
        return subprocess.run(
            ["/bin/bash", "-c", 'source "$1"\nshift\n' + code,
             "installer-test", str(INSTALLER), *map(str, args)],
            env=env or self.env, capture_output=True, text=True, timeout=30,
        )

    def upgrade(self, env=None, source=""):
        return self.bash('''
INSTALL_DIR="$1"
API_URL="$2/latest"
service_events="$3"
trap cleanup EXIT
detect_linux_arch() { echo linux_amd64; }
detect_linux_asset_variant() { echo default; }
is_service_running() { return 0; }
is_cliproxyapi_running() { return 1; }
stop_service() { echo stopped >> "$service_events"; }
stop_cliproxyapi_processes() { echo killed >> "$service_events"; }
restart_service() { echo restarted >> "$service_events"; }
create_systemd_service() { :; }
if [[ -n "$4" ]]; then
    fixture_base="$2"
    fetch_release_info() { curl -fsSL "$fixture_base/latest"; }
    main upgrade --source "$4"
else
    main upgrade
fi
''', self.install, self.base, self.marker, source, env=env)

    def assert_preserved(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.marker.exists(), "service was stopped before validation")
        self.assertEqual((self.install / "version.txt").read_text(), "8.0.61-jay.1\n")
        self.assertEqual((self.install / "cli-proxy-api").read_bytes(), b"old binary\n")
        self.assertEqual((self.install / "config.yaml").read_text(), "keep: user configuration\n")
        self.assertEqual(self.auth.read_text(), '{"keep":"saved credential"}\n')
        self.assertEqual(list(self.temporary.iterdir()), [self.sentinel])

    def test_default_repository(self):
        result = self.bash('printf "%s" "$API_URL"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "https://api.github.com/repos/JayConstruct/CLIProxyAPI/releases/latest")

    def test_upgrade_retries_and_preserves_config(self):
        for path in ("/latest", self.asset_path, "/release/checksums.txt"):
            self.routes[path].insert(0, (503, b"<html>Service Unavailable</html>"))
        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.marker.read_text().splitlines(), ["stopped", "restarted"])
        self.assertEqual((self.install / "version.txt").read_text(), VERSION + "\n")
        self.assertEqual((self.install / "cli-proxy-api").read_bytes(), BINARY)
        self.assertEqual((self.install / "config.yaml").read_text(), "keep: user configuration\n")
        for path in ("/latest", self.asset_path, "/release/checksums.txt"):
            self.assertEqual(self.requests[path], 2)
        self.assertEqual(list(self.temporary.iterdir()), [self.sentinel])

    def test_source_options_select_repository(self):
        for source, owner in (("official", "router-for-me"), ("fork", "JayConstruct")):
            with self.subTest(source=source):
                result = self.bash('''
install_cliproxyapi() { printf '%s' "$API_URL"; }
main upgrade --source "$1"
''', source)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout,
                                 f"https://api.github.com/repos/{owner}/CLIProxyAPI/releases/latest")

    def test_invalid_source_does_not_stop_service(self):
        result = self.upgrade(source="invalid")
        self.assert_preserved(result)
        self.assertIn("Use --source fork or --source official", result.stderr)

    def test_switch_to_official_and_back(self):
        official_binary = b"#!/bin/sh\necho official\n"
        self.release(make_archive(binary=official_binary), version="8.0.62")
        result = self.upgrade(source="official")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.install / "version.txt").read_text(), "8.0.62\n")
        self.assertEqual((self.install / "cli-proxy-api").read_bytes(), official_binary)
        self.assertTrue((self.install / "release-source.txt").read_text().startswith(
            "router-for-me/CLIProxyAPI|8.0.62|default|"))
        # Returning to an older fork release is also an intentional source switch.
        self.release(self.archive, version="8.0.61-jay.1")
        result = self.upgrade(source="fork")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.install / "version.txt").read_text(), "8.0.61-jay.1\n")
        self.assertEqual((self.install / "cli-proxy-api").read_bytes(), BINARY)
        self.assertTrue((self.install / "release-source.txt").read_text().startswith(
            "JayConstruct/CLIProxyAPI|8.0.61-jay.1|default|"))
        self.assertEqual((self.install / "config.yaml").read_text(), "keep: user configuration\n")
        self.assertEqual(self.auth.read_text(), '{"keep":"saved credential"}\n')
        self.assertEqual(self.marker.read_text().splitlines(),
                         ["stopped", "restarted", "stopped", "restarted"])

    def test_legacy_official_install_is_adopted(self):
        (self.install / "version.txt").write_text("8.0.61\n")
        (self.install / "asset-variant.txt").unlink()
        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.install / "version.txt").read_text(), VERSION + "\n")
        self.assertEqual((self.install / "config.yaml").read_text(), "keep: user configuration\n")
        self.assertEqual(self.auth.read_text(), '{"keep":"saved credential"}\n')

    def test_same_version_from_other_source_is_installed(self):
        (self.install / "version.txt").write_text(VERSION + "\n")
        digest = hashlib.sha256(b"old binary\n").hexdigest()
        (self.install / "release-source.txt").write_text(
            f"router-for-me/CLIProxyAPI|{VERSION}|default|{digest}\n")
        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.install / "cli-proxy-api").read_bytes(), BINARY)
        self.assertEqual(self.marker.read_text().splitlines(), ["stopped", "restarted"])

    def test_official_installer_can_replace_tracked_binary(self):
        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # An external installer replaces the binary without updating our source record.
        (self.install / "cli-proxy-api").write_bytes(b"official replacement\n")
        result = self.bash('INSTALL_DIR="$1"\nget_current_source', self.install)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "unknown")
        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.install / "cli-proxy-api").read_bytes(), BINARY)

    def test_current_source_and_binary_skip_reinstall(self):
        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        requests_before = self.requests[self.asset_path]
        events_before = self.marker.read_text()
        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already up to date", result.stdout)
        self.assertEqual(self.requests[self.asset_path], requests_before)
        self.assertEqual(self.marker.read_text(), events_before)

    def test_http_error_does_not_stop_service(self):
        self.routes[self.asset_path] = [(404, b"<html>Not Found</html>")]
        result = self.upgrade()
        self.assert_preserved(result)
        self.assertIn("Failed to download", result.stderr)

    def test_metadata_http_error_does_not_stop_service(self):
        self.routes["/latest"] = [(403, b"Forbidden")]
        result = self.upgrade()
        self.assert_preserved(result)
        self.assertIn("Failed to fetch release information", result.stderr)

    def test_empty_download_does_not_stop_service(self):
        self.routes[self.asset_path] = [(200, b"")]
        result = self.upgrade()
        self.assert_preserved(result)
        self.assertIn("Downloaded file is empty", result.stderr)

    def test_checksum_mismatch_does_not_stop_service(self):
        self.release(self.archive, "0" * 64)
        result = self.upgrade()
        self.assert_preserved(result)
        self.assertIn("SHA-256 checksum mismatch", result.stderr)

    def test_missing_checksum_does_not_stop_service(self):
        self.routes["/release/checksums.txt"] = [(200, b"<html>upstream error</html>")]
        result = self.upgrade()
        self.assert_preserved(result)
        self.assertIn("Missing or invalid SHA-256", result.stderr)

    def test_html_with_matching_checksum_does_not_stop_service(self):
        self.release(b"<html>upstream error</html>")
        result = self.upgrade()
        self.assert_preserved(result)
        self.assertIn("not a valid tar.gz archive", result.stderr)

    def test_missing_binary_does_not_stop_service(self):
        self.release(make_archive(include_binary=False))
        result = self.upgrade()
        self.assert_preserved(result)
        self.assertIn("does not contain cli-proxy-api", result.stderr)

    def test_wget_fallback_retries_http_error(self):
        if not shutil.which("wget"):
            self.skipTest("wget is unavailable")
        tools = self.root / "wget-path"
        tools.mkdir()
        for name in ("wget", "basename", "rm"):
            (tools / name).symlink_to(shutil.which(name))
        path = "/wget-download"
        self.routes[path] = [(503, b"temporary error"), (200, self.archive)]
        output = self.root / "wget.tar.gz"
        result = self.bash('download_file "$1" "$2"', self.base + path, output,
                           env=dict(self.env, PATH=str(tools)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output.read_bytes(), self.archive)
        self.assertEqual(self.requests[path], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
