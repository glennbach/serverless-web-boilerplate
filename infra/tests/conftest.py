import json
from pathlib import Path

import pytest
from aws_cdk import App

INFRA = Path(__file__).resolve().parent.parent


def _app(tmp_path, **context):
    """An App with the ``cdk.json`` context (the feature flags ``cdk deploy`` uses), updated by ``context``.

    A ``None`` value removes that key, so ``projectName=None`` is an app with no project name.
    """
    merged = {**json.loads((INFRA / "cdk.json").read_text())["context"], **context}
    return App(outdir=str(tmp_path / "cdk.out"), context={k: v for k, v in merged.items() if v is not None})


@pytest.fixture
def dist(tmp_path):
    """A fake web/dist."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><script src=/assets/app-abc123.js></script>")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)")
    (dist / "config.json").write_text('{"authMode": "dev", "apiBaseUrl": ""}')
    return dist
