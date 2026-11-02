import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest

from openpush_scan.client import Client, ClientError, OAuthManifestClient


class Handler(BaseHTTPRequestHandler):
    response_code = 200
    response = {}
    received = None

    def do_GET(self):
        self._answer()

    def do_PUT(self):
        self._answer()

    def do_POST(self):
        self._answer()

    def _answer(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        type(self).received = (self.command, self.path, self.headers.get("X-OP-API-Key"),
                               json.loads(body) if body else None,
                               self.headers.get("Authorization"))
        payload = json.dumps(type(self).response).encode()
        self.send_response(type(self).response_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Handler.response_code = 200
        Handler.response = {}

    def test_put_manifest_uses_expected_route_header_and_body(self):
        Handler.response = {"manifest_id": "man_1"}
        doc = {"manifest_version": 1}
        result = Client(self.origin, "k").put_manifest("demo", doc)
        self.assertEqual(result["manifest_id"], "man_1")
        self.assertEqual(Handler.received, ("PUT", "/v1/apps/demo/manifest", "k", doc, None))

    def test_oauth_prepare_uses_bearer_and_two_step_route(self):
        Handler.response = {"confirm_token": "opc_1"}
        result = OAuthManifestClient(self.origin, "opat_secret").prepare(
            "example game", {"manifest_version": 1})
        self.assertEqual("opc_1", result["confirm_token"])
        self.assertEqual(
            ("POST", "/cli/v1/apps/example%20game/manifest/prepare", None,
             {"manifest": {"manifest_version": 1}}, "Bearer opat_secret"),
            Handler.received,
        )

    def test_read_only_error_is_clear(self):
        Handler.response_code = 403
        Handler.response = {"detail": "read-only X-OP-API-Key"}
        with self.assertRaisesRegex(ClientError, "This API key is read-only"):
            Client(self.origin, "k").put_manifest("demo", {})

    def test_unreachable_error_names_origin(self):
        with self.assertRaisesRegex(ClientError, "Could not reach http://127.0.0.1:1"):
            Client("http://127.0.0.1:1", "k").schema()


if __name__ == "__main__":
    unittest.main()
