# NetCoop AI - Project Implementation Plan 

## Project Overview
NetCoop AI is a multi-agent network fault diagnosis system built for a 24-hour hackathon, modeling campus network telemetry for IIT Bhubaneswar (hostel Wi-Fi, department Ethernet, core/distribution routers, lecture halls, and infrastructure services).

Round 1 establishes the foundational protocol, interoperability layer, synthetic telemetry generation, realistic network topology, scenario benchmarks, and rigorous automated test suite. No agents or orchestrators are built in this round.

---

## Target File Tree

```
netcoop_ai/
├── README.md                          # Project overview, installation, and Round 1 interfaces
├── PLAN.md                            # Comprehensive build plan and file tree architecture
├── requirements.txt                   # Dependency specifications
├── pyproject.toml                     # Python package metadata and tool configurations
├── config/
│   ├── thresholds.yaml                # Telemetry metric thresholds, ranges, baselines, and stale windows
│   └── scoring.yaml                   # Confidence scoring weights, quality penalties, evaluation rules
├── docs/
│   └── PROTOCOL.md                    # Exhaustive protocol specification with JSON examples for all message types
├── netcoop/
│   ├── __init__.py                    # Package root
│   ├── protocol/
│   │   ├── __init__.py                # Protocol exports
│   │   ├── causes.py                  # CauseCode enum, labels, and Canonical Metric Dictionary
│   │   ├── messages.py                # Pydantic v2 envelope and 7 typed payload models
│   │   ├── schema_registry.py         # Version registry (v0.9 legacy & v1.0 canonical, strict checks)
│   │   ├── normalizer.py              # Alias mapping, unit conversions, normalization audit log
│   │   └── validators.py              # Structured error codes, rule validations, ValidationResult
│   └── data/
│       ├── __init__.py                # Data module exports
│       ├── generator.py               # Deterministic time series synthetic telemetry generator
│       ├── scenarios.py               # Pre-defined scenario builders (8 faults, normal, 5 interop edge cases)
│       └── topology.py                # NetworkX campus topology for IIT Bhubaneswar (JSON load/save)
├── data/
│   ├── topology.json                  # Exported campus graph (uplink, core, dist, access, APs, servers)
│   └── samples/                       # Pre-generated and committed scenario sample files
│       ├── normal.json                # Baseline healthy campus network
│       ├── link_congestion.json       # Distribution-to-core link saturation
│       ├── weak_wifi.json             # Hostel room Wi-Fi RF attenuation / low RSSI
│       ├── interface_fault.json       # Department access switch FCS/CRC errors
│       ├── dns_failure.json           # DNS server timeout / high latency
│       ├── dhcp_failure.json          # DHCP pool exhaustion and failures
│       ├── upstream_congestion.json   # NKN ISP gateway bottleneck
│       ├── device_cpu_overload.json   # LHC switch CPU spike
│       ├── ambiguous_insufficient.json# Low completeness / borderline metrics
│       ├── legacy_schema_0_9.json     # Telemetry adhering to schema v0.9 (flat aliases)
│       ├── mixed_units.json           # Telemetry with seconds, Gbps, ratios
│       ├── missing_fields.json        # Telemetry with omitted required fields
│       ├── unknown_schema_version.json# Telemetry with unrecognized schema version
│       └── corrupted_json.json        # Syntactically malformed JSON file
└── tests/
    ├── __init__.py
    ├── test_protocol_messages.py      # Envelope and payload round-trip Pydantic tests
    ├── test_normalizer.py             # Alias mapping, unit conversions, and log verification
    ├── test_validators.py             # Exhaustive checks for every structured error code
    ├── test_generator.py              # Seed determinism and telemetry shape tests
    ├── test_scenarios.py              # Verifies all sample files load and conform to expectations
    └── test_topology.py               # Verifies campus graph connectivity, segments, and serialization
```

---

## Build Order

1. **Step 1: Project Metadata & Dependencies**
   - Create `requirements.txt` with strict versions: `pydantic>=2.0`, `pandas`, `networkx`, `pyyaml`, `pytest`.
   - Create `pyproject.toml` with build-system and pytest path configurations.
   - Create initial `README.md` stub.

2. **Step 2: Configuration Baselines & Thresholds**
   - Create `config/thresholds.yaml` defining healthy baselines, warning thresholds, critical thresholds, units, and valid ranges for all 16 canonical metrics.
   - Create `config/scoring.yaml` defining confidence weighting, evidence impact factors, and data quality penalty functions.

