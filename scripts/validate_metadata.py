#!/usr/bin/env python3
"""Compatibility entry point for the current-root metadata/source validator.

The original 0.6.1-oriented script remains preserved in Git history and in
both frozen engine trees of the R1 ESM. Current main uses the read-only
validator below; this entry point does not overwrite historical validation.
"""
from check_current_release import main

if __name__ == "__main__":
    raise SystemExit(main())
