#!/usr/bin/env python3
"""PreToolUse guard for Antigravity (AGY): read_file / view_file.

Guards:
1. Guard A: Denies reading raw transcript JSONL (>24KB) without a narrow line window (<=80 lines)
   to prevent context blowout (~12K-30K tokens per unconstrained read).
2. Guard B: Transparently downscales oversized raster images (>1024px) via macOS `sips` with
   disk caching, saving thousands of tokens per screenshot read.

Fails open (empty stdout) on any error or unexpected input.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def main():
    if os.environ.get("AGY_READ_GUARD") == "0":
        return

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
    except Exception:
        return

    if not isinstance(data, dict):
        return

    tool_call = data.get("toolCall") or {}
    tool_name = tool_call.get("name") or data.get("name") or data.get("tool_name") or ""
    if tool_name and tool_name not in ("read_file", "view_file", "Read"):
        return

    args = tool_call.get("args") or data.get("args") or data.get("tool_input") or {}
    if not isinstance(args, dict):
        return

    path_key = None
    for k in ("Path", "AbsolutePath", "filePath", "file_path", "path"):
        if k in args and isinstance(args[k], str) and args[k].strip():
            path_key = k
            break

    if not path_key:
        return

    src_raw = args[path_key]
    src = os.path.abspath(os.path.expanduser(src_raw))
    real_src = os.path.realpath(src)

    # --- Guard A: Raw transcript JSONL ---
    norm_path = src.replace("\\", "/")
    real_norm_path = real_src.replace("\\", "/")
    base_names = (os.path.basename(src), os.path.basename(real_src))
    base_name = os.path.basename(real_src) if os.path.basename(real_src) in ("transcript.jsonl", "transcript_full.jsonl") else os.path.basename(src)

    is_transcript = (
        any(bn in ("transcript.jsonl", "transcript_full.jsonl") for bn in base_names)
        or any("/.system_generated/logs/" in p and p.endswith(".jsonl") for p in (norm_path, real_norm_path))
    )

    check_src = real_src if os.path.isfile(real_src) else src
    if is_transcript and os.path.isfile(check_src):
        try:
            file_size = os.path.getsize(check_src)
        except OSError:
            file_size = 0
        guard_bytes = int(os.environ.get("AGY_TRANSCRIPT_GUARD_BYTES", "24000"))
        if file_size > guard_bytes:
            start_line_val = args.get("StartLine") if args.get("StartLine") is not None else args.get("start_line")
            end_line_val = args.get("EndLine") if args.get("EndLine") is not None else args.get("end_line")

            allowed_window = False
            if start_line_val is not None and end_line_val is not None:
                if not isinstance(start_line_val, bool) and not isinstance(end_line_val, bool):
                    try:
                        sl = int(start_line_val)
                        el = int(end_line_val)
                        max_lines = int(os.environ.get("AGY_TRANSCRIPT_MAX_LINES", "80"))
                        if sl >= 1 and el >= sl and (el - sl + 1) <= max_lines:
                            allowed_window = True
                    except (ValueError, TypeError):
                        allowed_window = False

            if not allowed_window:
                reason = (
                    f"Context bloat guard: reading raw transcript JSONL ({base_name}) without a narrow line window "
                    f"(<=80 lines) dumps ~12K-30K tokens per call into main context. Use grep -n / tail -n 30 via "
                    "run_command, check ## Late results, or pass explicit StartLine and EndLine (<=80 lines)."
                )
                print(json.dumps({"decision": "deny", "reason": reason}))
                return

    # --- Guard B: Image downscale via macOS sips ---
    if (
        os.environ.get("AGY_IMAGE_DOWNSCALE", "1") != "0"
        and re.search(r"\.(png|jpg|jpeg|webp|tiff|tif|bmp|heic)$", src, re.IGNORECASE)
        and os.path.isfile(src)
        and shutil.which("sips")
    ):
        try:
            p_dims = subprocess.run(
                ["sips", "-g", "pixelWidth", "-g", "pixelHeight", src],
                capture_output=True,
                text=True,
                timeout=3,
            )
            w, h = 0, 0
            if p_dims.returncode == 0:
                mw = re.search(r"pixelWidth:\s*(\d+)", p_dims.stdout)
                mh = re.search(r"pixelHeight:\s*(\d+)", p_dims.stdout)
                if mw and mh:
                    w, h = int(mw.group(1)), int(mh.group(1))

            max_dim = int(os.environ.get("AGY_IMAGE_DOWNSCALE_MAXDIM", "1024"))
            if w > max_dim or h > max_dim:
                cache_dir_str = os.environ.get("AGY_IMAGE_DOWNSCALE_CACHE_DIR") or "~/.claude/cache/downscaled-images"
                cache_dir = Path(cache_dir_str).expanduser()
                cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                try:
                    os.chmod(cache_dir, 0o700)
                except OSError:
                    pass

                stat = os.stat(src)
                mtime = int(stat.st_mtime)
                size = stat.st_size
                key_src = f"{src}|{mtime}|{size}|{max_dim}"
                key = hashlib.md5(key_src.encode("utf-8")).hexdigest()

                safe_stem = re.sub(r"[^\w.-]", "_", Path(src).stem)[:40]
                ext = Path(src).suffix.lstrip(".").lower()
                out_path = cache_dir / f"{safe_stem}-{max_dim}px-{key[:12]}.{ext}"
                meta_path = cache_dir / f"{safe_stem}-{max_dim}px-{key[:12]}.json"

                if meta_path.is_file() and out_path.is_file():
                    try:
                        cached = json.loads(meta_path.read_text(encoding="utf-8"))
                        if isinstance(cached, dict) and "nw" in cached and "nh" in cached:
                            cw = cached.get("w", w)
                            ch = cached.get("h", h)
                            cnw = cached["nw"]
                            cnh = cached["nh"]
                            tok_before = cached.get("tok_before", (cw * ch // 750) if (cw and ch) else 0)
                            tok_after = cached.get("tok_after", max(1, cnw * cnh // 750))
                            pct = cached.get("pct", round(((tok_before - tok_after) / tok_before) * 100) if tok_before else 0)
                            reason = (
                                f"Context guard: downscaled {base_name} from {cw}x{ch} to {cnw}x{cnh} "
                                f"(~{tok_before} tokens -> ~{tok_after}, {pct}% saved). Original untouched at {src}."
                            )
                            decision_payload = {
                                "decision": "allow",
                                "reason": reason,
                                "overwrite": {path_key: str(out_path)},
                            }
                            print(json.dumps(decision_payload))
                            return
                    except Exception:
                        pass

                if not out_path.is_file():
                    tmp_out = cache_dir / f"{out_path.name}.tmp.{os.getpid()}"
                    p_scale = subprocess.run(
                        ["sips", "-Z", str(max_dim), src, "--out", str(tmp_out)],
                        capture_output=True,
                        timeout=3,
                    )
                    if p_scale.returncode != 0 or not tmp_out.is_file():
                        tmp_out.unlink(missing_ok=True)
                        return
                    os.replace(tmp_out, out_path)

                p_new = subprocess.run(
                    ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(out_path)],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                nw, nh = 0, 0
                if p_new.returncode == 0:
                    mnw = re.search(r"pixelWidth:\s*(\d+)", p_new.stdout)
                    mnh = re.search(r"pixelHeight:\s*(\d+)", p_new.stdout)
                    if mnw and mnh:
                        nw, nh = int(mnw.group(1)), int(mnh.group(1))

                if not (nw and nh):
                    if w >= h:
                        nw, nh = max_dim, max(1, round(h * max_dim / w))
                    else:
                        nw, nh = max(1, round(w * max_dim / h)), max_dim

                tok_before = w * h // 750
                tok_after = max(1, nw * nh // 750)
                saved = tok_before - tok_after
                min_saved = int(os.environ.get("AGY_IMAGE_DOWNSCALE_MIN_SAVED", "400"))

                if saved >= min_saved:
                    pct = round((saved / tok_before) * 100) if tok_before else 0
                    reason = (
                        f"Context guard: downscaled {base_name} from {w}x{h} to {nw}x{nh} "
                        f"(~{tok_before} tokens -> ~{tok_after}, {pct}% saved). Original untouched at {src}."
                    )
                    meta_payload = {
                        "w": w,
                        "h": h,
                        "nw": nw,
                        "nh": nh,
                        "tok_before": tok_before,
                        "tok_after": tok_after,
                        "pct": pct,
                    }
                    tmp_meta = cache_dir / f"{meta_path.name}.tmp.{os.getpid()}"
                    try:
                        tmp_meta.write_text(json.dumps(meta_payload), encoding="utf-8")
                        os.replace(tmp_meta, meta_path)
                    except Exception:
                        try:
                            tmp_meta.unlink(missing_ok=True)
                        except OSError:
                            pass

                    decision_payload = {
                        "decision": "allow",
                        "reason": reason,
                        "overwrite": {path_key: str(out_path)},
                    }
                    print(json.dumps(decision_payload))
                    return
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
