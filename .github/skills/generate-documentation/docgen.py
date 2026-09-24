#!/usr/bin/env python3
"""Portable entry point. No target modules are imported."""
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    print('{"error":"Python 3.11 or newer is required","exit_code":3}')
    raise SystemExit(3)

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
