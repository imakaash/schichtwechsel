"""Entry point for Streamlit Community Cloud.

Its own folder, so Community Cloud installs the lean requirements.txt next
to it rather than the conda environment.yml at the repository root.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from schichtwechsel.ui.app import main  # noqa: E402

main()
