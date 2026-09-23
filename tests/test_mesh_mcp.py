#!/usr/bin/env python3
"""mesh MCP server: every request must get a response, even unknown methods.

A request the server ignores leaves the client waiting forever. agy 1.2.x opens
each stdio MCP server with `server/discover`; mesh answered nothing, so agy's
print mode never started a turn.
"""
import json
import os
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
        return json.loads(self.proc.stdout.readline())

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


if __name__ == "__main__":
    unittest.main()
