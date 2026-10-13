"""Puts the block root on sys.path so `import routing` resolves.

Belt and braces alongside pytest.ini: this file works even when pytest is
invoked from elsewhere, or with a configuration file that does not apply.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
