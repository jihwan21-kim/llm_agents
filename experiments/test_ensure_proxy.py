from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import ensure_proxy as ep


class ProxyStartupTests(unittest.TestCase):
    def test_reuses_ready_proxy_without_starting_process(self):
        with patch.object(ep, 'probe', return_value=True), patch.object(ep, 'start_proxy') as start:
            self.assertFalse(ep.ensure_proxy())
            start.assert_not_called()

    def test_starts_absent_proxy_once_and_waits_until_ready(self):
        with patch.object(ep, 'probe', side_effect=[False, False, True]), \
             patch.object(ep, 'start_proxy', return_value=SimpleNamespace(poll=lambda:None)) as start, \
             patch.object(ep.time, 'sleep'):
            self.assertTrue(ep.ensure_proxy())
            start.assert_called_once()

    def test_wrong_service_is_not_replaced(self):
        response=SimpleNamespace(status=200, read=lambda n:b'{}', getheader=lambda name:None)
        connection=SimpleNamespace(request=lambda *a,**kw:None, getresponse=lambda:response, close=lambda:None)
        with patch.object(ep.http.client, 'HTTPConnection', return_value=connection), \
             patch.object(ep, 'start_proxy') as start:
            with self.assertRaisesRegex(ep.ProxySetupError, 'not the expected mock proxy'):
                ep.ensure_proxy()
            start.assert_not_called()

    def test_exited_proxy_has_actionable_error(self):
        with patch.object(ep, 'probe', return_value=False), \
             patch.object(ep, 'start_proxy', return_value=SimpleNamespace(poll=lambda:1)):
            with self.assertRaisesRegex(ep.ProxySetupError, 'start-proxy-windows.bat'):
                ep.ensure_proxy()

    def test_missing_environment_does_not_launch(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ep.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(ep.ProxySetupError, 'setup-windows.bat'):
                ep.start_proxy(Path(tmp))
            start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
