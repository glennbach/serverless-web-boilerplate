"""The Project's delivery pipeline: a push to ``build`` deploys QA, then prod after approval.

Deploy with ``git push origin master:build``. A push to ``master`` alone deploys nothing.

See docs/plans/2026-11-23-platform.md and ADR 0001, Decisions 3 and 4.
"""

import os
import re

from aws_cdk import App, Environment, Stack
from aws_cdk import pipelines
from constructs import Construct

from environment import ENVIRONMENTS, HOME_REGION, EnvironmentStage, checked_project_name

#: The branch whose pushes start the pipeline. Only fast-forward it from master.
BRANCH = "build"

#: A GitHub repository, ``owner/name``.
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

#: An AWS CodeConnections (formerly CodeStar Connections) connection ARN.
CONNECTION_ARN = re.compile(r"arn:aws:(codeconnections|codestar-connections):[a-z0-9-]+:\d{12}:connection/[0-9a-f-]+")


class PipelineStack(Stack):
    """A self-updating CDK pipeline that deploys one Environment stage per environment.

    One synth step tests everything and builds the SPA once; every stage then
    deploys the same published assets. Prod waits for a manual approval.

    Args:
        scope: The parent construct, normally the CDK ``App``.
        construct_id: The stack name, which is also the pipeline's name.

    Keyword Args:
        project_name: The checked ``projectName``.
        repository: The GitHub repository, ``owner/name``.
        connection_arn: The CodeConnections connection that can read ``repository``.
        account: The AWS account every Environment deploys to.
        api_dir: The directory holding the API's ``Dockerfile``.
        web_dist: The directory holding the built SPA (``npm run build``).
        **kwargs: Passed to ``Stack``, for example ``env``.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project_name: str,
        repository: str,
        connection_arn: str,
        account: str | None,
        api_dir: str,
        web_dist: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        pipeline = pipelines.CodePipeline(
            self,
            "Pipeline",
            pipeline_name=construct_id,
            synth=pipelines.ShellStep(
                "Synth",
                input=pipelines.CodePipelineSource.connection(repository, BRANCH, connection_arn=connection_arn),
                env={"GOTOOLCHAIN": "auto"},
                install_commands=["n 26", "pip3 install uv==0.13.9", "npm install -g aws-cdk@2.1149.0"],
                commands=[
                    "(cd api && go vet ./... && go test ./...)",
                    "(cd web && npm ci && npm test && npm run build)",
                    "(cd infra && uv run pytest -q && cdk synth)",
                ],
                primary_output_directory="infra/cdk.out",
            ),
        )
        #: Each Environment's stage, keyed by environment.
        self.stages: dict[str, EnvironmentStage] = {}
        for environment in ENVIRONMENTS:
            stage = EnvironmentStage(
                self,
                environment.capitalize(),
                project_name=project_name,
                environment=environment,
                account=account,
                api_dir=api_dir,
                web_dist=web_dist,
            )
            approval = pipelines.ManualApprovalStep(
                "PromoteToProd", comment="QA passed? Approving deploys this commit to prod."
            )
            smoke = pipelines.ShellStep(
                "Smoke",
                env_from_cfn_outputs={
                    "SITE_URL": stage.environment_stack.site_url_output,
                    "API_URL": stage.environment_stack.api_url_output,
                },
                commands=[
                    """curl -sf "$SITE_URL/config.json" | grep -q '"cognito"'""",
                    """test "$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/me")" = 401""",
                ],
            )
            pipeline.add_stage(stage, pre=[approval] if environment == "prod" else [], post=[smoke])
            self.stages[environment] = stage


def _setting(app: App, key: str, pattern: re.Pattern) -> str:
    """Read one pipeline setting from the context and check it.

    Args:
        app: The CDK app.
        key: The context key in ``infra/cdk.json``.
        pattern: What the whole value must match.

    Raises:
        ValueError: The value is missing or does not match ``pattern``; the message names ``key``.

    Returns:
        The value.
    """
    value = app.node.try_get_context(key)
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{key} in infra/cdk.json is {value!r}; set it before synthesizing the pipeline")
    return value


def pipeline_stack(app: App, *, api_dir: str, web_dist: str) -> PipelineStack:
    """Add the Project's pipeline to ``app``, configured from its context values.

    Side Effects:
        Adds the pipeline stack, and through it every Environment stage, to ``app``'s construct tree.

    Args:
        app: The CDK app. ``cdk.json`` supplies ``projectName``, ``repository``, and ``connectionArn``.

    Keyword Args:
        api_dir: The directory holding the API's ``Dockerfile``.
        web_dist: The directory holding the built SPA (``npm run build``).

    Raises:
        ValueError: A context value is missing or invalid.

    Returns:
        The stack, named ``<projectName>-pipeline``.
    """
    project_name = checked_project_name(app.node.try_get_context("projectName"))
    account = os.environ.get("CDK_DEFAULT_ACCOUNT")
    return PipelineStack(
        app,
        f"{project_name}-pipeline",
        env=Environment(account=account, region=HOME_REGION),
        project_name=project_name,
        repository=_setting(app, "repository", REPOSITORY),
        connection_arn=_setting(app, "connectionArn", CONNECTION_ARN),
        account=account,
        api_dir=api_dir,
        web_dist=web_dist,
    )
