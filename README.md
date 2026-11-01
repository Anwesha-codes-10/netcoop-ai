# NetCoop AI - Multi-Agent Network Fault Diagnosis System

**NetCoop AI** is a distributed multi-agent system designed for automated network fault diagnosis across large-scale campus networks, modeled after the **IIT Bhubaneswar** campus network infrastructure (Hostel Wi-Fi, Department Ethernet, Core & Distribution Switches, Lecture Hall Complex, and Datacenter Servers).

---

## Quick start (backend + dashboard)

```bash
pip install -r requirements.txt
python -m netcoop.cli serve        # API + dashboard at the address it prints
```

The dashboard is a React app. Its source is in `ui/` and the **built** version is
committed in `frontend/`, so judges do not need Node. Every number it shows comes
from the real `/api` endpoints; there is no mock data.

Change the UI:

```bash
cd ui && npm install
npm run dev      # hot reload, proxies /api to http://127.0.0.1:8000
npm run build    # writes ../frontend
```

`frontend-classic/` is an older dependency-free version of the dashboard (also
shows telemetry charts and the topology map). To use it, rename it to `frontend/`.

## 📌 Round 1 Status: Foundation Layer (Complete)

Round 1 establishes the rock-solid offline foundation:
- **Versioned Protocol Envelope & Models (`netcoop.protocol`)**: Pydantic v2 implementation of `MessageEnvelope` (schema_version "1.0", UUID, incident_id regex `INC-xxxx`, UTC ISO timestamps) and typed payloads for all 7 message types (`task_request`, `finding`, `evidence_query`, `evidence_response`, `conflict_notice`, `error`, `final_result`).
- **Cause Codes & Metric Dictionary (`netcoop.protocol.causes`)**: 10 standardized `CauseCode` values with human-readable labels and a canonical catalog of 16 network telemetry metrics with valid ranges, units, and baseline expectations.
- **Interoperability & Schema Registry (`netcoop.protocol.schema_registry`)**: Schema registry supporting "1.0" (canonical) and "0.9" (legacy flat sensor telemetry); unrecognized versions are flagged as errors and never guessed.
- **Telemetry Normalizer (`netcoop.protocol.normalizer`)**: Seamlessly converts legacy aliases, unit variants (`s -> ms`, `bps/kbps/Gbps -> Mbps`, `fraction -> %`), parses embedded string units, records every conversion in an audit log, and calculates completeness penalties.
- **Structured Non-Crashing Validators (`netcoop.protocol.validators`)**: Validates JSON envelopes and telemetry time-series batches against 12 structured error codes without throwing uncaught exceptions to callers.
- **Campus Topology (`netcoop.data.topology`)**: Realistic NetworkX graph of IIT Bhubaneswar infrastructure (Uplink NKN Gateway, Dual Core Catalyst 9600s, 4 Distribution switches, 6 Access switches, 5 Wi-Fi 6 APs, DNS/DHCP servers) with JSON load/save.
- **Deterministic Telemetry Generator (`netcoop.data.generator`)**: Seeded synthetic telemetry time-series generator with comprehensive fault profiles (`link_congestion`, `weak_wifi`, `interface_fault`, `dns_failure`, `dhcp_failure`, `upstream_congestion`, `device_cpu_overload`, `ambiguous_insufficient`).
- **Benchmark Sample Scenarios (`netcoop.data.scenarios` & `data/samples/`)**: 14 pre-generated sample scenario files committed to `data/samples/` plus `data/topology.json`.
- **Exhaustive Protocol Documentation (`docs/PROTOCOL.md`)**: Full documentation of all envelope fields, cause codes, canonical metrics, error codes, and complete JSON examples for every single message type.
- **Automated Test Suite (`tests/`)**: 41 comprehensive pytest test cases covering message serialization, normalization, validation error codes, generator determinism, scenario file loading, and topology graph queries.

---

## 📁 Project Directory Structure

