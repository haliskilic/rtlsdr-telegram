#!/usr/bin/env python3
"""Giriş noktası: python3 run.py [-c config.yaml]"""
import sys
from rtlsdr_telegram.app import main
if __name__ == "__main__":
    sys.exit(main())
