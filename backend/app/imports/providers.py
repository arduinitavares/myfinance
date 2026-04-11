from pathlib import Path
import os
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class FallbackRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: str
    threshold: float | None = None


class ProviderConfig(BaseModel):
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
    model_config = ConfigDict(extra="forbid")

    order: list[str] = Field(default_factory=list)
    fallback_on: list[FallbackRule] = Field(default_factory=list)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)


class ProviderRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_extraction: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    translation_normalization: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    category_inference: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    duplicate_detection: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)

    @classmethod
    def from_path(cls, path: Path) -> "ProviderRegistry":
        if not path.exists():
            return cls()
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(payload)

    def family(self, family_name: str) -> ProviderFamilyConfig:
        return getattr(self, family_name)

    def validate(self) -> dict[str, dict[str, dict[str, Any]]]:
        report: dict[str, dict[str, dict[str, Any]]] = {}
        for family_name in (
            "document_extraction",
            "translation_normalization",
            "category_inference",
            "duplicate_detection",
        ):
            family = getattr(self, family_name)
            report[family_name] = {}
            available_in_order: list[str] = []
            skipped_in_order: list[str] = []
            for provider_name, provider in family.providers.items():
                available = True
                reason = "enabled"
                if not provider.enabled:
                    available = False
                    reason = "disabled"
                elif provider.api_key_env and not os.environ.get(provider.api_key_env):
                    available = False
                    reason = "missing_env"
                report[family_name][provider_name] = {
                    "available": available,
                    "reason": reason,
                }

            invalid_order_refs = [provider_name for provider_name in family.order if provider_name not in family.providers]
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
