# experiment package

import os
from pathlib import Path

# The SDK only reads a config file named explicitly (v0.3+); research
# scripts opt in to the repo's config.yaml here, before touching the SDK.
os.environ.setdefault("RMIC_CONFIG", str(Path(__file__).resolve().parents[1] / "config.yaml"))
