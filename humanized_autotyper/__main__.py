"""`python -m humanized_autotyper` 等同 `autotyper` 命令。"""
import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
