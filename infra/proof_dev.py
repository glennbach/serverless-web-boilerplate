"""The phase 2a dev environment: one stack in the home region.

See docs/plans/2026-11-22-dev-environment.md and ADR 0001 / ADR 0002.
"""

import json

import jsii
from aws_cdk import Duration, RemovalPolicy, Stack
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
from constructs import Construct

#: Every resource of this stack is created here (ADR 0001, Decision 10).
HOME_REGION = "us-west-2"

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


class ProofDevStack(Stack):
    """The dev site, sign-in, and API for the proof, with nothing in ``us-east-1``.

    The SPA is served from a private S3 bucket through CloudFront on its
    ``*.cloudfront.net`` URL.

    Args:
        scope: The parent construct, normally the CDK ``App``.
        construct_id: The stack name.

    Keyword Args:
        api_dir: The directory holding the API's ``Dockerfile``.
        web_dist: The directory holding the built SPA (``npm run build``).
        cognito_domain_prefix: The Hosted UI prefix domain.
        **kwargs: Passed to ``Stack``, for example ``env``.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        api_dir: str,
        web_dist: str,
        cognito_domain_prefix: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

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
        )
        #: The site origin, ``https://<distribution>.cloudfront.net``, with no trailing slash.
        self.site_url = f"https://{self.distribution.distribution_domain_name}"

        # Sign-in alias and the email attribute's required/mutable flags are
        # fixed at pool creation; changing them means a new pool.
        #: The dev User Pool. Email is the username and is on the ID token.
        self.user_pool = cognito.UserPool(
            self,
            "Users",
            sign_in_aliases=cognito.SignInAliases(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True)
            ),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            self_sign_up_enabled=False,
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            mfa=cognito.Mfa.OFF,
            feature_plan=cognito.FeaturePlan.LITE,
            removal_policy=RemovalPolicy.DESTROY,
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
                self, "ApiLogs", retention=logs.RetentionDays.ONE_MONTH, removal_policy=RemovalPolicy.DESTROY
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
            self, "ApiAccessLogs", retention=logs.RetentionDays.ONE_MONTH, removal_policy=RemovalPolicy.DESTROY
        )
        # Only HttpStage takes access_log_settings, so the $default stage is explicit.
        apigwv2.HttpStage(
            self,
            "DefaultStage",
            http_api=self.api,
            auto_deploy=True,
            access_log_settings=_AccessLogSettings(apigwv2.LogGroupLogDestination(self.access_logs)),
        )
