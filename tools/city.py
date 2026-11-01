"""City build CLI shim:  python tools/city.py <command> ...  (same as  python -m tools.city ...)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.city.cli import main  # noqa: E402

main()
