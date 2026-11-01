"""NetCoop AI Data - Campus Network Topology for IIT Bhubaneswar.

Constructs, queries, saves, and loads a realistic NetworkX topology graph representing:
- Uplink (NKN Gateway)
- Campus Core Routers
- Distribution Switches (Hostel, Acad, DC, Admin)
- Access Switches (Hostel Blocks, Depts, LHC, Library)
- Wireless Access Points (Hostels, LHC, Library)
- Infrastructure Servers (DNS, DHCP)
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

import networkx as nx


class CampusTopology:
    """Manages the network graph and metadata for the campus infrastructure."""

    def __init__(self, graph: Optional[nx.Graph] = None):
        self.graph = graph if graph is not None else nx.Graph()

    @classmethod
    def build_iit_bhubaneswar_topology(cls) -> "CampusTopology":
        """Construct the official IIT Bhubaneswar campus network topology."""
        g = nx.Graph()

        # 1. Uplink Gateway
        g.add_node(
            "GW_NKN_ISP",
            device_id="GW_NKN_ISP",
            device_type="uplink",
            segment="uplink",
            location="Campus Border / Datacenter",
            ip_address="14.139.221.1",
            bandwidth_mbps=20000.0,
            model="Cisco ASR 9904",
        )

        # 2. Campus Core Routers
        g.add_node(
            "CORE_RTR_01",
            device_id="CORE_RTR_01",
            device_type="core_router",
            segment="core",
            location="Main Datacenter (CC)",
            ip_address="10.10.0.1",
            bandwidth_mbps=10000.0,
            model="Cisco Catalyst 9600",
        )
        g.add_node(
            "CORE_RTR_02",
            device_id="CORE_RTR_02",
            device_type="core_router",
            segment="core",
            location="Backup Datacenter (Admin)",
            ip_address="10.10.0.2",
            bandwidth_mbps=10000.0,
            model="Cisco Catalyst 9600",
        )

        # 3. Distribution Switches
        g.add_node(
            "DIST_SW_HOSTEL",
            device_id="DIST_SW_HOSTEL",
            device_type="distribution_switch",
            segment="hostel_wifi",
            location="Hostel Cluster Node Room",
            ip_address="10.10.10.1",
            bandwidth_mbps=10000.0,
            model="Cisco Catalyst 9500",
        )
        g.add_node(
            "DIST_SW_ACAD",
            device_id="DIST_SW_ACAD",
            device_type="distribution_switch",
            segment="dept_ethernet",
            location="Academic Complex Block 1",
            ip_address="10.10.20.1",
            bandwidth_mbps=10000.0,
            model="Cisco Catalyst 9500",
        )
        g.add_node(
            "DIST_SW_ADMIN",
            device_id="DIST_SW_ADMIN",
            device_type="distribution_switch",
            segment="admin",
            location="Administrative Building",
            ip_address="10.10.30.1",
            bandwidth_mbps=10000.0,
            model="Cisco Catalyst 9500",
        )
        g.add_node(
            "DIST_SW_DATACENTER",
            device_id="DIST_SW_DATACENTER",
            device_type="distribution_switch",
            segment="datacenter",
            location="Main Datacenter Server Farm",
            ip_address="10.10.40.1",
            bandwidth_mbps=10000.0,
            model="Nexus 9300",
        )

        # 4. Access Switches
        # Hostels
        g.add_node(
            "ACC_SW_HOSTEL_A",
            device_id="ACC_SW_HOSTEL_A",
            device_type="access_switch",
            segment="hostel_wifi",
            location="Hostel Block A (MHR)",
            ip_address="10.10.11.1",
            bandwidth_mbps=1000.0,
            model="Cisco Catalyst 9200",
        )
        g.add_node(
            "ACC_SW_HOSTEL_B",
            device_id="ACC_SW_HOSTEL_B",
            device_type="access_switch",
            segment="hostel_wifi",
            location="Hostel Block B (Subhadra Hall)",
            ip_address="10.10.12.1",
            bandwidth_mbps=1000.0,
            model="Cisco Catalyst 9200",
        )
        # Academic & LHC
        g.add_node(
            "ACC_SW_CSE_01",
            device_id="ACC_SW_CSE_01",
            device_type="access_switch",
            segment="dept_ethernet",
            location="School of Electrical Sciences (CSE Wing)",
            ip_address="10.10.21.1",
            bandwidth_mbps=1000.0,
            model="Cisco Catalyst 9200",
        )
        g.add_node(
            "ACC_SW_ECE_01",
            device_id="ACC_SW_ECE_01",
            device_type="access_switch",
            segment="dept_ethernet",
            location="School of Electrical Sciences (ECE Wing)",
            ip_address="10.10.22.1",
            bandwidth_mbps=1000.0,
            model="Cisco Catalyst 9200",
        )
        g.add_node(
            "ACC_SW_LHC_01",
            device_id="ACC_SW_LHC_01",
            device_type="access_switch",
            segment="lhc",
            location="Lecture Hall Complex Ground Floor",
            ip_address="10.10.23.1",
            bandwidth_mbps=1000.0,
            model="Cisco Catalyst 9200",
        )
        g.add_node(
            "ACC_SW_LIB_01",
            device_id="ACC_SW_LIB_01",
            device_type="access_switch",
            segment="dept_ethernet",
            location="Central Library Switch Room",
            ip_address="10.10.24.1",
            bandwidth_mbps=1000.0,
            model="Cisco Catalyst 9200",
        )

        # 5. Access Points (APs)
        g.add_node(
            "AP_HOSTEL_A_FL1",
            device_id="AP_HOSTEL_A_FL1",
            device_type="access_point",
            segment="hostel_wifi",
            location="Hostel A Floor 1 Corridor",
            ip_address="10.10.11.101",
            bandwidth_mbps=1000.0,
            model="Aruba AP-535 Wi-Fi 6",
        )
        g.add_node(
            "AP_HOSTEL_A_FL2",
            device_id="AP_HOSTEL_A_FL2",
            device_type="access_point",
            segment="hostel_wifi",
            location="Hostel A Floor 2 Corridor",
            ip_address="10.10.11.102",
            bandwidth_mbps=1000.0,
            model="Aruba AP-535 Wi-Fi 6",
        )
        g.add_node(
            "AP_HOSTEL_B_FL1",
            device_id="AP_HOSTEL_B_FL1",
            device_type="access_point",
            segment="hostel_wifi",
            location="Hostel B Floor 1 Corridor",
            ip_address="10.10.12.101",
            bandwidth_mbps=1000.0,
            model="Aruba AP-535 Wi-Fi 6",
        )
        g.add_node(
            "AP_LHC_ROOM101",
            device_id="AP_LHC_ROOM101",
            device_type="access_point",
            segment="lhc",
            location="LHC Room 101 Lecture Hall",
            ip_address="10.10.23.101",
            bandwidth_mbps=1000.0,
            model="Aruba AP-555 High-Density",
        )
        g.add_node(
            "AP_LIB_READING",
            device_id="AP_LIB_READING",
            device_type="access_point",
            segment="dept_ethernet",
            location="Central Library Main Reading Hall",
            ip_address="10.10.24.101",
            bandwidth_mbps=1000.0,
            model="Aruba AP-535 Wi-Fi 6",
        )

        # 6. Infrastructure Servers (Datacenter)
        g.add_node(
            "SRV_DNS_01",
            device_id="SRV_DNS_01",
            device_type="server",
            segment="datacenter",
            location="Main Datacenter Rack 4",
            ip_address="10.10.40.10",
            bandwidth_mbps=10000.0,
            model="Dell PowerEdge R650 (Primary DNS)",
        )
        g.add_node(
            "SRV_DNS_02",
            device_id="SRV_DNS_02",
            device_type="server",
            segment="datacenter",
            location="Main Datacenter Rack 5",
            ip_address="10.10.40.11",
            bandwidth_mbps=10000.0,
            model="Dell PowerEdge R650 (Secondary DNS)",
        )
        g.add_node(
            "SRV_DHCP_01",
            device_id="SRV_DHCP_01",
            device_type="server",
            segment="datacenter",
            location="Main Datacenter Rack 4",
            ip_address="10.10.40.20",
            bandwidth_mbps=10000.0,
            model="Dell PowerEdge R650 (Primary DHCP)",
        )
        g.add_node(
            "SRV_DHCP_02",
            device_id="SRV_DHCP_02",
            device_type="server",
            segment="datacenter",
            location="Main Datacenter Rack 5",
            ip_address="10.10.40.21",
            bandwidth_mbps=10000.0,
            model="Dell PowerEdge R650 (Secondary DHCP)",
        )

        # ---------------------------------------------------------------------
        # Edges / Links
        # ---------------------------------------------------------------------

        # Uplink to Core Routers (Dual 10G / 20G links)
        g.add_edge("GW_NKN_ISP", "CORE_RTR_01", bandwidth_mbps=10000.0, medium="fiber", interface_u="HundredGigE0/0/1", interface_v="TenGigE1/0/1")
        g.add_edge("GW_NKN_ISP", "CORE_RTR_02", bandwidth_mbps=10000.0, medium="fiber", interface_u="HundredGigE0/0/2", interface_v="TenGigE1/0/1")

        # Inter-Core Link
        g.add_edge("CORE_RTR_01", "CORE_RTR_02", bandwidth_mbps=20000.0, medium="fiber", interface_u="TenGigE1/0/48", interface_v="TenGigE1/0/48")

        # Core Routers to Distribution Switches
        dist_switches = ["DIST_SW_HOSTEL", "DIST_SW_ACAD", "DIST_SW_ADMIN", "DIST_SW_DATACENTER"]
        for dist in dist_switches:
            g.add_edge("CORE_RTR_01", dist, bandwidth_mbps=10000.0, medium="fiber", interface_u=f"TenGigE1/{dist}", interface_v="TenGigE0/1")
            g.add_edge("CORE_RTR_02", dist, bandwidth_mbps=10000.0, medium="fiber", interface_u=f"TenGigE1/{dist}", interface_v="TenGigE0/2")

        # Distribution to Access Switches
        g.add_edge("DIST_SW_HOSTEL", "ACC_SW_HOSTEL_A", bandwidth_mbps=1000.0, medium="fiber", interface_u="GigE1/0/1", interface_v="GigE0/49")
        g.add_edge("DIST_SW_HOSTEL", "ACC_SW_HOSTEL_B", bandwidth_mbps=1000.0, medium="fiber", interface_u="GigE1/0/2", interface_v="GigE0/49")

        g.add_edge("DIST_SW_ACAD", "ACC_SW_CSE_01", bandwidth_mbps=1000.0, medium="fiber", interface_u="GigE1/0/1", interface_v="GigE0/49")
        g.add_edge("DIST_SW_ACAD", "ACC_SW_ECE_01", bandwidth_mbps=1000.0, medium="fiber", interface_u="GigE1/0/2", interface_v="GigE0/49")
        g.add_edge("DIST_SW_ACAD", "ACC_SW_LHC_01", bandwidth_mbps=1000.0, medium="fiber", interface_u="GigE1/0/3", interface_v="GigE0/49")
        g.add_edge("DIST_SW_ACAD", "ACC_SW_LIB_01", bandwidth_mbps=1000.0, medium="fiber", interface_u="GigE1/0/4", interface_v="GigE0/49")

        # Distribution Datacenter to Servers
        g.add_edge("DIST_SW_DATACENTER", "SRV_DNS_01", bandwidth_mbps=10000.0, medium="fiber", interface_u="TenGigE1/1", interface_v="eth0")
        g.add_edge("DIST_SW_DATACENTER", "SRV_DNS_02", bandwidth_mbps=10000.0, medium="fiber", interface_u="TenGigE1/2", interface_v="eth0")
        g.add_edge("DIST_SW_DATACENTER", "SRV_DHCP_01", bandwidth_mbps=10000.0, medium="fiber", interface_u="TenGigE1/3", interface_v="eth0")
        g.add_edge("DIST_SW_DATACENTER", "SRV_DHCP_02", bandwidth_mbps=10000.0, medium="fiber", interface_u="TenGigE1/4", interface_v="eth0")

        # Access Switches to APs
        g.add_edge("ACC_SW_HOSTEL_A", "AP_HOSTEL_A_FL1", bandwidth_mbps=1000.0, medium="cat6", interface_u="GigE0/1", interface_v="eth0")
        g.add_edge("ACC_SW_HOSTEL_A", "AP_HOSTEL_A_FL2", bandwidth_mbps=1000.0, medium="cat6", interface_u="GigE0/2", interface_v="eth0")
        g.add_edge("ACC_SW_HOSTEL_B", "AP_HOSTEL_B_FL1", bandwidth_mbps=1000.0, medium="cat6", interface_u="GigE0/1", interface_v="eth0")
        g.add_edge("ACC_SW_LHC_01", "AP_LHC_ROOM101", bandwidth_mbps=1000.0, medium="cat6", interface_u="GigE0/1", interface_v="eth0")
        g.add_edge("ACC_SW_LIB_01", "AP_LIB_READING", bandwidth_mbps=1000.0, medium="cat6", interface_u="GigE0/1", interface_v="eth0")

        return cls(graph=g)

    def get_device_ids(self) -> List[str]:
        """Return all device IDs in the topology."""
        return sorted(list(self.graph.nodes()))

    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Return attributes dictionary for a given device ID."""
        if device_id in self.graph.nodes:
            return dict(self.graph.nodes[device_id])
        return None

    def get_devices_by_type(self, device_type: str) -> List[str]:
        """Return all device IDs matching a device type."""
        return [
            node for node, data in self.graph.nodes(data=True)
            if data.get("device_type") == device_type
        ]

    def get_devices_by_segment(self, segment: str) -> List[str]:
        """Return all device IDs belonging to a network segment."""
        return [
            node for node, data in self.graph.nodes(data=True)
            if data.get("segment") == segment
        ]

    def get_neighbors(self, device_id: str) -> List[str]:
        """Return adjacent device IDs."""
        if device_id in self.graph:
            return list(self.graph.neighbors(device_id))
        return []

    def get_shortest_path(self, source: str, target: str) -> Optional[List[str]]:
        """Calculate shortest hop path between two devices."""
        try:
            return nx.shortest_path(self.graph, source=source, target=target)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize topology graph to a structured dictionary."""
        nodes_list = []
        for node, data in self.graph.nodes(data=True):
            item = dict(data)
            item["id"] = node
            nodes_list.append(item)

        edges_list = []
        for u, v, data in self.graph.edges(data=True):
            item = dict(data)
            item["source"] = u
            item["target"] = v
            edges_list.append(item)

        return {
            "name": "IIT Bhubaneswar Campus Network",
            "version": "1.0",
            "node_count": self.graph.number_of_nodes(),
            "edge_count": self.graph.number_of_edges(),
            "nodes": sorted(nodes_list, key=lambda x: x["id"]),
            "edges": edges_list,
        }

    def save_to_json(self, path: Union[str, Path], indent: int = 2) -> None:
        """Write topology graph to a JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=indent)

    @classmethod
    def load_from_json(cls, path: Union[str, Path]) -> "CampusTopology":
        """Load and reconstruct topology graph from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        g = nx.Graph()
        for node_info in data.get("nodes", []):
            node_id = node_info.get("id") or node_info.get("device_id")
            attrs = {k: v for k, v in node_info.items() if k != "id"}
            g.add_node(node_id, **attrs)

        for edge_info in data.get("edges", []):
            u = edge_info["source"]
            v = edge_info["target"]
            attrs = {k: v for k, v in edge_info.items() if k not in ["source", "target"]}
            g.add_edge(u, v, **attrs)

        return cls(graph=g)
