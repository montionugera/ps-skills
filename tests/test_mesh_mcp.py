#!/usr/bin/env python3
"""mesh MCP server: every request must get a response, even unknown methods.

A request the server ignores leaves the client waiting forever. agy 1.2.x opens
each stdio MCP server with `server/discover`; mesh answered nothing, so agy's
print mode never started a turn.
"""
import json
import os
import queue
import threading
import subprocess
import tempfile
import unittest
from pathlib import Path

MESH = Path(__file__).resolve().parent.parent / "bin" / "mesh"


class MeshMcpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = dict(os.environ)
        env["AGENT_MESH_DB"] = os.path.join(self.tmp.name, "mesh.db")
        env["MESH_AGENT_ID"] = "test-agent"
        self.proc = subprocess.Popen(
            [str(MESH), "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
        )
        # Read on a thread so a missing reply times out instead of hanging the suite.
        self.lines = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put("")  # EOF: the server exited

    def tearDown(self):
        self.proc.kill()
        self.proc.wait()
        self.proc.stdin.close()
        self.proc.stdout.close()
        self.tmp.cleanup()

    def request(self, line: str) -> dict:
        """Send one line; return the next response, failing instead of hanging."""
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        # A sentinel ping after the request: if the request got no reply, the
        # first line read is the ping's reply instead.
        self.proc.stdin.write('{"jsonrpc":"2.0","id":"sentinel","method":"ping"}\n')
        self.proc.stdin.flush()
        resp = self._read()
        if resp.get("id") != "sentinel":
            self.assertEqual(self._read()["id"], "sentinel")  # drain; server still alive
        return resp

    def _read(self) -> dict:
        try:
            line = self.lines.get(timeout=5)
        except queue.Empty:
            self.fail("mesh sent no reply within 5s")
        self.assertTrue(line, "mesh exited instead of replying")
        return json.loads(line)

    def test_unknown_method_gets_method_not_found(self):
        resp = self.request('{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{}}')
        self.assertEqual(resp["id"], 1)
        self.assertEqual(resp["error"]["code"], -32601)

    def test_unknown_notification_gets_no_response(self):
        resp = self.request('{"jsonrpc":"2.0","method":"notifications/cancelled"}')
        self.assertEqual(resp["id"], "sentinel")

    def test_malformed_json_gets_parse_error(self):
        resp = self.request("{not json")
        self.assertIsNone(resp["id"])
        self.assertEqual(resp["error"]["code"], -32700)

    def test_known_methods_still_work(self):
        resp = self.request('{"jsonrpc":"2.0","id":2,"method":"initialize","params":{}}')
        self.assertEqual(resp["result"]["serverInfo"]["name"], "mesh")

    def test_non_object_json_gets_invalid_request_and_server_survives(self):
        for payload in ("[]", "5", "null", '"x"', '[{"jsonrpc":"2.0","id":1,"method":"ping"}]'):
            resp = self.request(payload)
            self.assertIsNone(resp["id"], payload)
            self.assertEqual(resp["error"]["code"], -32600, payload)

    def test_tool_call_with_missing_argument_gets_error_and_server_survives(self):
        resp = self.request('{"jsonrpc":"2.0","id":3,"method":"tools/call",'
                            '"params":{"name":"mesh_claim","arguments":{}}}')
        self.assertEqual(resp["id"], 3)
        self.assertEqual(resp["error"]["code"], -32602)
        self.assertEqual(self.request('{"jsonrpc":"2.0","id":4,"method":"ping"}')["id"], 4)

    def test_unknown_tool_gets_error(self):
        resp = self.request('{"jsonrpc":"2.0","id":5,"method":"tools/call",'
                            '"params":{"name":"no_such_tool","arguments":{}}}')
        self.assertEqual(resp["id"], 5)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_non_object_params_does_not_crash(self):
        resp = self.request('{"jsonrpc":"2.0","id":6,"method":"tools/call","params":5}')
        self.assertEqual(resp["id"], 6)
        self.assertIn("error", resp)


if __name__ == "__main__":
    unittest.main()
