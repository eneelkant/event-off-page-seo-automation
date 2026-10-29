"""Publishing rules engine — gates dry-run vs live submit decisions.

Rules are evaluated in order. Live publication never proceeds when dry-run is
requested or when required authorization/credentials/status checks fail.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.settings import Settings, get_settings


@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    severity: str  # info | warn | block
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishingDecision:
    allowed: bool
    dry_run: bool
    authorize_publication: bool
    reasons: list[str] = field(default_factory=list)
    rule_results: list[RuleResult] = field(default_factory=list)
    missing_credentials: list[str] = field(default_factory=list)
    eligible_for_dry_run: bool = True
    eligible_for_live: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "dry_run": self.dry_run,
            "authorize_publication": self.authorize_publication,
            "eligible_for_dry_run": self.eligible_for_dry_run,
            "eligible_for_live": self.eligible_for_live,
            "reasons": self.reasons,
            "missing_credentials": self.missing_credentials,
            "rule_results": [
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": r.severity,
                    "message": r.message,
                    "details": r.details,
                }
                for r in self.rule_results
            ],
        }


def credential_presence(platform: PlatformRecord, environ: dict[str, str] | None = None) -> dict[str, Any]:
    env = environ if environ is not None else dict(os.environ)
    required = list(platform.credentials.env_vars or [])
    optional = list(platform.credentials.optional_env_vars or [])
    present = [name for name in required if bool(str(env.get(name, "")).strip())]
    missing = [name for name in required if name not in present]
    optional_present = [name for name in optional if bool(str(env.get(name, "")).strip())]
    return {
        "platform_id": platform.platform_id,
        "auth_type": platform.credentials.auth_type,
        "required_env_vars": required,
        "optional_env_vars": optional,
        "present": present,
        "missing": missing,
        "optional_present": optional_present,
        "configured": len(missing) == 0 if required else False,
        "required_for_live": platform.credentials.required_for_live,
        # Never include secret values
        "values_redacted": True,
    }


class PublishingRulesEngine:
    """Evaluate whether a submission may proceed (dry-run or live)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def evaluate(
        self,
        event: EventRecord | None,
        platform: PlatformRecord,
        *,
        dry_run: bool | None = None,
        authorize_publication: bool = False,
        environ: dict[str, str] | None = None,
    ) -> PublishingDecision:
        if dry_run is None:
            dry_run = self.settings.dry_run_default

        results: list[RuleResult] = []
        missing_fields: list[str] = []
        if event is not None:
            missing_fields = event.missing_fields_for(platform.required_fields)

        # R1: required event fields
        results.append(
            RuleResult(
                rule_id="required_fields",
                passed=not missing_fields,
                severity="block" if missing_fields else "info",
                message=(
                    "All required event fields present"
                    if not missing_fields
                    else f"Missing required fields: {', '.join(missing_fields)}"
                ),
                details={"missing_fields": missing_fields},
            )
        )

        # R2: platform not BLOCKED
        blocked = platform.automation_status == "BLOCKED"
        results.append(
            RuleResult(
                rule_id="platform_not_blocked",
                passed=not blocked,
                severity="block" if blocked else "info",
                message="Platform is BLOCKED" if blocked else "Platform is not BLOCKED",
                details={"automation_status": platform.automation_status},
            )
        )

        # R3: self-promo restricted communities — dry-run OK, live blocked by policy
        restricted = bool(platform.policy.self_promo_restricted)
        results.append(
            RuleResult(
                rule_id="self_promo_policy",
                passed=True if dry_run or not restricted else False,
                severity="block" if (restricted and not dry_run) else ("warn" if restricted else "info"),
                message=(
                    "Self-promo restricted platform — live submit blocked by policy"
                    if restricted and not dry_run
                    else (
                        "Self-promo restricted; dry-run drafts only"
                        if restricted
                        else "No self-promo restriction"
                    )
                ),
                details={"self_promo_restricted": restricted},
            )
        )

        # R4: dry-run short-circuit — always allowed if fields OK and not blocked
        if dry_run:
            results.append(
                RuleResult(
                    rule_id="dry_run_default",
                    passed=True,
                    severity="info",
                    message="Dry-run mode: no live publication; API/browser publish skipped",
                    details={"dry_run": True},
                )
            )
            hard_fail = [r for r in results if not r.passed and r.severity == "block"]
            # Self-promo doesn't block dry-run
            hard_fail = [r for r in hard_fail if r.rule_id != "self_promo_policy"]
            allowed = not any(r.rule_id in {"required_fields", "platform_not_blocked"} and not r.passed for r in results)
            return PublishingDecision(
                allowed=allowed,
                dry_run=True,
                authorize_publication=False,
                reasons=[r.message for r in results if not r.passed] or ["Dry-run allowed"],
                rule_results=results,
                eligible_for_dry_run=allowed,
                eligible_for_live=False,
            )

        # Live path rules below
        # R5: require explicit authorization
        auth_ok = authorize_publication or not self.settings.require_publication_authorization
        results.append(
            RuleResult(
                rule_id="authorize_publication",
                passed=bool(authorize_publication),
                severity="block" if not authorize_publication else "info",
                message=(
                    "authorize_publication=true provided"
                    if authorize_publication
                    else "Live submit requires authorize_publication=true"
                ),
            )
        )

        # R6: settings require authorization flag
        results.append(
            RuleResult(
                rule_id="settings_require_authorization",
                passed=auth_ok,
                severity="block" if not auth_ok else "info",
                message=(
                    "REQUIRE_PUBLICATION_AUTHORIZATION satisfied"
                    if auth_ok
                    else "Settings require publication authorization"
                ),
                details={
                    "require_publication_authorization": self.settings.require_publication_authorization
                },
            )
        )

        # R7: READY preferred. NEEDS_VERIFICATION may proceed only with explicit
        # authorize_publication (human-approved live test); never silently.
        ready = platform.automation_status == "READY"
        allow_unready = platform.policy.allow_live_without_ready
        human_override = bool(authorize_publication) and platform.automation_status == "NEEDS_VERIFICATION"
        status_ok = ready or allow_unready or human_override
        results.append(
            RuleResult(
                rule_id="automation_status_ready",
                passed=status_ok,
                severity=(
                    "info"
                    if ready
                    else ("warn" if status_ok else "block")
                ),
                message=(
                    "Platform READY for live"
                    if ready
                    else (
                        "Human-approved live test while NEEDS_VERIFICATION (authorize_publication=true)"
                        if human_override
                        else (
                            "Policy allows live without READY"
                            if allow_unready
                            else f"Platform status {platform.automation_status}; live blocked"
                        )
                    )
                ),
                details={"automation_status": platform.automation_status},
            )
        )

        # R8: credentials present when required_for_live
        cred = credential_presence(platform, environ=environ)
        cred_ok = (not platform.credentials.required_for_live) or cred["configured"] or not cred["required_env_vars"]
        # If required_env_vars empty but required_for_live, treat as not configured for API platforms
        if platform.credentials.required_for_live and not platform.credentials.env_vars:
            cred_ok = False
            cred["missing"] = cred.get("missing") or ["<account_credentials_not_env_wired>"]
        results.append(
            RuleResult(
                rule_id="credentials_present",
                passed=cred_ok,
                severity="block" if not cred_ok else "info",
                message=(
                    "Required credentials present"
                    if cred_ok
                    else f"Missing credentials: {', '.join(cred['missing'])}"
                ),
                details={k: v for k, v in cred.items() if k != "values"},
            )
        )

        # R9: approval_required already covered by authorize_publication; record policy
        results.append(
            RuleResult(
                rule_id="platform_approval_policy",
                passed=bool(authorize_publication) if platform.approval_required else True,
                severity="block" if platform.approval_required and not authorize_publication else "info",
                message=(
                    "Platform approval_required satisfied"
                    if (not platform.approval_required or authorize_publication)
                    else "Platform requires approval before publication"
                ),
            )
        )

        # R10: LinkedIn parent is not a submit entry
        if platform.platform_id == "linkedin" and not platform.is_workflow:
            results.append(
                RuleResult(
                    rule_id="linkedin_use_workflow",
                    passed=False,
                    severity="block",
                    message="Submit via a LinkedIn workflow entry (linkedin_*), not the parent platform",
                )
            )
        else:
            results.append(
                RuleResult(
                    rule_id="linkedin_use_workflow",
                    passed=True,
                    severity="info",
                    message="Registry entry is a valid submit target",
                )
            )

        block_fails = [r for r in results if (not r.passed) and r.severity == "block"]
        allowed = len(block_fails) == 0
        reasons = [r.message for r in block_fails] or ["All live publishing rules passed"]
        return PublishingDecision(
            allowed=allowed,
            dry_run=False,
            authorize_publication=authorize_publication,
            reasons=reasons,
            rule_results=results,
            missing_credentials=list(cred.get("missing") or []),
            eligible_for_dry_run=not missing_fields and not blocked,
            eligible_for_live=allowed,
        )
