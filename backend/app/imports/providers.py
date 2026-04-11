from pathlib import Path
import os

import yaml
from pydantic import BaseModel, Field


class FallbackRule(BaseModel):
    condition: str
    threshold: float | None = None


class ProviderConfig(BaseModel):
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
    order: list[str] = Field(default_factory=list)
    fallback_on: list[FallbackRule] = Field(default_factory=list)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)


class ProviderRegistry(BaseModel):
    document_extraction: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    translation_normalization: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    category_inference: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    duplicate_detection: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)

    @classmethod
    def from_path(cls, path: Path) -> "ProviderRegistry":
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(payload)

    def family(self, family_name: str) -> ProviderFamilyConfig:
        return getattr(self, family_name)

    def validate(self) -> dict[str, dict[str, dict[str, str | bool]]]:
        report: dict[str, dict[str, dict[str, str | bool]]] = {}
        for family_name in (
            "document_extraction",
            "translation_normalization",
            "category_inference",
            "duplicate_detection",
        ):
            family = getattr(self, family_name)
            report[family_name] = {}
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
        return report
