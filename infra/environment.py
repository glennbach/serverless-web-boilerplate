"""One Environment of the Project (dev, QA, or prod): its site, sign-in, and API in the home region.

See docs/plans/2026-11-23-platform.md, docs/plans/2026-11-22-dev-environment.md, and ADRs 0001-0003.
"""

import json
import re

import jsii
from aws_cdk import CfnOutput, Duration, Environment, RemovalPolicy, Stack, Stage
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

from edge import EDGE_REGION, EdgeStack

#: Every resource of this stack is created here (ADR 0001, Decision 10).
HOME_REGION = "us-west-2"

#: A valid ``projectName``: lowercase letters, digits, and hyphens, starting with a letter and
#: not ending with a hyphen (ADR 0003).
PROJECT_NAME = re.compile(r"[a-z]([a-z0-9-]*[a-z0-9])?")

#: The longest ``projectName``: ``<name>-prod`` must fit Cognito's 63-character domain prefix.
MAX_PROJECT_NAME = 58

#: Words Cognito refuses anywhere in a Hosted UI domain prefix.
RESERVED_WORDS = ("aws", "amazon", "cognito")

#: The Environments of a Project, in promotion order.
ENVIRONMENTS = ("dev", "qa", "prod")

#: How long each Environment keeps its CloudWatch logs (ADR 0001, open question 3).
LOG_RETENTION = {
    "dev": logs.RetentionDays.ONE_MONTH,
    "qa": logs.RetentionDays.ONE_MONTH,
    "prod": logs.RetentionDays.SIX_MONTHS,
}


def checked_project_name(project_name: object) -> str:
    """Check a ``projectName`` against the rule in ADR 0003.

    Args:
        project_name: The ``projectName`` context value, unchecked.

    Raises:
        ValueError: ``project_name`` is missing or would not make a valid Hosted UI prefix.

    Returns:
        ``project_name``, unchanged.
    """
    if not isinstance(project_name, str):
        raise ValueError("projectName is not set in infra/cdk.json")
    if not PROJECT_NAME.fullmatch(project_name):
        raise ValueError(
            f"projectName {project_name!r} must be lowercase letters, digits, and hyphens, "
            "start with a letter, and not end with a hyphen"
        )
    if len(project_name) > MAX_PROJECT_NAME:
        raise ValueError(f"projectName {project_name!r} is longer than {MAX_PROJECT_NAME} characters")
    for word in RESERVED_WORDS:
        if word in project_name:
            raise ValueError(f"projectName {project_name!r} contains {word!r}, which Cognito refuses in a prefix")
    return project_name


def environment_name(project_name: object, environment: str) -> str:
    """The name of one Environment of a Project: its stack name and its Hosted UI prefix (ADR 0003).

    Args:
        project_name: The ``projectName`` context value, unchecked.
        environment: ``dev``, ``qa``, or ``prod``.

    Raises:
        ValueError: ``project_name`` is invalid, or ``environment`` is not one of ``ENVIRONMENTS``.

    Returns:
        ``<project_name>-<environment>``.
    """
    if environment not in ENVIRONMENTS:
        raise ValueError(f"environment {environment!r} is not one of {', '.join(ENVIRONMENTS)}")
    return f"{checked_project_name(project_name)}-{environment}"


#: One JSON object per API request. ``integrationRequestId`` is the Lambda
#: request id, which joins an access-log entry to Lambda logs and X-Ray.
#: Never add the email or the token.
ACCESS_LOG_FIELDS = {
    "requestId": "$context.requestId",
    "integrationRequestId": "$context.integration.requestId",
    "ip": "$context.identity.sourceIp",
    "requestTime": "$context.requestTime",
    "routeKey": "$context.routeKey",
    "path": "$context.path",
    "status": "$context.status",
    "responseLength": "$context.responseLength",
    "responseLatency": "$context.responseLatency",
    "integrationStatus": "$context.integrationStatus",
    "integrationError": "$context.integrationErrorMessage",
    "authorizerError": "$context.authorizer.error",
}


@jsii.implements(apigwv2.IAccessLogSettings)
class _AccessLogSettings:
    """Access logging for an ``HttpStage``: ``ACCESS_LOG_FIELDS`` as JSON, to one destination.

    ``IAccessLogSettings`` is a jsii interface, not a struct, so Python needs a
    class that implements it.

    Args:
        destination: Where API Gateway writes the access log.
    """

    def __init__(self, destination: apigwv2.IAccessLogDestination) -> None:
        #: Where API Gateway writes the access log.
        self._destination = destination

    @property
    def destination(self) -> apigwv2.IAccessLogDestination:
        """Where API Gateway writes the access log.

        Returns:
            The destination given to the constructor.
        """
        return self._destination

    @property
    def format(self) -> apigw.AccessLogFormat:
        """One JSON object per request, with the keys of ``ACCESS_LOG_FIELDS``.

        Returns:
            The custom access-log format.
        """
        return apigw.AccessLogFormat.custom(json.dumps(ACCESS_LOG_FIELDS))