3. **Step 3: Protocol Core (`netcoop/protocol/causes.py` & `messages.py`)**
   - Implement `CauseCode` enum: `LINK_CONGESTION`, `WEAK_WIFI_SIGNAL`, `INTERFACE_FAULT`, `DEVICE_CPU_OVERLOAD`, `UPSTREAM_CONGESTION`, `DNS_FAILURE`, `DHCP_FAILURE`, `HARDWARE_FAILURE`, `NORMAL`, `UNKNOWN` with human-readable labels.
   - Define canonical metric catalog with units, validation bounds, and descriptions.
   - Implement `MessageEnvelope` (UUID message_id, INC-xxxx incident_id, schema_version 1.0, UTC ISO timestamp, sender, recipient, message_type, correlation_id, payload).
   - Implement typed payload models for all 7 message types: `task_request`, `finding`, `evidence_query`, `evidence_response`, `conflict_notice`, `error`, `final_result`.

4. **Step 4: Interoperability Layer (`schema_registry.py`, `normalizer.py`, `validators.py`)**
   - `schema_registry.py`: Manage schema versions "0.9" and "1.0". Unrecognized versions raise structured errors, never guessed.
   - `normalizer.py`: Map legacy aliases (`lat`, `rtt`, `util`, `loss`, `signal`, etc.) to canonical names. Convert units (`s -> ms`, `bps/kbps/Gbps -> Mbps`, `fraction -> percent`). Record all conversions in an audit log. Compute data completeness penalties for unconvertible fields.
   - `validators.py`: Implement non-crashing structured validation returning `ValidationResult(ok, errors, warnings, completeness)`. Cover all 12 failure classes: missing fields, wrong types, out-of-range, empty input, NaN/null, timestamp anomalies, stale data, unknown devices, unknown schemas, mixed units, and corrupted JSON.

5. **Step 5: Campus Topology (`netcoop/data/topology.py`)**
   - Construct a realistic IIT Bhubaneswar campus network graph using `networkx`:
     - Uplink: `GW_NKN_ISP`
     - Core: `CORE_RTR_01`, `CORE_RTR_02`
     - Distribution: `DIST_SW_ACAD`, `DIST_SW_HOSTEL`, `DIST_SW_ADMIN`, `DIST_SW_DATACENTER`
     - Access Switches: Hostels (`ACC_SW_HOSTEL_A`, `ACC_SW_HOSTEL_B`), Departments (`ACC_SW_CSE_01`, `ACC_SW_ECE_01`), LHC (`ACC_SW_LHC_01`)
     - Access Points: `AP_HOSTEL_A_FL1`, `AP_HOSTEL_A_FL2`, `AP_LHC_ROOM101`, etc.
     - Servers: `SRV_DNS_01`, `SRV_DNS_02`, `SRV_DHCP_01`, `SRV_DHCP_02`
   - Implement JSON export/import and query methods for devices and segments.

6. **Step 6: Synthetic Telemetry Generator (`netcoop/data/generator.py`)**
   - Port and expand the Colab telemetry generation logic.
   - Add deterministic seeding (`random.Random(seed)` and numpy/pandas seed consistency).
   - Generate per-device time series with all 16 canonical metrics over configurable time intervals.
   - Support specific fault profile injection corresponding to each cause code.

7. **Step 7: Scenarios & Data Samples (`netcoop/data/scenarios.py` & `data/samples/`)**
   - Build generators for all required scenarios:
     - Root causes: `normal`, `link_congestion`, `weak_wifi`, `interface_fault`, `dns_failure`, `dhcp_failure`, `upstream_congestion`, `device_cpu_overload`, `ambiguous_insufficient`.
     - Interoperability tests: `legacy_schema_0_9`, `mixed_units`, `missing_fields`, `unknown_schema_version`, `corrupted_json`.
   - Export all sample datasets into `data/samples/` and `data/topology.json`.

8. **Step 8: Comprehensive Protocol Documentation (`docs/PROTOCOL.md`)**
   - Document all fields, units, valid ranges, versioning rules, error codes.
   - Include a summary table of message types and exact, realistic JSON examples for every message type.

9. **Step 9: Test Suite Implementation & Verification**
   - Write comprehensive pytest modules covering protocol serialization, normalizer conversions and logs, validator error codes, generator determinism, scenario file integrity, and topology operations.
   - Run pytest and ensure 100% test pass rate.

10. **Step 10: Final Documentation & Round 2 Handoff**
    - Update `README.md` with module summary and public APIs.
    - Provide a structured handoff overview for Round 2.
