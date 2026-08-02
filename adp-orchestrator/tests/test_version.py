from importlib.metadata import version

import adp_orchestrator


def test_exported_version_matches_distribution_metadata() -> None:
    assert adp_orchestrator.__version__ == version("adp-orchestrator")
