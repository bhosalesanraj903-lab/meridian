"""Central runtime configuration.

Every entrypoint (CLI, Lambda handler, Glue job) builds one Settings object
from the environment and passes it down. Nothing else reads os.environ, and
nothing hardcodes paths — the same code runs against a local directory
(`MERIDIAN_LAKE_URI=./data`, the default) or the S3 lake
(`MERIDIAN_LAKE_URI=s3://meridian-lake-<acct>`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    lake_uri: str
    user_agent: str
    state_backend: str  # "local" | "dynamodb"
    state_table: str
    aws_region: str
    alerts_topic_arn: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            lake_uri=os.environ.get("MERIDIAN_LAKE_URI", "./data").rstrip("/"),
            user_agent=os.environ.get(
                "MERIDIAN_USER_AGENT",
                "MeridianDataPlatform bhosalesanraj903@gmail.com",
            ),
            state_backend=os.environ.get("MERIDIAN_STATE_BACKEND", "local"),
            state_table=os.environ.get("MERIDIAN_STATE_TABLE", "meridian-state"),
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            alerts_topic_arn=os.environ.get("MERIDIAN_ALERTS_TOPIC_ARN", ""),
        )

    # Lake layout — single source of truth for prefixes.
    @property
    def bronze_ofac_prefix(self) -> str:
        return f"{self.lake_uri}/bronze/ofac/sdn"

    @property
    def bronze_customers_prefix(self) -> str:
        return f"{self.lake_uri}/bronze/customers/incoming"

    @property
    def silver_customers_prefix(self) -> str:
        return f"{self.lake_uri}/silver/customers"

    @property
    def gold_hits_prefix(self) -> str:
        return f"{self.lake_uri}/gold/screening_hits"

    @property
    def quarantine_prefix(self) -> str:
        return f"{self.lake_uri}/quarantine"

    @property
    def manifests_prefix(self) -> str:
        return f"{self.lake_uri}/manifests"

    @property
    def local_state_path(self) -> str:
        return f"{self.lake_uri}/bronze/ofac/_state.json"
