#!/usr/bin/env python3
"""Re-introduce the intentional bug in the sample project.

The offline demo (`python run_agent.py --provider mock --yes`) fixes a real bug
in `sample_project/shop/pricing.py`. Run this script afterwards to put the bug
back so you can watch the agent find it again.
"""

from __future__ import annotations

import sys
from pathlib import Path

PRICING = Path(__file__).resolve().parent / "sample_project" / "shop" / "pricing.py"

BROKEN = "    return price - price * percent_off\n"
FIXED = "    return price - price * (percent_off / 100)\n"


def main() -> int:
    if not PRICING.is_file():
        print(f"Could not find {PRICING}", file=sys.stderr)
        return 1

    text = PRICING.read_text(encoding="utf-8")
    if BROKEN in text:
        print("The intentional bug is already in place.")
        return 0
    if FIXED not in text:
        print(
            "Could not find the expected line in pricing.py; edit it by hand to restore the bug.",
            file=sys.stderr,
        )
        return 1

    PRICING.write_text(text.replace(FIXED, BROKEN), encoding="utf-8")
    print(f"Restored the intentional bug in {PRICING}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
