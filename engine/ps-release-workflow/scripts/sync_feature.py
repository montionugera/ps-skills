"""ps-release-workflow:sync — merge release/<v> into current feature branch."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import sys
from pathlib import Path

from scripts.epic import epic_sync


def main() -> int:
    try:
        res = epic_sync(Path.cwd())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
