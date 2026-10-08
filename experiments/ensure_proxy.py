"""Reuse a verified local mock proxy, or start the project's proxy if absent."""
from __future__ import annotations
import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


class ProxySetupError(RuntimeError):
    pass


def probe(timeout=2):
    """False only when no listener accepts connections; never replace another service."""
    connection = http.client.HTTPConnection('127.0.0.1', 8080, timeout=timeout)
    try:
        connection.request('GET', 'http://mock.test/__mock/sites', headers={'Host': 'mock.test'})
        response = connection.getresponse()
        body = response.read(65537)
        if response.status != 200 or response.getheader('X-Mock-Proxy') != 'local-only':
            raise ProxySetupError('Port 8080 is occupied by a service that is not the expected mock proxy. Stop or reconfigure that service first.')
        try:
            sites = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise ProxySetupError('The proxy site registry response is invalid.') from exc
        if not isinstance(sites, list) or not sites or any(not isinstance(s, dict) or not s.get('id') or not s.get('host') for s in sites):
            raise ProxySetupError('The proxy did not return a valid site registry.')
        return True
    except ConnectionRefusedError:
        return False
    except (socket.timeout, http.client.HTTPException) as exc:
        raise ProxySetupError('Port 8080 is not responding as a mock proxy. Check the existing proxy window; no second proxy was started.') from exc
    finally:
        connection.close()


def start_proxy(root=ROOT):
    windows = os.name == 'nt'
    executable = root / '.venv' / ('Scripts/python.exe' if windows else 'bin/python')
    if not executable.is_file():
        raise ProxySetupError('Proxy environment is missing. Run setup-windows.bat first (separate from setup-agent-windows.bat), then retry.')
    if not (root / 'run_proxy.py').is_file():
        raise ProxySetupError('run_proxy.py is missing. Extract or pull the complete repository before retrying.')
    if windows:
        # Fixed relative script name avoids quoting the repository path through cmd.exe.
        return subprocess.Popen(['cmd.exe', '/c', 'start-proxy-windows.bat'], cwd=root,
                                creationflags=subprocess.CREATE_NEW_CONSOLE)
    logdir = root / 'logs'
    logdir.mkdir(exist_ok=True)
    with (logdir / 'proxy-startup.log').open('ab') as log:
        return subprocess.Popen([str(executable), 'run_proxy.py'], cwd=root,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True)


def ensure_proxy(timeout=20, root=ROOT):
    if probe():
        print('Mock proxy is already running at 127.0.0.1:8080.', flush=True)
        return False
    print('Mock proxy is not running. Starting it now...', flush=True)
    process = start_proxy(root)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe():
            print('Mock proxy is ready. Keep its window open while testing.', flush=True)
            return True
        if process.poll() is not None:
            raise ProxySetupError('The proxy exited before becoming ready. Run start-proxy-windows.bat directly and inspect its error message. If dependencies are missing, rerun setup-windows.bat.')
        time.sleep(0.25)
    raise ProxySetupError('The proxy did not become ready within the startup timeout. Check the new proxy window (or logs/proxy-startup.log on macOS/Linux). No browser or GPT run was started.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=20)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    try:
        ensure_proxy(args.timeout)
    except (ProxySetupError, OSError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