class EnvironmentStack(Stack):
    """The site, sign-in, and API of one Environment, in the home region.

    The SPA is served from a private S3 bucket through CloudFront on its
    ``*.cloudfront.net`` URL. Prod keeps its User Pool and log groups if the
    stack is deleted; dev and QA delete them with the stack.

    Args:
        scope: The parent construct.
        construct_id: The construct id, and the stack name unless ``stack_name`` is given.

    Keyword Args:
        environment: ``dev``, ``qa``, or ``prod``.
        api_dir: The directory holding the API's ``Dockerfile``.
        web_dist: The directory holding the built SPA (``npm run build``).
        cognito_domain_prefix: The Hosted UI prefix domain.
        web_acl_arn: The ARN of the WAF web ACL in front of the distribution, if any.
        **kwargs: Passed to ``Stack``, for example ``env``.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment: str,
        api_dir: str,
        web_dist: str,
        cognito_domain_prefix: str,
        web_acl_arn: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        keep = environment == "prod"
        removal = RemovalPolicy.RETAIN if keep else RemovalPolicy.DESTROY
        retention = LOG_RETENTION[environment]

        #: The private bucket that holds the SPA.
        self.bucket = s3.Bucket(
            self,
            "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        #: The CloudFront distribution that serves the SPA.
        self.distribution = cloudfront.Distribution(
            self,
            "Cdn",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            web_acl_id=web_acl_arn,
        )
        #: The site origin, ``https://<distribution>.cloudfront.net``, with no trailing slash.
        self.site_url = f"https://{self.distribution.distribution_domain_name}"

        # Sign-in alias, case sensitivity, and the email attribute's required/mutable flags are
        # fixed at pool creation; changing them means a new pool.
        #: The Environment's User Pool. Email is the username and is on the ID token.
        self.user_pool = cognito.UserPool(
            self,
            "Users",
            sign_in_aliases=cognito.SignInAliases(email=True),
            sign_in_case_sensitive=False,
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True)
            ),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            self_sign_up_enabled=False,
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            mfa=cognito.Mfa.OFF,
            feature_plan=cognito.FeaturePlan.LITE,
            deletion_protection=keep,
            removal_policy=removal,
        )
        #: The Hosted UI prefix domain, ``https://<prefix>.auth.us-west-2.amazoncognito.com``.
        self.user_pool_domain = self.user_pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=cognito_domain_prefix),
            managed_login_version=cognito.ManagedLoginVersion.CLASSIC_HOSTED_UI,
        )
        #: The SPA's public client: authorization-code grant, PKCE in the browser, no secret.
        self.user_pool_client = self.user_pool.add_client(
            "Spa",
            generate_secret=False,
            prevent_user_existence_errors=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
                callback_urls=[self.site_url + "/"],
                logout_urls=[self.site_url + "/"],
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
        )

        #: The Go API image on Lambda, reading the user from the authorizer's claims.
        self.function = lambda_.DockerImageFunction(
            self,
            "Api",
            code=lambda_.DockerImageCode.from_image_asset(api_dir, platform=ecr_assets.Platform.LINUX_ARM64),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=256,
            timeout=Duration.seconds(10),
            environment={"AUTH_MODE": "aws"},
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(
                self, "ApiLogs", retention=retention, removal_policy=removal
            ),
        )
        #: The HTTP API. It answers CORS preflights itself; Go sets no CORS headers.
        self.api = apigwv2.HttpApi(
            self,
            "HttpApi",
            create_default_stage=False,
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=[self.site_url],
                allow_methods=[apigwv2.CorsHttpMethod.GET],
                allow_headers=["authorization"],
                max_age=Duration.hours(1),
            ),
        )
        self.api.add_routes(
            path="/api/me",
            methods=[apigwv2.HttpMethod.GET],
            integration=integrations.HttpLambdaIntegration("Me", self.function),
            authorizer=authorizers.HttpUserPoolAuthorizer(
                "Cognito", self.user_pool, user_pool_clients=[self.user_pool_client]
            ),
        )
        #: The API's access log group.
        self.access_logs = logs.LogGroup(
            self, "ApiAccessLogs", retention=retention, removal_policy=removal
        )
        # Only HttpStage takes access_log_settings, so the $default stage is explicit.
        apigwv2.HttpStage(
            self,
            "DefaultStage",
            http_api=self.api,
            auto_deploy=True,
            access_log_settings=_AccessLogSettings(apigwv2.LogGroupLogDestination(self.access_logs)),
        )

        # Two deployments to one bucket, both prune=False so neither deletes the
        # other's files. The local web/dist/config.json (authMode dev) is in neither.
        # They share one handler Lambda, so they share its log group too.
        deploy_logs = logs.LogGroup(
            self, "SpaDeployLogs", retention=retention, removal_policy=removal
        )
        assets = s3deploy.BucketDeployment(
            self,
            "SpaAssets",
            sources=[s3deploy.Source.asset(web_dist, exclude=["index.html", "config.json"])],
            log_group=deploy_logs,
            destination_bucket=self.bucket,
            prune=False,
            cache_control=[
                s3deploy.CacheControl.set_public(),
                s3deploy.CacheControl.max_age(Duration.days(365)),
                s3deploy.CacheControl.immutable(),
            ],
        )
        entry = s3deploy.BucketDeployment(
            self,
            "SpaEntry",
            sources=[
                s3deploy.Source.asset(web_dist, exclude=["*", "!index.html"]),
                s3deploy.Source.json_data(
                    "config.json",
                    {
                        "authMode": "cognito",
                        "apiBaseUrl": self.api.api_endpoint,
                        "cognitoDomainUrl": self.user_pool_domain.base_url(),
                        "clientId": self.user_pool_client.user_pool_client_id,
                    },
                ),
            ],
            log_group=deploy_logs,
            destination_bucket=self.bucket,
            prune=False,
            cache_control=[s3deploy.CacheControl.no_cache()],
        )
        # A new index.html never points at hashed assets that are not uploaded yet.
        entry.node.add_dependency(assets)

        #: The ``SiteUrl`` output, read by the pipeline's smoke test.
        self.site_url_output = CfnOutput(self, "SiteUrl", value=self.site_url)
        #: The ``ApiUrl`` output, read by the pipeline's smoke test.
        self.api_url_output = CfnOutput(self, "ApiUrl", value=self.api.api_endpoint)
        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=self.user_pool_client.user_pool_client_id)
        CfnOutput(self, "CognitoDomainUrl", value=self.user_pool_domain.base_url())
        CfnOutput(self, "ApiAccessLogGroup", value=self.access_logs.log_group_name)
        CfnOutput(self, "ApiFunctionLogGroup", value=self.function.log_group.log_group_name)
        CfnOutput(self, "ApiFunctionName", value=self.function.function_name)


class EnvironmentStage(Stage):
    """One Environment: its web ACL in ``us-east-1`` and everything else in the home region.

    The two stacks are joined by CDK cross-region references, so the
    distribution takes the web ACL's ARN without a hand-copied value.

    Args:
        scope: The parent construct: the pipeline stack, or an ``App`` in tests.
        construct_id: The stage id, for example ``Dev``; also the pipeline stage's name.

    Keyword Args:
        project_name: The ``projectName`` context value, unchecked.
        environment: ``dev``, ``qa``, or ``prod``.
        account: The AWS account both stacks deploy to, or ``None`` for the CLI's default.
        api_dir: The directory holding the API's ``Dockerfile``.
        web_dist: The directory holding the built SPA (``npm run build``).

    Raises:
        ValueError: ``project_name`` is invalid, or ``environment`` is unknown.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project_name: object,
        environment: str,
        account: str | None,
        api_dir: str,
        web_dist: str,
    ) -> None:
        name = environment_name(project_name, environment)
        super().__init__(scope, construct_id)
        #: ``dev``, ``qa``, or ``prod``.
        self.environment = environment
        #: The web ACL stack, ``<name>-edge``, in ``us-east-1``.
        self.edge_stack = EdgeStack(
            self,
            "Edge",
            stack_name=f"{name}-edge",
            env=Environment(account=account, region=EDGE_REGION),
            cross_region_references=True,
        )
        #: The site, sign-in, and API stack, ``<name>``, in the home region.
        self.environment_stack = EnvironmentStack(
            self,
            "Site",
            stack_name=name,
            env=Environment(account=account, region=HOME_REGION),
            cross_region_references=True,
            environment=environment,
            api_dir=api_dir,
            web_dist=web_dist,
            cognito_domain_prefix=name,
            web_acl_arn=self.edge_stack.web_acl_arn,
        )
