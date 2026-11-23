"""CDK entry point: the phase 2a dev environment, deployed by hand with ``cdk deploy``."""

import os
from pathlib import Path

from aws_cdk import App, Environment

from proof_dev import HOME_REGION, ProofDevStack

#: The repository root, which holds ``api/`` and ``web/``.
REPO = Path(__file__).resolve().parent.parent

#: The CDK app; ``cdk`` synthesizes it by running this file.
app = App()
ProofDevStack(
    app,
    "ProofDev",
    env=Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=HOME_REGION),
    api_dir=str(REPO / "api"),
    web_dist=str(REPO / "web" / "dist"),
    cognito_domain_prefix=app.node.get_context("cognitoDomainPrefix"),
)
app.synth()
