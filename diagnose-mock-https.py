"""Diagnose the HTTPS certificate used by the dedicated offline mock proxy.

This never fetches from the internet and never bypasses TLS verification.
It checks the project-specific mitmproxy CA and the TLS handshake over the
local loopback proxy, matching the hostname used in the Chrome address bar.
"""
import hashlib
from pathlib import Path
import socket
import ssl
import sys

HOST = "inbox.cedarpostmail.net"
PORT = 8080
ROOT = Path(__file__).resolve().parent
CERT = ROOT / "mitm-ca" / "mitmproxy-ca-cert.cer"


def print_cert_trust():
    if not CERT.is_file():
        print("CA file not found:", CERT)
        print("Start start-proxy-windows.bat first so mitmproxy generates its CA.")
        return False
    raw = CERT.read_bytes()
    print("Expected CA file:", CERT)
    print("Expected CA SHA256:", hashlib.sha256(raw).hexdigest().upper())
    if sys.platform != "win32":
        print("Windows trust-store check is only available on Windows.")
        return None
    trusted = False
    try:
        for cert, _encoding, trust in ssl.enum_certificates("ROOT"):
            if hashlib.sha256(cert).digest() == hashlib.sha256(raw).digest():
                trusted = True
                break
    except (OSError, AttributeError) as exc:
        print("Unable to inspect Windows trusted roots:", exc)
        return None
    print("Project CA in Windows trusted root store:", "YES" if trusted else "NO")
    if not trusted:
        print("Install THIS project's mitm-ca/mitmproxy-ca-cert.cer in")
        print("Current User > Trusted Root Certification Authorities.")
        print("If you installed a cert from %USERPROFILE%\\.mitmproxy,")
        print("it may be a different CA from the one this project uses.")
    return trusted


def verify_local_proxy():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=5) as connection:
            connection.settimeout(5)
            command = (
                f"CONNECT {HOST}:443 HTTP/1.1\r\n"
                f"Host: {HOST}:443\r\n"
                "Proxy-Connection: close\r\n\r\n"
            )
            connection.sendall(command.encode("ascii"))
            header = b""
            while not header.endswith(b"\r\n\r\n") and len(header) < 8192:
                chunk = connection.recv(1)
                if not chunk:
                    break
                header += chunk
            first_line = header.split(b"\r\n", 1)[0].decode("ascii", "replace")
            print("Local proxy CONNECT:", first_line)
            if " 200 " not in first_line:
                print("The proxy did not establish a CONNECT tunnel.")
                return False
            context = ssl.create_default_context()
            with context.wrap_socket(connection, server_hostname=HOST) as tls:
                cert = tls.getpeercert()
                print("Verified TLS hostname:", HOST)
                print("Certificate issuer:", cert.get("issuer"))
                print("Subject alternative names:", cert.get("subjectAltName"))
                print("Certificate not after:", cert.get("notAfter"))
                print("TLS chain and hostname verification: SUCCESS")
                return True
    except ssl.SSLCertVerificationError as exc:
        print("TLS certificate verification FAILED:", exc)
        print("Check the CA root, issuer, expiration, and hostname mismatch.")
        return False
    except (socket.timeout, OSError, ssl.SSLError) as exc:
        print("Could not complete verified HTTPS over the localhost proxy:", exc)
        print("Is the mock proxy running and is port 8080 listening?")
        return False


def main():
    print("=== Dedicated Chrome / HTTPS trust diagnostic ===")
    print("This checks HTTPS using Windows trust, without skipping verification.")
    print("Use the exact browser address https://" + HOST + "/")
    print("http:// addresses are ALWAYS treated as insecure by Chrome.")
    print()
    trusted = print_cert_trust()
    print()
    verified = verify_local_proxy()
    print()
    if verified and trusted is not False:
        print("Verified HTTPS works from this Python environment.")
        print("If Chrome still warns, check its Security panel for the precise")
        print("reason and confirm the dedicated Chrome profile is in use.")
        return 0
    print("If the trust state changed, fully close the dedicated Chrome profile")
    print("and restart it before checking https://" + HOST + "/ again.")
    print("Do not bypass certificate errors or disable Chrome TLS checks.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
