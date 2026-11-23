import json
from pathlib import Path

import pytest
from aws_cdk import App, Environment
from aws_cdk.assertions import Capture, Match, Template

from proof_dev import HOME_REGION, ProofDevStack

INFRA = Path(__file__).resolve().parent.parent


@pytest.fixture
def built(tmp_path):
    """The stack, its template, and the cloud assembly directory, from a fake web/dist."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><script src=/assets/app-abc123.js></script>")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)")
    (dist / "config.json").write_text('{"authMode": "dev", "apiBaseUrl": ""}')
    # The same feature flags `cdk deploy` uses.
    context = json.loads((INFRA / "cdk.json").read_text())["context"]
    app = App(outdir=str(tmp_path / "cdk.out"), context=context)
    stack = ProofDevStack(
        app,
        "ProofDev",
        env=Environment(region=HOME_REGION),
        api_dir=str(INFRA.parent / "api"),
        web_dist=str(dist),
        cognito_domain_prefix="test-prefix",
    )
    template = Template.from_stack(stack)
    return stack, template, Path(app.synth().directory)


def test_nothing_outside_home_region(built):
    stack, template, _ = built
    assert stack.region == "us-west-2"
    assert "us-east-1" not in json.dumps(template.to_json())


def test_site_bucket_is_private_behind_oac(built):
    _, t, _ = built
    t.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )
    t.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)
    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "DefaultRootObject": "index.html",
                    "DefaultCacheBehavior": Match.object_like({"ViewerProtocolPolicy": "redirect-to-https"}),
                }
            )
        },
    )


def test_pool_schema(built):
    _, t, _ = built
    t.has_resource_properties(
        "AWS::Cognito::UserPool",
        {
            "UsernameAttributes": ["email"],
            "AutoVerifiedAttributes": ["email"],
            "Schema": Match.array_with([Match.object_like({"Name": "email", "Required": True, "Mutable": True})]),
            "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
            "UserPoolTier": "LITE",
        },
    )


def test_prefix_domain_classic_hosted_ui(built):
    _, t, _ = built
    t.has_resource_properties("AWS::Cognito::UserPoolDomain", {"Domain": "test-prefix", "ManagedLoginVersion": 1})


def test_client_is_public_pkce_with_site_callback(built):
    stack, t, _ = built
    site = stack.resolve(stack.site_url + "/")
    t.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "GenerateSecret": False,
            "AllowedOAuthFlowsUserPoolClient": True,
            "AllowedOAuthFlows": ["code"],
            "AllowedOAuthScopes": Match.array_equals(["openid", "email"]),
            "SupportedIdentityProviders": ["COGNITO"],
            "CallbackURLs": [site],
            "LogoutURLs": [site],
            "ReadAttributes": Match.absent(),
        },
    )


def test_function_runs_image_in_aws_mode_with_tracing(built):
    _, t, _ = built
    t.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "PackageType": "Image",
            "Architectures": ["arm64"],
            "Environment": {"Variables": {"AUTH_MODE": "aws"}},
            "TracingConfig": {"Mode": "Active"},
        },
    )


def test_function_image_is_arm64(built):
    _, _, outdir = built
    images = json.loads((outdir / "ProofDev.assets.json").read_text())["dockerImages"]
    assert [i["source"]["platform"] for i in images.values()] == ["linux/arm64"]


def test_api_cors_and_single_route(built):
    stack, t, _ = built
    t.has_resource_properties(
        "AWS::ApiGatewayV2::Api",
        {
            "ProtocolType": "HTTP",
            "CorsConfiguration": {
                "AllowOrigins": [stack.resolve(stack.site_url)],
                "AllowMethods": ["GET"],
                "AllowHeaders": ["authorization"],
                "MaxAge": 3600,
            },
        },
    )
    t.resource_count_is("AWS::ApiGatewayV2::Route", 1)
    t.has_resource_properties("AWS::ApiGatewayV2::Route", {"RouteKey": "GET /api/me", "AuthorizationType": "JWT"})


def test_jwt_authorizer_accepts_the_spa_client(built):
    stack, t, _ = built
    t.has_resource_properties(
        "AWS::ApiGatewayV2::Authorizer",
        {
            "AuthorizerType": "JWT",
            "IdentitySource": ["$request.header.Authorization"],
            "JwtConfiguration": Match.object_like(
                {"Audience": [stack.resolve(stack.user_pool_client.user_pool_client_id)]}
            ),
        },
    )


def test_default_stage_writes_json_access_logs(built):
    _, t, _ = built
    fmt = Capture()
    t.has_resource_properties(
        "AWS::ApiGatewayV2::Stage",
        {
            "StageName": "$default",
            "AutoDeploy": True,
            "AccessLogSettings": {"DestinationArn": Match.any_value(), "Format": fmt},
        },
    )
    entry = json.loads(fmt.as_string())
    assert entry["integrationRequestId"] == "$context.integration.requestId"
    assert entry["authorizerError"] == "$context.authorizer.error"
    assert set(entry) == {
        "requestId", "integrationRequestId", "ip", "requestTime", "routeKey", "path",
        "status", "responseLength", "responseLatency", "integrationStatus", "integrationError", "authorizerError",
    }
    t.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 30})
