"""One Environment's resources that AWS accepts only in ``us-east-1``: the CloudFront WAF web ACL.

See docs/plans/2026-11-23-platform.md and ADR 0001, Decisions 8 and 10.
"""

from aws_cdk import Stack
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct

#: CloudFront's web ACLs must be created here.
EDGE_REGION = "us-east-1"

#: Requests per 5 minutes from one IP address before WAF blocks it.
RATE_LIMIT = 1000

#: AWS managed rule groups, in priority order after the rate limit. With it, 4 of the Free plan's 5 rules.
MANAGED_RULE_GROUPS = (
    "AWSManagedRulesAmazonIpReputationList",
    "AWSManagedRulesCommonRuleSet",
    "AWSManagedRulesKnownBadInputsRuleSet",
)


def _visibility(metric_name: str) -> wafv2.CfnWebACL.VisibilityConfigProperty:
    """CloudWatch metrics and sampled requests under one metric name.

    Args:
        metric_name: The CloudWatch metric name.

    Returns:
        The visibility configuration.
    """
    return wafv2.CfnWebACL.VisibilityConfigProperty(
        cloud_watch_metrics_enabled=True, sampled_requests_enabled=True, metric_name=metric_name
    )


class EdgeStack(Stack):
    """The web ACL in front of one Environment's CloudFront distribution.

    It stays within the CloudFront flat-rate Free plan: at most 5 rules and no
    customer rule groups.

    Args:
        scope: The parent construct, normally an ``EnvironmentStage``.
        construct_id: The construct id.

    Keyword Args:
        **kwargs: Passed to ``Stack``, for example ``env`` and ``stack_name``.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        rate_limit = wafv2.CfnWebACL.RuleProperty(
            name="RateLimit",
            priority=0,
            statement=wafv2.CfnWebACL.StatementProperty(
                rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                    limit=RATE_LIMIT, aggregate_key_type="IP"
                )
            ),
            action=wafv2.CfnWebACL.RuleActionProperty(block={}),
            visibility_config=_visibility("RateLimit"),
        )
        managed = [
            wafv2.CfnWebACL.RuleProperty(
                name=name,
                priority=priority,
                statement=wafv2.CfnWebACL.StatementProperty(
                    managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                        vendor_name="AWS", name=name
                    )
                ),
                override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                visibility_config=_visibility(name),
            )
            for priority, name in enumerate(MANAGED_RULE_GROUPS, start=1)
        ]
        #: The web ACL; CloudFront takes it by ARN.
        self.web_acl = wafv2.CfnWebACL(
            self,
            "WebAcl",
            scope="CLOUDFRONT",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            rules=[rate_limit, *managed],
            visibility_config=_visibility("WebAcl"),
        )
        #: The web ACL's ARN, read across regions by the Environment's home-region stack.
        self.web_acl_arn = self.web_acl.attr_arn
