"""CDK entry point: the dev Environment, deployed by hand with ``cdk deploy``."""

from pathlib import Path

from aws_cdk import App

from environment import environment_stack

#: The repository root, which holds ``api/`` and ``web/``.
REPO = Path(__file__).resolve().parent.parent

#: The CDK app; ``cdk`` synthesizes it by running this file.
app = App()
environment_stack(app, "dev", api_dir=str(REPO / "api"), web_dist=str(REPO / "web" / "dist"))
app.synth()
