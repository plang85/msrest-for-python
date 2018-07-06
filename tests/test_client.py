﻿#--------------------------------------------------------------------------
#
# Copyright (c) Microsoft Corporation. All rights reserved.
#
# The MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the ""Software""), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED *AS IS*, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
#--------------------------------------------------------------------------

import io
import json
import unittest
try:
    from unittest import mock
except ImportError:
    import mock
import sys

import requests
from requests.adapters import HTTPAdapter
from oauthlib import oauth2

from msrest import ServiceClient, SDKClient
from msrest.pipeline import HTTPSender
from msrest.pipeline.requests import RequestsHTTPSender
from msrest.pipeline.universal import HTTPLogger
from msrest.authentication import OAuthTokenAuthentication, Authentication

from msrest import Configuration
from msrest.exceptions import ClientRequestError, TokenExpiredError
from msrest.pipeline import ClientRequest, ClientResponse


class TestServiceClient(unittest.TestCase):

    def setUp(self):
        self.cfg = Configuration("https://my_endpoint.com")
        self.cfg.headers = {'Test': 'true'}
        self.creds = mock.create_autospec(OAuthTokenAuthentication)
        return super(TestServiceClient, self).setUp()

    def test_session_callback(self):

        with RequestsHTTPSender(self.cfg) as driver:

            def callback(session, global_config, local_config, **kwargs):
                self.assertIs(session, driver.session)
                self.assertIs(global_config, self.cfg)
                self.assertTrue(local_config["test"])
                my_kwargs = kwargs.copy()
                my_kwargs.update({'used_callback': True})
                return my_kwargs

            self.cfg.session_configuration_callback = callback

            request = ClientRequest('GET', 'http://127.0.0.1/')
            request.pipeline_context = driver.build_context()
            output_kwargs = driver._configure_send(request, **{"test": True})
            self.assertTrue(output_kwargs['used_callback'])

    def test_sdk_context_manager(self):
        cfg = Configuration("http://127.0.0.1/")

        class Creds(Authentication):
            def __init__(self):
                self.first_session = None
                self.called = 0

            def signed_session(self, session=None):
                self.called += 1
                assert session is not None
                if self.first_session:
                    assert self.first_session is session
                else:
                    self.first_session = session
        creds = Creds()

        with SDKClient(creds, cfg) as client:
            assert cfg.keep_alive

            req = client._client.get('/')
            try:
                # Will fail, I don't care, that's not the point of the test
                client._client.send(req, timeout=0)
            except Exception:
                pass

            try:
                # Will fail, I don't care, that's not the point of the test
                client._client.send(req, timeout=0)
            except Exception:
                pass

        assert not cfg.keep_alive
        assert creds.called == 2

    def test_context_manager(self):

        cfg = Configuration("http://127.0.0.1/")

        class Creds(Authentication):
            def __init__(self):
                self.first_session = None
                self.called = 0

            def signed_session(self, session=None):
                self.called += 1
                assert session is not None
                if self.first_session:
                    assert self.first_session is session
                else:
                    self.first_session = session
        creds = Creds()

        with ServiceClient(creds, cfg) as client:
            assert cfg.keep_alive

            req = client.get('/')
            try:
                # Will fail, I don't care, that's not the point of the test
                client.send(req, timeout=0)
            except Exception:
                pass

            try:
                # Will fail, I don't care, that's not the point of the test
                client.send(req, timeout=0)
            except Exception:
                pass

        assert not cfg.keep_alive
        assert creds.called == 2

    def test_keep_alive(self):

        cfg = Configuration("http://127.0.0.1/")
        cfg.keep_alive = True

        class Creds(Authentication):
            def __init__(self):
                self.first_session = None
                self.called = 0

            def signed_session(self, session=None):
                self.called += 1
                assert session is not None
                if self.first_session:
                    assert self.first_session is session
                else:
                    self.first_session = session
        creds = Creds()

        client = ServiceClient(creds, cfg)
        req = client.get('/')
        try:
            # Will fail, I don't care, that's not the point of the test
            client.send(req, timeout=0)
        except Exception:
            pass

        try:
            # Will fail, I don't care, that's not the point of the test
            client.send(req, timeout=0)
        except Exception:
            pass

        assert creds.called == 2
        # Manually close the client in "keep_alive" mode
        client.close()

    def test_max_retries_on_default_adapter(self):
        # max_retries must be applied only on the default adapters of requests
        # If the user adds its own adapter, don't touch it
        max_retries = self.cfg.retry_policy()

        with RequestsHTTPSender(self.cfg) as driver:
            request = ClientRequest('GET', '/')
            request.pipeline_context = driver.build_context()
            request.pipeline_context.session.mount('"http://127.0.0.1/"', HTTPAdapter())

            driver._configure_send(request)
            assert driver.session.adapters["http://"].max_retries is max_retries
            assert driver.session.adapters["https://"].max_retries is max_retries
            assert driver.session.adapters['"http://127.0.0.1/"'].max_retries is not max_retries

    @mock.patch('msrest.http_logger._LOGGER')
    def test_no_log(self, mock_http_logger):
        request = ClientRequest('GET', 'http://127.0.0.1/')
        http_logger = HTTPLogger(self.cfg)
        response = ClientResponse(request)

        # By default, no log handler for HTTP
        http_logger.prepare(request)
        mock_http_logger.debug.assert_not_called()
        http_logger.post_send(request, response)
        mock_http_logger.debug.assert_not_called()
        mock_http_logger.reset_mock()

        # I can enable it per request
        http_logger.prepare(request, **{"enable_http_logger": True})
        assert mock_http_logger.debug.call_count >= 1
        http_logger.post_send(request, response, **{"enable_http_logger": True})
        assert mock_http_logger.debug.call_count >= 1
        mock_http_logger.reset_mock()

        # I can enable it per request (bool value should be honored)
        http_logger.prepare(request, **{"enable_http_logger": False})
        mock_http_logger.debug.assert_not_called()
        http_logger.post_send(request, response, **{"enable_http_logger": False})
        mock_http_logger.debug.assert_not_called()
        mock_http_logger.reset_mock()

        # I can enable it globally
        self.cfg.enable_http_logger = True
        http_logger.prepare(request)
        assert mock_http_logger.debug.call_count >= 1
        http_logger.post_send(request, response)
        assert mock_http_logger.debug.call_count >= 1
        mock_http_logger.reset_mock()

        # I can enable it globally and override it locally
        self.cfg.enable_http_logger = True
        http_logger.prepare(request, **{"enable_http_logger": False})
        mock_http_logger.debug.assert_not_called()
        http_logger.post_send(request, response, **{"enable_http_logger": False})
        mock_http_logger.debug.assert_not_called()
        mock_http_logger.reset_mock()

    def test_client_request(self):

        cfg = Configuration("http://127.0.0.1/")
        client = ServiceClient(self.creds, cfg)
        obj = client.get('/')
        self.assertEqual(obj.method, 'GET')
        self.assertEqual(obj.url, "http://127.0.0.1/")

        obj = client.get("/service", {'param':"testing"})
        self.assertEqual(obj.method, 'GET')
        self.assertEqual(obj.url, "http://127.0.0.1/service?param=testing")

        obj = client.get("service 2")
        self.assertEqual(obj.method, 'GET')
        self.assertEqual(obj.url, "http://127.0.0.1/service 2")

        cfg.base_url = "https://127.0.0.1/"
        obj = client.get("//service3")
        self.assertEqual(obj.method, 'GET')
        self.assertEqual(obj.url, "https://127.0.0.1/service3")

        obj = client.put('/')
        self.assertEqual(obj.method, 'PUT')

        obj = client.post('/')
        self.assertEqual(obj.method, 'POST')

        obj = client.head('/')
        self.assertEqual(obj.method, 'HEAD')

        obj = client.merge('/')
        self.assertEqual(obj.method, 'MERGE')

        obj = client.patch('/')
        self.assertEqual(obj.method, 'PATCH')

        obj = client.delete('/')
        self.assertEqual(obj.method, 'DELETE')

    def test_format_url(self):

        url = "/bool/test true"

        client = mock.create_autospec(ServiceClient)
        client.config = mock.Mock(base_url="http://localhost:3000")

        formatted = ServiceClient.format_url(client, url)
        self.assertEqual(formatted, "http://localhost:3000/bool/test true")

        client.config = mock.Mock(base_url="http://localhost:3000/")
        formatted = ServiceClient.format_url(client, url, foo=123, bar="value")
        self.assertEqual(formatted, "http://localhost:3000/bool/test true")

        url = "https://absolute_url.com/my/test/path"
        formatted = ServiceClient.format_url(client, url)
        self.assertEqual(formatted, "https://absolute_url.com/my/test/path")
        formatted = ServiceClient.format_url(client, url, foo=123, bar="value")
        self.assertEqual(formatted, "https://absolute_url.com/my/test/path")

        url = "test"
        formatted = ServiceClient.format_url(client, url)
        self.assertEqual(formatted, "http://localhost:3000/test")

        client.config = mock.Mock(base_url="http://{hostname}:{port}/{foo}/{bar}")
        formatted = ServiceClient.format_url(client, url, hostname="localhost", port="3000", foo=123, bar="value")
        self.assertEqual(formatted, "http://localhost:3000/123/value/test")

        client.config = mock.Mock(base_url="https://my_endpoint.com/")
        formatted = ServiceClient.format_url(client, url, foo=123, bar="value")
        self.assertEqual(formatted, "https://my_endpoint.com/test")


    def test_client_send(self):
        current_ua = self.cfg.user_agent

        class MockHTTPDriver(object):
            def configure_session(self, **config):
                pass
            def send(self, request, **config):
                pass

        client = ServiceClient(self.creds, self.cfg)
        client.config.keep_alive = True

        session = mock.create_autospec(requests.Session)
        session.adapters = {
            "http://": HTTPAdapter(),
            "https://": HTTPAdapter(),
        }
        # Be sure the mock does not trick me
        assert not hasattr(session.resolve_redirects, 'is_mrest_patched')

        client._pipeline._sender.session = session
        # Hack, reconfigure session
        client._pipeline._sender._init_session()

        client.creds.signed_session.return_value = session
        client.creds.refresh_session.return_value = session

        request = ClientRequest('GET', '/')
        client.send(request, stream=False)
        session.request.call_count = 0
        session.request.assert_called_with(
            'GET',
            '/',
            allow_redirects=True,
            cert=None,
            headers={
                'User-Agent': current_ua,
                'Test': 'true'  # From global config
            },
            stream=False,
            timeout=100,
            verify=True
        )
        assert session.resolve_redirects.is_mrest_patched

        client.send(request, headers={'id':'1234'}, content={'Test':'Data'}, stream=False)
        session.request.assert_called_with(
            'GET',
            '/',
            data='{"Test": "Data"}',
            allow_redirects=True,
            cert=None,
            headers={
                'User-Agent': current_ua,
                'Content-Length': '16',
                'id':'1234',
                'Test': 'true'  # From global config
            },
            stream=False,
            timeout=100,
            verify=True
        )
        self.assertEqual(session.request.call_count, 1)
        session.request.call_count = 0
        assert session.resolve_redirects.is_mrest_patched

        session.request.side_effect = requests.RequestException("test")
        with self.assertRaises(ClientRequestError):
            client.send(request, headers={'id':'1234'}, content={'Test':'Data'}, test='value', stream=False)
        session.request.assert_called_with(
            'GET',
            '/',
            data='{"Test": "Data"}',
            allow_redirects=True,
            cert=None,
            headers={
                'User-Agent': current_ua,
                'Content-Length': '16',
                'id':'1234',
                'Test': 'true'  # From global config
            },
            stream=False,
            timeout=100,
            verify=True
        )
        self.assertEqual(session.request.call_count, 1)
        session.request.call_count = 0
        assert session.resolve_redirects.is_mrest_patched

        session.request.side_effect = oauth2.rfc6749.errors.InvalidGrantError("test")
        with self.assertRaises(TokenExpiredError):
            client.send(request, headers={'id':'1234'}, content={'Test':'Data'}, test='value')
        self.assertEqual(session.request.call_count, 2)
        session.request.call_count = 0

        session.request.side_effect = ValueError("test")
        with self.assertRaises(ValueError):
            client.send(request, headers={'id':'1234'}, content={'Test':'Data'}, test='value')

    @mock.patch.object(ClientRequest, "_format_data")
    def test_client_formdata_add(self, format_data):
        format_data.return_value = "formatted"

        request = ClientRequest('GET', '/')
        request.add_formdata()
        assert request.files == {}

        request = ClientRequest('GET', '/')
        request.add_formdata({'Test':'Data'})
        assert request.files == {'Test':'formatted'}

        request = ClientRequest('GET', '/')
        request.headers = {'Content-Type':'1234'}
        request.add_formdata({'1':'1', '2':'2'})
        assert request.files == {'1':'formatted', '2':'formatted'}

        request = ClientRequest('GET', '/')
        request.headers = {'Content-Type':'1234'}
        request.add_formdata({'1':'1', '2':None})
        assert request.files == {'1':'formatted'}

        request = ClientRequest('GET', '/')
        request.headers = {'Content-Type':'application/x-www-form-urlencoded'}
        request.add_formdata({'1':'1', '2':'2'})
        assert request.files is None
        assert request.data == {'1':'1', '2':'2'}

        request = ClientRequest('GET', '/')
        request.headers = {'Content-Type':'application/x-www-form-urlencoded'}
        request.add_formdata({'1':'1', '2':None})
        assert request.files is None
        assert request.data == {'1':'1'}

    def test_format_data(self):

        data = ClientRequest._format_data(None)
        self.assertEqual(data, (None, None))

        data = ClientRequest._format_data("Test")
        self.assertEqual(data, (None, "Test"))

        mock_stream = mock.create_autospec(io.BytesIO)
        data = ClientRequest._format_data(mock_stream)
        self.assertEqual(data, (None, mock_stream, "application/octet-stream"))

        mock_stream.name = "file_name"
        data = ClientRequest._format_data(mock_stream)
        self.assertEqual(data, ("file_name", mock_stream, "application/octet-stream"))

    def test_request_builder(self):
        client = ServiceClient(self.creds, self.cfg)

        req = client.get('http://127.0.0.1/')
        assert req.method == 'GET'
        assert req.url == 'http://127.0.0.1/'
        assert req.headers == {'Accept': 'application/json'}
        assert req.data is None
        assert req.files is None

        req = client.put("http://127.0.0.1/", content={'creation': True})
        assert req.method == 'PUT'
        assert req.url == "http://127.0.0.1/"
        assert req.headers == {'Content-Length': '18', 'Accept': 'application/json'}
        assert req.data == '{"creation": true}'
        assert req.files is None


if __name__ == '__main__':
    unittest.main()