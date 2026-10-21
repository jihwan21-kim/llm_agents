"""Offline assertions for HTTPS trust tools, without installing a root CA."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HTTPSDiagnosticTests(unittest.TestCase):
    def test_check_uses_project_ca_and_verified_host(self):
        source = (ROOT / "diagnose-mock-https.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('HOST = "inbox.cedarpostmail.net"', source)
        self.assertIn('ROOT / "mitm-ca" / "mitmproxy-ca-cert.cer"', source)
        self.assertIn('ssl.enum_certificates("ROOT")', source)
        self.assertIn("ssl.create_default_context()", source)
        self.assertIn('server_hostname=HOST', source)
        self.assertNotIn("_create_unverified_context", source)
        self.assertNotIn("CERT_NONE", source)
        self.assertNotIn("ignore_https_errors", source)

    def test_install_requires_explicit_confirmation_for_current_user(self):
        script = (ROOT / "trust-project-ca-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("Read-Host", script)
        self.assertIn("-cne 'TRUST'", script)
        self.assertIn("Cert:\\CurrentUser\\Root", script)
        self.assertIn("Import-Certificate", script)
        self.assertNotIn("Cert:\\LocalMachine\\Root", script)
        self.assertTrue((ROOT / "trust-project-ca-windows.bat").exists())
        self.assertTrue((ROOT / "check-mock-https-windows.bat").exists())


if __name__ == "__main__":
    unittest.main()
