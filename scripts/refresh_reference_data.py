"""Re-fetch nationality codes from ACIS and save them to src/eoir_api/reference/.

Usage:
    mise run refresh-reference
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REFERENCE_DIR = Path(__file__).parent.parent / "src" / "eoir_api" / "reference"

BASE = "https://acis.eoir.justice.gov/page-data/sq/d"
NATIONALITY_URL = f"{BASE}/1791802679.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def fetch(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", "utf-8")
    print(f"wrote {path}")


def main() -> int:
    try:
        nationalities = fetch(NATIONALITY_URL)["data"]["countries"]["countries"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: could not refresh reference data: {exc}", file=sys.stderr)
        print(
            "The Gatsby query hashes likely rotated; re-derive them from the "
            "page bundle. Existing snapshots are still valid.",
            file=sys.stderr,
        )
        return 1

    write(REFERENCE_DIR / "nationality-codes.json", nationalities)
    print(f"{len(nationalities)} nationalities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
