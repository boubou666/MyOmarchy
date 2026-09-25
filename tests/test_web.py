import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

import web


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_page_and_state_load_locally(self):
        with urlopen(self.base + "/") as response:
            page = response.read().decode()
            self.assertIn("Build Omarchy your way", page)
            self.assertIn(web.TOKEN, page)
        with urlopen(self.base + "/api/state") as response:
            state = json.load(response)
            self.assertIn("packages", state)
            self.assertIn("isos", state)
            self.assertIn("catalogs", state)
            self.assertIn("v4.0.3", [item["key"] for item in state["targets"]])
        with urlopen(self.base + "/api/catalog?q=firefox") as response:
            result = json.load(response)
            self.assertIn("packages", result)

    def test_mutations_require_local_origin_and_token(self):
        request = Request(self.base + "/api/build", data=b"{}",
                          headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(HTTPError) as result:
            urlopen(request)
        self.assertEqual(result.exception.code, 403)
        result.exception.close()

    def test_start_docker_uses_desktop_cli_after_local_request(self):
        request = Request(self.base + "/api/docker/start", data=b"{}", headers={
            "Content-Type": "application/json", "Origin": self.base,
            "X-MyOmarchy-Token": web.TOKEN,
        }, method="POST")
        with patch.dict(web.DOCKER_SNAPSHOT, {"desktop_available": True}), \
             patch.object(web, "docker_status", return_value={"ready": False}), \
             patch.object(web.JOB, "start") as start:
            with urlopen(request) as response:
                self.assertEqual(response.status, 202)
            start.assert_called_once_with("Starting Docker Desktop", [
                "docker", "desktop", "start", "--timeout", "180"
            ])


if __name__ == "__main__":
    unittest.main()
