"""Regenerate the HTTP contract without connecting to a database."""
import json
from pathlib import Path

from loom.api import app

Path('docs/openapi.json').write_text(json.dumps(app.openapi(), indent=2) + '\n')
