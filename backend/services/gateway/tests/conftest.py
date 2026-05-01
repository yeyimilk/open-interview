from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

MODELS_YAML = """
chat:
  default: chat-test
  models:
    chat-test:
      provider: openai
      endpoint: https://api.openai.com/v1
      model_id: gpt-test
embedding:
  default: embed-test
  models:
    embed-test:
      provider: openai
      endpoint: https://api.openai.com/v1
      model_id: embed-test-model
"""

TIERS_YAML = """
tiers:
  free:
    rate_limit_rpm: 3
  paid:
    rate_limit_rpm: 60
"""


@pytest.fixture()
def yaml_tmp(tmp_path_factory):
    d = tmp_path_factory.mktemp("cfg")
    (d / "models.yaml").write_text(MODELS_YAML)
    (d / "tiers.yaml").write_text(TIERS_YAML)
    return d