```
netcoop_ai/
├── README.md                          # Project documentation and Round 1 public APIs
├── PLAN.md                            # Complete architecture and build order plan
├── requirements.txt                   # Dependency specifications
├── pyproject.toml                     # Project packaging and pytest configuration
├── config/
│   ├── thresholds.yaml                # Canonical metric thresholds, baselines, and windows
│   └── scoring.yaml                   # Data completeness penalties and confidence weights
├── docs/
│   └── PROTOCOL.md                    # Exhaustive protocol specification with JSON examples
├── netcoop/
│   ├── __init__.py
│   ├── protocol/
│   │   ├── __init__.py
│   │   ├── causes.py                  # CauseCode enum, labels, and Canonical Metric Dictionary
│   │   ├── messages.py                # MessageEnvelope & typed payload models (Pydantic v2)
│   │   ├── schema_registry.py         # SchemaRegistry (1.0 canonical, 0.9 legacy, strict checks)
│   │   ├── normalizer.py              # TelemetryNormalizer, unit conversions, and audit log
│   │   └── validators.py              # TelemetryValidator and ErrorCode definitions
│   └── data/
│       ├── __init__.py
│       ├── generator.py               # Seeded time-series telemetry generator
│       ├── scenarios.py               # Scenario builders for standard & interop test cases
│       └── topology.py                # NetworkX campus topology for IIT Bhubaneswar
├── data/
│   ├── topology.json                  # IIT Bhubaneswar network graph export
│   └── samples/                       # Benchmark scenario inputs
│       ├── normal.json
│       ├── link_congestion.json
│       ├── weak_wifi.json
│       ├── interface_fault.json
│       ├── dns_failure.json
│       ├── dhcp_failure.json
│       ├── upstream_congestion.json
│       ├── device_cpu_overload.json
│       ├── ambiguous_insufficient.json
│       ├── legacy_schema_0_9.json
│       ├── mixed_units.json
│       ├── missing_fields.json
│       ├── unknown_schema_version.json
│       └── corrupted_json.json
└── tests/
    ├── __init__.py
    ├── test_protocol_messages.py      # Envelope & payload round-trip serialization tests
    ├── test_normalizer.py             # Alias mapping, unit conversions, and log tests
    ├── test_validators.py             # Structured error code coverage (all 12 codes)
    ├── test_generator.py              # Generator determinism and fault profile tests
    ├── test_scenarios.py              # Scenario file existence and integrity tests
    └── test_topology.py               # Campus graph connectivity and serialization tests
```

---

## 🚀 Public Interfaces for Round 2

### 1. Protocol Models (`netcoop.protocol`)
```python
from netcoop.protocol import (
    MessageEnvelope,
    MessageType,
    CauseCode,
    TaskRequestPayload,
    FindingPayload,
    FindingScope,
    HypothesisCandidate,
    MetricEvidence,
    DataQuality,
    EvidenceQueryPayload,
    EvidenceResponsePayload,
    ConflictNoticePayload,
    ErrorPayload,
    FinalResultPayload,
    parse_message,
)

# Parse any raw JSON message into a strongly-typed Pydantic envelope:
envelope = parse_message(raw_json_string_or_dict)
print(envelope.message_type) # e.g. MessageType.FINDING
print(envelope.payload)      # Strongly typed payload model
```

### 2. Telemetry Normalizer (`netcoop.protocol.normalizer`)
```python
from netcoop.protocol.normalizer import TelemetryNormalizer

normalizer = TelemetryNormalizer()
result = normalizer.normalize_record(raw_telemetry_dict)

print(result.normalized_data) # Canonical metric keys & units (ms, Mbps, %)
print(result.completeness)    # Completeness score 0.0 - 1.0
print(result.log)             # Audit log of every conversion applied
```

### 3. Telemetry Validator (`netcoop.protocol.validators`)
```python
from netcoop.protocol.validators import TelemetryValidator, ErrorCode

validator = TelemetryValidator(stale_window_seconds=300)
# Safe non-crashing JSON validation
parsed_data, res = validator.validate_json_string(raw_text)

# Validate batch of telemetry records
validation_result = validator.validate_telemetry_batch(records, reference_time=now)
if not validation_result.ok:
    for error in validation_result.errors:
        print(error.code, error.message)
```

### 4. Campus Topology Graph (`netcoop.data.topology`)
```python
from netcoop.data.topology import CampusTopology

# Load default IIT Bhubaneswar topology
topo = CampusTopology.load_from_json("data/topology.json")
# Query topology
devices = topo.get_devices_by_segment("hostel_wifi")
path = topo.get_shortest_path("AP_HOSTEL_A_FL1", "GW_NKN_ISP")
```

### 5. Telemetry Generator & Scenarios (`netcoop.data`)
```python
from netcoop.data import TelemetryGenerator, ScenarioBuilder

# Deterministic generation
gen = TelemetryGenerator(seed=42)
series = gen.generate_time_series(device_id="DIST_SW_HOSTEL", fault_type="link_congestion", steps=10)

# Build standard benchmark scenarios
builder = ScenarioBuilder(seed=42)
scenarios = builder.build_all()
```

---

## 🧪 Running Automated Tests

```bash
# Execute full test suite
pytest -v
```

All 41 tests execute completely offline without external APIs or keys.
