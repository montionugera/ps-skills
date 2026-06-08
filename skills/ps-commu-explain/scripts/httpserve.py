#!/usr/bin/env python3
"""No-cache static server for ps-commu workspaces.

Sends Cache-Control: no-store so fix-loop edits are always visible on plain
reload (python -m http.server sends no cache headers and browsers cache
heuristically). Binds 127.0.0.1 ONLY (spec D9). The docroot argv carries the
workspace path — the kill-safety marker (spec D7).

Usage: httpserve.py PORT DOCROOT
"""
import functools
import http.server
import sys


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass  # server.log stays quiet; serve.sh logs attempts


def main() -> None:
    port, root = int(sys.argv[1]), sys.argv[2]
    handler = functools.partial(NoCacheHandler, directory=root)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


if __name__ == "__main__":
    main()
