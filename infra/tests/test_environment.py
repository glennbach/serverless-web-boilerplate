import json
from pathlib import Path

import pytest
from aws_cdk.assertions import Capture, Match, Template

from conftest import INFRA, _app
from environment import environment_name, environment_stack


@pytest.fixture
def built(tmp_path, dist):
    """The dev stack, its template, and the cloud assembly directory."""
    app = _app(tmp_path)
    stack = environment_stack(app, "dev", api_dir=str(INFRA.parent / "api"), web_dist=str(dist))
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
    t.has_resource_properties("AWS::Cognito::UserPoolDomain", {"Domain": "swb-proof-dev", "ManagedLoginVersion": 1})


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
    stack, _, outdir = built
    images = json.loads((outdir / f"{stack.artifact_id}.assets.json").read_text())["dockerImages"]
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


def _deployments(t):
    return t.find_resources("Custom::CDKBucketDeployment").values()


def test_entry_files_are_no_cache(built):
    _, t, _ = built
    caches = sorted(d["Properties"]["SystemMetadata"]["cache-control"] for d in _deployments(t))
    assert caches == ["no-cache", "public, max-age=31536000, immutable"]
    assert all(d["Properties"]["Prune"] is False for d in _deployments(t))


def test_config_json_is_built_from_stack_values(built):
    stack, t, outdir = built
    (markers,) = [m for d in _deployments(t) for m in d["Properties"].get("SourceMarkers", []) if m]
    (staged,) = outdir.glob("asset.*/config.json")
    config = json.loads(staged.read_text())

    def fill(value):
        """Replace each deploy-time marker with the CloudFormation value it stands for."""
        for marker, cfn in markers.items():
            value = value.replace(marker, json.dumps(cfn))
        return value

    filled = {k: fill(v) for k, v in config.items()}
    domain_ref = json.dumps(stack.resolve(stack.user_pool_domain.domain_name))
    assert filled == {
        "authMode": "cognito",
        "apiBaseUrl": json.dumps(stack.resolve(stack.api.api_endpoint)),
        "cognitoDomainUrl": f"https://{domain_ref}.auth.us-west-2.amazoncognito.com",
        "clientId": json.dumps(stack.resolve(stack.user_pool_client.user_pool_client_id)),
    }


def test_dev_config_is_never_uploaded(built):
    _, _, outdir = built
    staged = [p.read_text() for p in outdir.glob("asset.*/config.json")]
    assert len(staged) == 1 and '"cognito"' in staged[0] and '"dev"' not in staged[0]


def test_outputs(built):
    _, t, _ = built
    for name in (
        "SiteUrl", "ApiUrl", "UserPoolId", "UserPoolClientId", "CognitoDomainUrl",
        "ApiAccessLogGroup", "ApiFunctionLogGroup", "ApiFunctionName",
    ):
        t.has_output(name, {})


def test_sign_in_is_case_insensitive(built):
    _, t, _ = built
    t.has_resource_properties("AWS::Cognito::UserPool", {"UsernameConfiguration": {"CaseSensitive": False}})


def test_client_hides_whether_a_user_exists(built):
    _, t, _ = built
    t.has_resource_properties("AWS::Cognito::UserPoolClient", {"PreventUserExistenceErrors": "ENABLED"})


def test_each_deployment_uploads_the_right_files(built):
    _, t, outdir = built

    def files(deployment):
        """The files a deployment uploads: its staged assets, keyed by ``<hash>.zip``."""
        dirs = [outdir / f"asset.{key.removesuffix('.zip')}" for key in deployment["Properties"]["SourceObjectKeys"]]
        return {p.relative_to(d).as_posix() for d in dirs for p in d.rglob("*") if p.is_file()}

    by_cache = {d["Properties"]["SystemMetadata"]["cache-control"]: files(d) for d in _deployments(t)}
    assert by_cache["no-cache"] == {"index.html", "config.json"}
    assert by_cache["public, max-age=31536000, immutable"] == {"assets/app-abc123.js"}


@pytest.mark.parametrize("env, days, policy, protection", [
    ("dev", 30, "Delete", "INACTIVE"), ("qa", 30, "Delete", "INACTIVE"), ("prod", 180, "Retain", "ACTIVE"),
])
def test_retention_and_removal_by_environment(tmp_path, dist, env, days, policy, protection):
    t = Template.from_stack(environment_stack(_app(tmp_path), env, api_dir=str(INFRA.parent / "api"), web_dist=str(dist)))
    groups = t.find_resources("AWS::Logs::LogGroup")
    assert groups
    for name, group in groups.items():
        assert group["Properties"]["RetentionInDays"] == days, name
        assert group["DeletionPolicy"] == policy, name
    t.has_resource("AWS::Cognito::UserPool", {"DeletionPolicy": policy, "UpdateReplacePolicy": policy,
                                              "Properties": Match.object_like({"DeletionProtection": protection})})


#: The logical ids swb-proof-dev was deployed with (synthesized 2026-11-23 at 787ad6c).
DEPLOYED_DEV_IDS = {
    "AWS::Cognito::UserPool": "Users0A0EEA89",
    "AWS::Cognito::UserPoolDomain": "UsersDomainC6632324",
    "AWS::Cognito::UserPoolClient": "UsersSpa85E8690B",
    "AWS::S3::Bucket": "SiteE53D7754",
    "AWS::CloudFront::Distribution": "Cdn9963B1AD",
    "AWS::ApiGatewayV2::Api": "HttpApiF5A9A8A7",
}


def test_dev_keeps_its_hand_deployed_logical_ids(built):
    stack, t, _ = built
    assert stack.stack_name == "swb-proof-dev"
    for type_, logical_id in DEPLOYED_DEV_IDS.items():
        assert set(t.find_resources(type_)) == {logical_id}


def test_checked_in_project_name_names_the_dev_stack(built):
    stack, _, _ = built
    context = json.loads((INFRA / "cdk.json").read_text())["context"]
    assert context["projectName"] == "swb-proof" and "cognitoDomainPrefix" not in context
    assert stack.stack_name == "swb-proof-dev"


def test_another_project_name_renames_stack_and_prefix(tmp_path, dist):
    stack = environment_stack(_app(tmp_path, projectName="acme-shop"), "dev", api_dir=str(INFRA.parent / "api"), web_dist=str(dist))
    assert stack.stack_name == "acme-shop-dev"
    Template.from_stack(stack).has_resource_properties("AWS::Cognito::UserPoolDomain", {"Domain": "acme-shop-dev"})


@pytest.mark.parametrize("name", ["a", "swb-proof", "a1-b2", "a" * 58])
def test_valid_project_names(name):
    assert environment_name(name, "prod") == f"{name}-prod"


@pytest.mark.parametrize(
    "name, rule",
    [
        (None, "projectName"), ("", "projectName"), ("MyApp", "lowercase"), ("my_app", "lowercase"),
        ("1app", "lowercase"), ("app-", "lowercase"), ("a" * 59, "58"),
        ("laws-firm", "contains 'aws'"), ("amazonia", "contains 'amazon'"), ("cognito-x", "contains 'cognito'"),
    ],
)
def test_invalid_project_names_fail_at_synth(tmp_path, dist, name, rule):
    # Through environment_stack, as app.py runs it; None means projectName is absent from the context.
    with pytest.raises(ValueError, match=rule):
        environment_stack(_app(tmp_path, projectName=name), "dev", api_dir=str(INFRA.parent / "api"), web_dist=str(dist))


def test_unknown_environment_fails():
    with pytest.raises(ValueError, match="staging"):
        environment_name("swb-proof", "staging")
