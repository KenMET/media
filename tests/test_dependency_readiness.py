import unittest
from unittest.mock import Mock

from media_mcp.monitor.dependencies import check_downloader
from media_mcp.platform.pairing import pairing_error_message


class DependencyReadinessTests(unittest.TestCase):
    def test_downloader_probe_only_reads_version(self):
        adapter=Mock();adapter.client.app_version.return_value='v5.0.5'
        result=check_downloader(lambda:adapter)
        self.assertEqual(result,{'success':True,'version':'v5.0.5'})
        self.assertEqual(adapter.client.method_calls,[unittest.mock.call.app_version()])
        adapter.prepare.assert_not_called()
        adapter.add.assert_not_called()

    def test_downloader_failures_do_not_echo_credentials_or_response_body(self):
        adapter=Mock()
        adapter.client.app_version.side_effect=type('Forbidden403Error',(Exception,),{})('private-token-value')
        self.assertEqual(check_downloader(lambda:adapter)['error_code'],'downloader_auth_failed')
        adapter.client.app_version.side_effect=TimeoutError('private-token-value')
        self.assertEqual(check_downloader(lambda:adapter)['error_code'],'downloader_unavailable')
        adapter.client.app_version.side_effect=None
        adapter.client.app_version.return_value='<html>private-token-value</html>'
        result=check_downloader(lambda:adapter)
        self.assertEqual(result['error_code'],'invalid_downloader_response')
        self.assertNotIn('private-token-value',str(result))

    def test_pairing_failure_hints_never_echo_original_exception(self):
        import requests
        errors=[requests.ConnectionError('private-token-value'),requests.Timeout('private-token-value'),
                PermissionError('private-token-value'),ValueError('private-token-value')]
        for error in errors:
            message=pairing_error_message(error)
            self.assertNotIn('private-token-value',message)
            self.assertIn('Existing keys will not be overwritten',message)
        self.assertIn('127.0.0.1',pairing_error_message(errors[0]))
        for status in (400,403,404):
            response=requests.Response();response.status_code=status
            message=pairing_error_message(requests.HTTPError('private-token-value',response=response))
            self.assertNotIn('private-token-value',message)
            self.assertIn('control',message.lower())
