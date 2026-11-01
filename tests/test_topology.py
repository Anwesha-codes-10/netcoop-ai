"""Tests for NetCoop AI campus network topology."""

from pathlib import Path
import pytest

from netcoop.data.topology import CampusTopology


def test_campus_topology_structure():
    topo = CampusTopology.build_iit_bhubaneswar_topology()
    device_ids = topo.get_device_ids()

    # Verify key nodes are present
    assert "GW_NKN_ISP" in device_ids
    assert "CORE_RTR_01" in device_ids
    assert "DIST_SW_HOSTEL" in device_ids
    assert "ACC_SW_HOSTEL_A" in device_ids
    assert "AP_HOSTEL_A_FL1" in device_ids
    assert "SRV_DNS_01" in device_ids
    assert "SRV_DHCP_01" in device_ids

    # Check segment queries
    hostel_devs = topo.get_devices_by_segment("hostel_wifi")
    assert "DIST_SW_HOSTEL" in hostel_devs
    assert "ACC_SW_HOSTEL_A" in hostel_devs
    assert "AP_HOSTEL_A_FL1" in hostel_devs

    # Check type queries
    servers = topo.get_devices_by_type("server")
    assert "SRV_DNS_01" in servers
    assert "SRV_DHCP_01" in servers

    aps = topo.get_devices_by_type("access_point")
    assert "AP_HOSTEL_A_FL2" in aps


def test_topology_path_reachability():
    topo = CampusTopology.build_iit_bhubaneswar_topology()

    # Path from AP in hostel to gateway
    path = topo.get_shortest_path("AP_HOSTEL_A_FL1", "GW_NKN_ISP")
    assert path is not None
    assert path[0] == "AP_HOSTEL_A_FL1"
    assert path[-1] == "GW_NKN_ISP"
    assert "ACC_SW_HOSTEL_A" in path
    assert "DIST_SW_HOSTEL" in path


def test_topology_json_round_trip(tmp_path):
    topo1 = CampusTopology.build_iit_bhubaneswar_topology()
    out_file = tmp_path / "test_topo.json"
    topo1.save_to_json(out_file)

    assert out_file.exists()
    topo2 = CampusTopology.load_from_json(out_file)

    assert sorted(topo1.get_device_ids()) == sorted(topo2.get_device_ids())
    assert topo1.graph.number_of_edges() == topo2.graph.number_of_edges()

    # Verify node attributes preserved
    gw1 = topo1.get_device("GW_NKN_ISP")
    gw2 = topo2.get_device("GW_NKN_ISP")
    assert gw1["ip_address"] == gw2["ip_address"]
    assert gw1["bandwidth_mbps"] == gw2["bandwidth_mbps"]
