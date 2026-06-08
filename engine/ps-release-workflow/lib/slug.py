"""Title → kebab-slug. Used for I-NNN-<slug>/ and F-NNN-<slug>/ folder names."""
import re


class SlugError(Exception):
    """Raised on empty/unslugifiable input."""


def slugify(title: str, max_len: int = 40) -> str:
    """Convert a free-text title to a filesystem-safe kebab-slug."""
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)  # non-alnum → dash
    s = re.sub(r"-+", "-", s).strip("-")  # collapse + strip
    if not s:
        raise SlugError(f"cannot slugify {title!r}")
    return s[:max_len].rstrip("-")
