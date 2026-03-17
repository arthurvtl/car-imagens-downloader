#!/usr/bin/env python3
"""
main.py — Ponto de entrada do pipeline multi-satélite IntegraCar.

Uso:
  python main.py run --csv coords.csv --satellite sentinel --cloud 20 --layer true
  python main.py list-satellites
  python main.py gui
"""

from src.cli.commands import main

if __name__ == "__main__":
    main()
