#!/usr/bin/env python3
"""No-cache static server for ps-commu workspaces.

Sends Cache-Control: no-store so fix-loop edits are always visible on plain
reload (python -m http.server sends no cache headers and browsers cache
heuristically). Binds 127.0.0.1 ONLY (spec D9). The docroot argv carries the
workspace path — the kill-safety marker (spec D7).

Usage: httpserve.py PORT DOCROOT [READYFILE]
  READYFILE  written with this process's PID once the socket is bound, so
             serve.sh can tell "bound" from "still starting" without lsof.
             A bind failure (port taken) exits non-zero before writing it.
"""
import functools
import http.server
import os
import socketserver
import sys


class LocalServer(http.server.ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer.server_bind calls socket.getfqdn(host) before listen();
        # reverse DNS can stall >10s (GitHub macOS runners), so skip it.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass  # server.log stays quiet; serve.sh logs attempts


def main() -> None:
    port, root = int(sys.argv[1]), sys.argv[2]
    handler = functools.partial(NoCacheHandler, directory=root)
    server = LocalServer(("127.0.0.1", port), handler)
    if len(sys.argv) > 3:
        tmp = sys.argv[3] + ".tmp"
        with open(tmp, "w") as f:
            f.write(str(os.getpid()))
        os.replace(tmp, sys.argv[3])
    server.serve_forever()


if __name__ == "__main__":
    main()
