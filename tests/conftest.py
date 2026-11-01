"""NetCoop AI Shared Test Fixtures."""

import pytest
from netcoop.config import load_config
from netcoop.data.topology import CampusTopology


@pytest.fixture
def topology():
    """IIT Bhubaneswar campus topology fixture."""
    return CampusTopology.build_iit_bhubaneswar_topology()


@pytest.fixture
def system_config():
    """System configuration fixture merging thresholds, scoring, and agents."""
    return load_config()