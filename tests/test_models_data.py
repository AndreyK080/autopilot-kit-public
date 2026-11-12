import json
from pathlib import Path

MODELS = Path(__file__).resolve().parent.parent / "kit" / "data" / "models.json"


def test_models_table_shape():
    data = json.loads(MODELS.read_text(encoding="utf-8"))
    for vendor in ("claude", "codex", "claude-gate"):
        assert set(data[vendor]["tiers"]) == {"strong", "balanced", "fast"}
        assert data[vendor]["efforts"]
