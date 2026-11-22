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
import http
import http.server
import os
import socketserver
import sys
import urllib.parse


class LocalServer(http.server.ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer.server_bind calls socket.getfqdn(host) before listen();
        # reverse DNS can stall >10s (GitHub macOS runners), so skip it.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        self._root_real = os.path.realpath(directory or os.getcwd())
        self._send_allow = False
        super().__init__(*args, directory=directory, **kwargs)

    def _is_within_root(self, path: str) -> bool:
        rp = os.path.realpath(path)
        root = self._root_real.rstrip(os.sep)
        if not root:
            return rp.startswith(os.sep)
        return rp == root or rp.startswith(root + os.sep)

    def _method_not_allowed(self):
        self._send_allow = True
        self.send_error(http.HTTPStatus.METHOD_NOT_ALLOWED, "Method Not Allowed")

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self._method_not_allowed
        raise AttributeError(name)

    def list_directory(self, path):
        self.send_error(http.HTTPStatus.NOT_FOUND, "File not found")
        return None

    def send_head(self):
        raw_path = self.path.split("#", 1)[0].split("?", 1)[0]
        try:
            decoded = urllib.parse.unquote(raw_path, errors="surrogatepass")
        except UnicodeDecodeError:
            decoded = urllib.parse.unquote(raw_path)
        if "\x00" in decoded:
            self.send_error(http.HTTPStatus.NOT_FOUND, "File not found")
            return None
        for seg in decoded.replace("\\", "/").split("/"):
            if seg and seg.startswith("."):
                self.send_error(http.HTTPStatus.NOT_FOUND, "File not found")
                return None

        path = self.translate_path(self.path)
        if not self._is_within_root(path):
            self.send_error(http.HTTPStatus.NOT_FOUND, "File not found")
            return None

        if os.path.isdir(path):
            has_index = False
            for index in self.index_pages:
                idx_path = os.path.join(path, index)
                if os.path.isfile(idx_path):
                    if not self._is_within_root(idx_path):
                        self.send_error(http.HTTPStatus.NOT_FOUND, "File not found")
                        return None
                    has_index = True
                    break
            if not has_index:
                return self.list_directory(path)

        return super().send_head()

    def end_headers(self):
        if self._send_allow:
            self.send_header("Allow", "GET, HEAD")
            self._send_allow = False
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
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
