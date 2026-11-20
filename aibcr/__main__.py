# -*- coding: utf-8 -*-
"""Cho phép chạy engine bằng ``python -m aibcr --game baccarat``."""

import sys

from aibcr.service.engine import main

if __name__ == "__main__":
    sys.exit(main())
