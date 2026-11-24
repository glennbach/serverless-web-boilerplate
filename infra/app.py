"""CDK entry point: the dev Environment, deployed by hand with ``cdk deploy`` (the pipeline replaces this)."""

import os
from pathlib import Path

from aws_cdk import App

from environment import EnvironmentStage

#: The repository root, which holds ``api/`` and ``web/``.
REPO = Path(__file__).resolve().parent.parent

#: The CDK app; ``cdk`` synthesizes it by running this file.
app = App()
EnvironmentStage(
    app,
    "Dev",
    project_name=app.node.try_get_context("projectName"),
    environment="dev",
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    api_dir=str(REPO / "api"),
    web_dist=str(REPO / "web" / "dist"),
)
app.synth()
