from __future__ import annotations

PUBLIC_BLOCKED_FINDINGS = {
    "password",
    "api_key",
    "bearer_token",
    "private_key",
    "biometric_data",
    "raw_chat_trace",
    "prompt_exfiltration",
    "custom_code_public",
}

PRIVATE_BLOCKED_FINDINGS = {
    "password",
    "api_key",
    "bearer_token",
    "private_key",
    "biometric_data",
    "prompt_exfiltration",
}

BUNDLE_MODES = {"spec_only", "trusted_code", "frozen_bundle"}
VISIBILITIES = {"public", "private"}
LANES = {"curated", "experimental", "revoked", "org_curated", "org_experimental", "org_revoked"}


def blocked_findings_for_visibility(visibility: str) -> set[str]:
    return set(PUBLIC_BLOCKED_FINDINGS if str(visibility or "").strip().lower() == "public" else PRIVATE_BLOCKED_FINDINGS)
