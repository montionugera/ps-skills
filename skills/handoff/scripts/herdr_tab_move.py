#!/usr/bin/env python3
"""Move a Herdr tab to a slot in its workspace through the socket API (`tab.move`).

`herdr tab` has no move subcommand, but the server takes
`{"method": "tab.move", "params": {"tab_id": ..., "insert_index": N}}`, where N
counts tabs from 0. Prints nothing on success; exits 1 with the reason on stderr.
"""
import argparse
import json
import socket
import sys


def move(socket_path, tab_id, index, timeout=3.0):
    request = {"id": "handoff-tab-move", "method": "tab.move", "params": {"tab_id": tab_id, "insert_index": index}}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(socket_path)
        sock.sendall((json.dumps(request) + "\n").encode())
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    reply = json.loads(data.split(b"\n", 1)[0] or b"{}")
    if "result" not in reply:
        raise RuntimeError(json.dumps(reply.get("error") or reply))
    return reply["result"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--tab", required=True)
    parser.add_argument("--index", required=True, type=int)
    args = parser.parse_args()
    try:
        move(args.socket, args.tab, args.index)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
