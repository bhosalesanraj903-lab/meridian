import pytest

from meridian.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        lake_uri=str(tmp_path / "lake"),
        user_agent="test",
        state_backend="local",
        state_table="meridian-state",
        aws_region="us-east-1",
        alerts_topic_arn="",
    )
