"""Module for backend app imports providers."""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class FallbackRule(BaseModel):
    """Represent fallback rule."""

    model_config = ConfigDict(extra="forbid")

    condition: str
    threshold: float | None = None


class ProviderConfig(BaseModel):
    """Represent provider config."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    kind: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_seconds: int = 30
    max_retries: int = 1
    supports_pdf: bool = False
    supports_images: bool = False
    supports_json_schema: bool = False
    cost_tier: str = "free"
    requires_confirmation: bool = False


class ProviderFamilyConfig(BaseModel):
    """Represent provider family config."""

    model_config = ConfigDict(extra="forbid")

    order: list[str] = Field(default_factory=list)
    fallback_on: list[FallbackRule] = Field(default_factory=list)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)


class ProviderRegistry(BaseModel):
    """Represent provider registry."""

    model_config = ConfigDict(extra="forbid")

    document_extraction: ProviderFamilyConfig = Field(
        default_factory=ProviderFamilyConfig
    )
    translation_normalization: ProviderFamilyConfig = Field(
        default_factory=ProviderFamilyConfig
    )
    category_inference: ProviderFamilyConfig = Field(
        default_factory=ProviderFamilyConfig
    )
    duplicate_detection: ProviderFamilyConfig = Field(
        default_factory=ProviderFamilyConfig
    )
    classification_assistant: ProviderFamilyConfig = Field(
        default_factory=ProviderFamilyConfig
    )

    @classmethod
    def from_path(cls, path: Path) -> "ProviderRegistry":
        """Handle from path."""
        if not path.exists():
            return cls()
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(payload)

    def family(self, family_name: str) -> ProviderFamilyConfig:
        """Handle family."""
        return getattr(self, family_name)

    def availability_report(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Return provider availability by family."""
        report: dict[str, dict[str, dict[str, Any]]] = {}
        for family_name in (
            "document_extraction",
            "translation_normalization",
            "category_inference",
            "duplicate_detection",
            "classification_assistant",
        ):
            family = getattr(self, family_name)
            report[family_name] = {}
            available_in_order: list[str] = []
            skipped_in_order: list[str] = []
            for provider_name, provider in family.providers.items():
                available, reason = self._provider_availability(family_name, provider)
                report[family_name][provider_name] = {
                    "available": available,
                    "reason": reason,
                }

            invalid_order_refs = [
                provider_name
                for provider_name in family.order
                if provider_name not in family.providers
            ]
            if invalid_order_refs:
                report[family_name]["__family__"] = {
                    "chain_available": False,
                    "reason": "invalid_order",
                    "invalid_references": invalid_order_refs,
                }
                continue

            for provider_name in family.order:
                provider_report = report[family_name][provider_name]
                if provider_report["available"]:
                    available_in_order.append(provider_name)
                else:
                    skipped_in_order.append(provider_name)

            if available_in_order:
                report[family_name]["__family__"] = {
                    "chain_available": True,
                    "reason": "provider_available",
                    "selected_provider": available_in_order[0],
                    "skipped_providers": skipped_in_order,
                }
            elif family.order:
                report[family_name]["__family__"] = {
                    "chain_available": False,
                    "reason": "no_available_provider",
                    "skipped_providers": skipped_in_order,
                }
            else:
                report[family_name]["__family__"] = {
                    "chain_available": False,
                    "reason": "no_order",
                    "skipped_providers": [],
                }
        return report

    @staticmethod
    def _provider_availability(
        family_name: str, provider: ProviderConfig
    ) -> tuple[bool, str]:
        if not provider.enabled:
            return False, "disabled"
        if family_name == "document_extraction" and not provider.supports_pdf:
            return False, "unsupported_pdf"
        if provider.api_key_env and not os.environ.get(provider.api_key_env):
            return False, "missing_env"
        return True, "enabled"
