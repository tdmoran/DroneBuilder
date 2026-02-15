#!/usr/bin/env python3
"""DroneBuilder CLI entry point.

Usage:
    python3 dronebuilder.py list motor
    python3 dronebuilder.py check <id1> <id2>
    python3 dronebuilder.py validate builds/example_5inch.json
    python3 dronebuilder.py calc builds/example_5inch.json
    python3 dronebuilder.py suggest --class 5inch --budget 300
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so that core/engines/cli imports work.
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from cli.main import main

if __name__ == "__main__":
    main()
