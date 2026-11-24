"""CDK entry point: the Project's pipeline, which deploys every Environment."""

from pathlib import Path

from aws_cdk import App

from pipeline import pipeline_stack

#: The repository root, which holds ``api/`` and ``web/``.
REPO = Path(__file__).resolve().parent.parent

#: The CDK app; ``cdk`` synthesizes it by running this file.
app = App()
pipeline_stack(app, api_dir=str(REPO / "api"), web_dist=str(REPO / "web" / "dist"))
app.synth()
