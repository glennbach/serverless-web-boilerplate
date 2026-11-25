import json
from pathlib import Path

import pytest
from aws_cdk.assertions import Template

from conftest import INFRA, _app
from environment import ENVIRONMENTS
from pipeline import pipeline_stack

ARN = "arn:aws:codeconnections:us-west-2:111111111111:connection/0a1b2c3d-0000-4000-8000-000000000000"


@pytest.fixture
def pipeline(tmp_path, dist, monkeypatch):
    monkeypatch.setenv("CDK_DEFAULT_ACCOUNT", "111111111111")
    app = _app(tmp_path, repository="example-org/proof", connectionArn=ARN)
    return pipeline_stack(app, api_dir=str(INFRA.parent / "api"), web_dist=str(dist))


def _stages(stack):
    (pipeline,) = Template.from_stack(stack).find_resources("AWS::CodePipeline::Pipeline").values()
    return pipeline["Properties"]["Stages"]


def test_qa_then_approved_prod(pipeline):
    stages = _stages(pipeline)
    names = [s["Name"] for s in stages]
    assert names[-2:] == ["Qa", "Prod"] and "Dev" not in names
    approvals = {s["Name"]: [a for a in s["Actions"] if a["ActionTypeId"]["Category"] == "Approval"] for s in stages}
    assert approvals["Qa"] == [] and len(approvals["Prod"]) == 1
    prod = next(s for s in stages if s["Name"] == "Prod")
    deploys = [a["RunOrder"] for a in prod["Actions"] if a["ActionTypeId"]["Category"] == "Deploy"]
    assert deploys and approvals["Prod"][0]["RunOrder"] < min(deploys)
    for s in stages[-2:]:
        assert any(a["Name"].startswith("Smoke") for a in s["Actions"])


def test_source_is_build_on_github(pipeline):
    source = _stages(pipeline)[0]["Actions"][0]
    assert source["ActionTypeId"]["Provider"] == "CodeStarSourceConnection"
    expected = {"FullRepositoryId": "example-org/proof", "BranchName": "build", "ConnectionArn": ARN}
    assert all(source["Configuration"][k] == v for k, v in expected.items())


def test_only_a_push_to_build_starts_the_pipeline(pipeline):
    # Without explicit Triggers, AWS derives a push filter from the branch the pipeline was created with
    # and may keep it after the source branch changes, so pushes to master would keep starting runs.
    (resource,) = Template.from_stack(pipeline).find_resources("AWS::CodePipeline::Pipeline").values()
    source = resource["Properties"]["Stages"][0]["Actions"][0]
    assert resource["Properties"]["Triggers"] == [{
        "ProviderType": "CodeStarSourceConnection",
        "GitConfiguration": {"SourceActionName": source["Name"], "Push": [{"Branches": {"Includes": ["build"]}}]},
    }]


def test_synth_tests_everything_before_synth(pipeline):
    specs = json.dumps(Template.from_stack(pipeline).find_resources("AWS::CodeBuild::Project"))
    for command in ("go test ./...", "npm test", "npm run build", "uv run pytest -q", "cdk synth"):
        assert command in specs


def test_every_environment_deploys_the_same_assets(pipeline):
    def shared_asset_ids(stage):
        # The image and the SPA files. Left out: the stack's own template, which differs by environment,
        # and the config.json asset, which is per environment by design.
        root = Path(stage.synth().directory)
        manifest = json.loads((root / f"{stage.environment_stack.artifact_id}.assets.json").read_text())
        files = {
            asset_id for asset_id, asset in manifest["files"].items()
            if not asset["source"]["path"].endswith(".template.json")
            and not (root / asset["source"]["path"] / "config.json").exists()
        }
        return files, set(manifest["dockerImages"])

    (files, images), *others = [shared_asset_ids(pipeline.stages[e]) for e in ENVIRONMENTS]
    assert files and len(images) == 1
    assert all(other == (files, images) for other in others)


def test_names(pipeline):
    assert pipeline.stack_name == "swb-proof-pipeline"
    assert {e: s.environment_stack.stack_name for e, s in pipeline.stages.items()} == {
        "qa": "swb-proof-qa", "prod": "swb-proof-prod"}


@pytest.mark.parametrize("key, value", [
    ("repository", ""), ("repository", "no-slash"), ("repository", None),
    ("connectionArn", ""), ("connectionArn", "arn:aws:s3:::bucket"), ("connectionArn", None),
])
def test_bad_pipeline_settings_fail_at_synth(tmp_path, dist, monkeypatch, key, value):
    monkeypatch.setenv("CDK_DEFAULT_ACCOUNT", "111111111111")
    context = {"repository": "example-org/proof", "connectionArn": ARN, key: value}
    with pytest.raises(ValueError, match=key):
        pipeline_stack(_app(tmp_path, **context), api_dir=str(INFRA.parent / "api"), web_dist=str(dist))


def test_api_image_pulls_nothing_from_docker_hub():
    # CodeBuild shares egress IPs, so anonymous Docker Hub pulls hit its per-IP rate limit during Assets.
    dockerfile = (INFRA.parent / "api" / "Dockerfile").read_text()
    images = [line.split()[1] if "--platform" not in line else line.split()[2]
              for line in dockerfile.splitlines() if line.startswith("FROM ")]
    images += [word.removeprefix("--from=") for word in dockerfile.split() if word.startswith("--from=") and "/" in word]
    assert images
    for image in images:
        host = image.split("/")[0] if "/" in image else ""
        assert "." in host, f"{image} has no registry host, so it comes from Docker Hub"
