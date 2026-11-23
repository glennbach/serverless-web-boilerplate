"""CDK entry point: the phase 2a dev environment, deployed by hand with ``cdk deploy``."""

from pathlib import Path

from aws_cdk import App

from proof_dev import dev_stack

#: The repository root, which holds ``api/`` and ``web/``.
REPO = Path(__file__).resolve().parent.parent

#: The CDK app; ``cdk`` synthesizes it by running this file.
app = App()
dev_stack(app, api_dir=str(REPO / "api"), web_dist=str(REPO / "web" / "dist"))
app.synth()
