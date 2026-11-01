# NetCoop AI Protocol Specification (v1.0)

## 1. Executive Summary & Core Principles
NetCoop AI is a distributed, cooperative multi-agent system designed for automated network fault diagnosis across complex campus infrastructures (modeled after the IIT Bhubaneswar campus network).

The NetCoop communication protocol is built on five strict architectural principles:
1. **Deterministic Versioned Envelope**: Every message exchanged between agents, telemetry ingestion sensors, and the orchestrator is wrapped in a versioned envelope (`schema_version: "1.0"`).
2. **Strict Schema Integrity**: Protocol schemas are strictly validated using Pydantic v2. Schema versions are never guessed; unknown versions trigger structured validation errors.
3. **Structured Non-Crashing Validation**: The protocol and telemetry validation pipelines never raise unhandled exceptions or raw stack traces to calling routines. All issues are categorized into structured error codes (`ErrorCode`).
4. **Transparent Audit Logging**: The interoperability layer maps legacy aliases (from schema v0.9) and converts heterogeneous telemetry units (seconds to milliseconds, Gbps/bps to Mbps, fractions to percentages) while recording every transformation in an immutable audit log.
5. **Quality-Aware Diagnosis**: Hypotheses explicitly separate supporting metrics from contradicting metrics and evaluate data quality (completeness, stale fields, missing metrics, and assumptions).

---

## 2. Protocol Envelope Specification

All messages sent over the agent bus adhere to the canonical `MessageEnvelope`:

| Field | Type | Required | Description / Constraints |
| :--- | :--- | :--- | :--- |
| `message_id` | `string (UUIDv4)` | Yes | Globally unique message identifier. Default: auto-generated UUIDv4. |
| `incident_id` | `string` | Yes | Incident case reference. Regex: `^INC-[A-Za-z0-9_-]+$` (e.g. `INC-2026-1042`). |
| `schema_version` | `string` | Yes | Target protocol schema version. Currently `"1.0"` (or `"0.9"` for legacy sensors). |
| `timestamp` | `string (ISO8601 UTC)` | Yes | UTC timestamp formatted with timezone offset (e.g., `2026-10-31T10:00:00Z`). |
| `sender` | `string` | Yes | Identifier of sending agent, sensor, or orchestrator (e.g., `wifi_subsystem_agent`). |
| `recipient` | `string` | Yes | Designated recipient: agent name, `"orchestrator"`, or `"broadcast"`. |
| `message_type` | `enum (string)` | Yes | One of the 7 supported protocol message types (see Section 3). |
| `correlation_id` | `string` | Optional | Identifier of originating request or conversation thread (nullable). |
| `payload` | `object` | Yes | Strongly-typed payload matching the declared `message_type`. |

---

## 3. Message Types Overview

| Message Type | Sender $\to$ Recipient | Purpose | Payload Model |
| :--- | :--- | :--- | :--- |
| `task_request` | Orchestrator $\to$ Agent | Assigns an investigation scope, target devices, or time window to a specialized agent. | `TaskRequestPayload` |
| `finding` | Agent $\to$ Orchestrator / Broadcast | Reports diagnostic hypothesis candidates, supporting/contradicting metrics, and data completeness. | `FindingPayload` |
| `evidence_query` | Agent $\to$ Peer / Storage | Requests raw telemetry or historical metric series for correlation. | `EvidenceQueryPayload` |
| `evidence_response` | Peer / Storage $\to$ Agent | Supplies requested telemetry records matching query filters. | `EvidenceResponsePayload` |
| `conflict_notice` | Orchestrator / Agent $\to$ Peers | Alerts participants of contradictory hypotheses between agents requiring collaborative reconciliation. | `ConflictNoticePayload` |
| `error` | Any $\to$ Orchestrator / Sender | Communicates execution, syntax, or validation errors using structured error codes. | `ErrorPayload` |
| `final_result` | Orchestrator $\to$ Broadcast / Operations | Publishes the consensus primary root cause, affected devices, and actionable remediation steps. | `FinalResultPayload` |

---

## 4. Detailed Payload Specifications

### 4.1 `TaskRequestPayload`
- `task_id` (`string`): Unique task assignment token.
- `target_device_ids` (`list[string]`): List of devices to analyze (e.g. `["DIST_SW_HOSTEL", "ACC_SW_HOSTEL_A"]`).
- `target_segment` (`string`, optional): Network segment (e.g. `"hostel_wifi"`, `"dept_ethernet"`, `"lhc"`).
- `window_start` (`ISO8601 UTC`, optional): Telemetry analysis window start.
- `window_end` (`ISO8601 UTC`, optional): Telemetry analysis window end.
- `parameters` (`dict`, optional): Additional agent-specific execution arguments.

### 4.2 `FindingPayload`
- `agent` (`string`): Name of the reporting agent.
- `scope` (`object`):
  - `device_ids` (`list[string]`): Devices evaluated.
  - `segment` (`string`, optional): Topological segment investigated.
- `hypothesis_candidates` (`list[object]`): Ranked diagnosis hypotheses. Each candidate contains:
  - `cause_code` (`CauseCode`): Identified root cause enum.
  - `score` (`float`, 0.0 to 1.0): Likelihood or belief score.
  - `supporting_metrics` (`list[MetricEvidence]`): Metrics that confirm this hypothesis.
  - `contradicting_metrics` (`list[MetricEvidence]`): Metrics that argue against this hypothesis.
- `data_quality` (`object`):
  - `completeness` (`float`, 0.0 to 1.0): Telemetry coverage metric after penalties.
  - `stale_fields` (`list[string]`): Stale telemetry fields detected.
  - `missing_fields` (`list[string]`): Expected metrics absent from data.
  - `assumptions` (`list[string]`): Explicit inferences made by the agent.
- `confidence` (`float`, 0.0 to 1.0): Aggregate diagnostic confidence score.

### 4.3 `MetricEvidence` Sub-structure
- `metric` (`string`): Canonical metric name (e.g. `link_utilization_pct`).
- `value` (`float | int | string`): Observed value.
- `unit` (`string`): Canonical unit (e.g. `%`, `ms`, `Mbps`).
- `baseline` (`float | int | string`, optional): Expected healthy reference value.
- `interpretation` (`string`): Qualitative explanation (e.g. `"Exceeds critical saturation threshold by 63%"`).

### 4.4 `EvidenceQueryPayload`
- `query_id` (`string`): Query tracking identifier.
- `requested_by` (`string`): Requesting agent identifier.
- `device_ids` (`list[string]`): Target devices.
- `metrics` (`list[string]`): Specific telemetry metrics queried.
- `start_time` (`ISO8601 UTC`, optional): Filter start time.
- `end_time` (`ISO8601 UTC`, optional): Filter end time.
- `filter_criteria` (`dict`): Additional matching conditions.

### 4.5 `EvidenceResponsePayload`
- `query_id` (`string`): Corresponds to `EvidenceQueryPayload.query_id`.
- `device_telemetry` (`list[dict]`): Telemetry records returned.
- `matched_records_count` (`int`): Count of matched records.
- `data_truncated` (`bool`): True if query hit max result limits.

### 4.6 `ConflictNoticePayload`
- `conflict_id` (`string`): Unique conflict token.
- `conflicting_hypotheses` (`list[dict]`): Differing hypotheses proposed by agents.
- `contending_agents` (`list[string]`): Names of disagreeing agents.
- `disputed_metrics` (`list[string]`): Metrics with contradictory interpretations.
- `resolution_strategy` (`string`, optional): Proposed arbitration strategy.

### 4.7 `ErrorPayload`
- `error_code` (`string`): Standardized error identifier from `ErrorCode` enum.
- `error_message` (`string`): Descriptive human-readable explanation.
- `details` (`dict`): Contextual key-values (field name, invalid value, line number).
- `retryable` (`bool`): Indicates if the operation can be retried.

### 4.8 `FinalResultPayload`
- `incident_id` (`string`): Incident identifier.
- `primary_root_cause` (`CauseCode`): Consensus diagnosis.
- `confidence` (`float`, 0.0 to 1.0): Final system confidence.
- `affected_devices` (`list[string]`): All degraded or impacted devices.
- `affected_segment` (`string`, optional): Impacted network segment.
- `remediation_recommendations` (`list[string]`): Actionable steps for campus network engineers.
- `summary` (`string`): Concise executive diagnostic summary.
- `contributing_findings` (`list[FindingPayload]`): Subsystem findings supporting the verdict.

---

## 5. Cause Code Dictionary (`causes.py`)

| Cause Code | Human-Readable Label | Key Diagnostic Indicators | Typical Affected Devices |
| :--- | :--- | :--- | :--- |
| `LINK_CONGESTION` | Link Congestion & Bandwidth Saturation | `link_utilization_pct > 90%`, high `queue_drops`, elevated `latency_ms` and `jitter_ms`. | Distribution Switches, Core Routers, Uplinks |
| `WEAK_WIFI_SIGNAL` | Weak Wi-Fi Signal / Low RF Coverage | `rssi_dbm < -80 dBm`, `snr_db < 15 dB`, `retransmission_pct > 15%`, packet loss on AP. | Access Points (`AP_HOSTEL_*`, `AP_LHC_*`) |
| `INTERFACE_FAULT` | Physical / Data-Link Interface Fault | Elevated `interface_errors` (CRC/FCS errors), intermittent `packet_loss_pct`, normal CPU. | Access Switches, Ethernet Ports |
| `DEVICE_CPU_OVERLOAD` | Device Control/Data Plane CPU Overload | `cpu_pct > 90%`, `memory_pct > 85%`, internal queue drops, elevated response latency. | Access Switches, Routers |
| `UPSTREAM_CONGESTION` | Upstream ISP / NKN Gateway Bottleneck | `GW_NKN_ISP` utilization $> 95\%$, uniform latency elevation across all campus downstream segments. | Gateway Uplink (`GW_NKN_ISP`) |
| `DNS_FAILURE` | DNS Server Resolution Failure / High Latency | `dns_resolution_ms > 1000 ms` or timeouts; ping/IP connectivity remains healthy. | DNS Servers (`SRV_DNS_01`, `SRV_DNS_02`) |
| `DHCP_FAILURE` | DHCP Lease Exhaustion or Handshake Failure | `dhcp_failures > 25`, inability of clients to renew IP addresses; server status degraded. | DHCP Servers (`SRV_DHCP_01`, `SRV_DHCP_02`) |
| `HARDWARE_FAILURE` | Critical Hardware Degradation / Crash | CPU at 99.9%, packet loss $> 20\%$, `device_status: "down"` or high interface drops. | Any Switch or Router |
| `NORMAL` | Healthy Operational Baseline | All metrics within nominal ranges, `packet_loss_pct: 0.0%`, `device_status: "up"`. | All Campus Devices |
| `UNKNOWN` | Unresolved / Insufficient Telemetry | Data completeness $< 0.5$, conflicting metrics, or borderline non-conclusive observations. | Any Device |

---

## 6. Canonical Metric Dictionary

All metrics ingested into NetCoop AI are mapped to this canonical dictionary:

| Metric Name | Canonical Unit | Valid Range | Healthy Baseline | Warning Threshold | Critical Threshold | Description |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `latency_ms` | `ms` | $[0.0, 10000.0]$ | $12.0$ | $80.0$ | $250.0$ | Round-trip network delay in milliseconds |
| `jitter_ms` | `ms` | $[0.0, 5000.0]$ | $2.5$ | $20.0$ | $60.0$ | Variance in packet arrival timing in milliseconds |
| `packet_loss_pct` | `%` | $[0.0, 100.0]$ | $0.0$ | $1.5$ | $5.0$ | Percentage of transmitted packets lost |
| `throughput_mbps` | `Mbps` | $[0.0, 100000.0]$| $450.0$ | $850.0$ | $980.0$ | Interface data transmission rate in Mbps |
| `bandwidth_mbps` | `Mbps` | $[0.0, 100000.0]$| $1000.0$ | N/A | N/A | Nominal interface link bandwidth capacity |
| `link_utilization_pct` | `%` | $[0.0, 100.0]$ | $35.0$ | $80.0$ | $95.0$ | Utilization percentage of link capacity |
| `cpu_pct` | `%` | $[0.0, 100.0]$ | $25.0$ | $75.0$ | $90.0$ | Device processor utilization percentage |
| `memory_pct` | `%` | $[0.0, 100.0]$ | $40.0$ | $80.0$ | $92.0$ | Device RAM memory utilization percentage |
| `queue_drops` | `packets` | $[0, 10000000]$ | $0$ | $10$ | $100$ | Packets discarded due to buffer overflow |
| `interface_errors` | `errors` | $[0, 10000000]$ | $0$ | $5$ | $50$ | Physical framing, CRC, or runt errors |
| `rssi_dbm` | `dBm` | $[-120.0, 0.0]$ | $-55.0$ | $-75.0$ | $-85.0$ | Received Wi-Fi signal strength in dBm |
| `snr_db` | `dB` | $[0.0, 100.0]$ | $35.0$ | $20.0$ | $12.0$ | Signal-to-Noise ratio in decibels |
| `retransmission_pct` | `%` | $[0.0, 100.0]$ | $1.0$ | $8.0$ | $20.0$ | Retransmitted frames / packets percentage |
| `device_status` | `enum` | `["up", "down", "degraded"]` | `"up"` | `"degraded"` | `"down"` | Operational state of the node |
| `dns_resolution_ms` | `ms` | $[0.0, 30000.0]$ | $15.0$ | $150.0$ | $1000.0$ | Standard campus DNS query response time |
| `dhcp_failures` | `events` | $[0, 100000]$ | $0$ | $5$ | $25$ | Failed or timed-out DHCP leasing requests |

---

## 7. Schema Versioning & Interoperability Rules

### 7.1 Versioning Principles
- **Canonical Version**: `"1.0"`. Fully typed, validated with Pydantic v2.
- **Legacy Compatibility**: `"0.9"`. Legacy flat sensor telemetry format. Supported via transparent normalizer translation.
- **Strict Version Checking**: Unknown or unapproved schema versions (e.g. `"2.5-beta"`, `"0.8"`) are **never guessed**. The system immediately flags `ERR_UNKNOWN_SCHEMA_VERSION`.

### 7.2 Schema 0.9 Flat Alias Mapping
| Legacy 0.9 Field | Canonical 1.0 Metric | Conversion Rule |
| :--- | :--- | :--- |
| `lat` / `rtt` | `latency_ms` | Direct map |
| `util` | `link_utilization_pct` | Direct map |
| `loss` | `packet_loss_pct` | Direct map |
| `signal` | `rssi_dbm` | Direct map |
| `cpu` | `cpu_pct` | Direct map |
| `mem` | `memory_pct` | Direct map |
| `drops` | `queue_drops` | Cast to integer |
| `errs` | `interface_errors` | Cast to integer |
| `bw` | `bandwidth_mbps` | Direct map |
| `tput` | `throughput_mbps` | Direct map |
| `retrans` | `retransmission_pct` | Direct map |
| `dns_ms` | `dns_resolution_ms` | Direct map |
| `dhcp_err` | `dhcp_failures` | Cast to integer |
| `dev` | `device_id` | Envelope identifier |
| `time` | `timestamp` | Envelope timestamp |

---

## 8. Telemetry Normalizer Specification (`normalizer.py`)

The Normalizer accepts heterogeneous telemetry and standardizes it into canonical representation while generating an audit trail:

### 8.1 Unit Detection & Conversion Equations
1. **Time Units $\to$ Milliseconds (`ms`)**:
   - Seconds (`s`, `sec`, `seconds`): $\text{val}_{\text{ms}} = \text{val}_{\text{s}} \times 1000.0$
   - Microseconds (`us`, `µs`): $\text{val}_{\text{ms}} = \text{val}_{\text{us}} / 1000.0$
2. **Throughput / Bandwidth Units $\to$ Megabits per second (`Mbps`)**:
   - Gigabits per second (`Gbps`): $\text{val}_{\text{Mbps}} = \text{val}_{\text{Gbps}} \times 1000.0$
   - Kilobits per second (`kbps`): $\text{val}_{\text{Mbps}} = \text{val}_{\text{kbps}} / 1000.0$
   - Bits per second (`bps`): $\text{val}_{\text{Mbps}} = \text{val}_{\text{bps}} / 1,000,000.0$
3. **Fractions $\to$ Percentages (`%`)**:
   - Decimal fractions ($0.0 \le f \le 1.0$ with unit `"fraction"` or field suffix `_ratio`/`_fraction`): $\text{val}_{\%} = f \times 100.0$

### 8.2 Audit Log Entry Structure
Every conversion generates a `ConversionLogEntry`:
```json
{
  "field_original": "latency_s",
  "canonical_field": "latency_ms",
  "original_value": 0.22,
  "original_unit": "s",
  "canonical_value": 220.0,
  "canonical_unit": "ms",
  "rule": "unit_convert_s_to_ms"
}
```

### 8.3 Completeness Scoring & Ambiguity Penalties
When a field cannot be parsed or possesses ambiguous units:
- Base Completeness: $1.0$
- Penalty per unconvertible/ambiguous field: $-0.10$
- Penalty per missing expected telemetry metric: $-0.05$
- Completeness score is clamped to $[0.0, 1.0]$.

---

## 9. Structured Validator Error Codes (`validators.py`)

The validator never raises raw uncaught exceptions to caller routines. It outputs a `ValidationResult` containing structured `ValidationIssue` entries.

The system supports canonical error codes (such as `CORRUPTED_JSON` and `EMPTY_INPUT`) and their backward-compatible aliases with the `ERR_` prefix:

| Canonical Error Code | Legacy / Alias | Severity | Trigger Condition | Recommended Recovery Action |
| :--- | :--- | :--- | :--- | :--- |
| `CORRUPTED_JSON` | `ERR_CORRUPTED_JSON` | ERROR | Malformed syntax, invalid JSON tokens, or unclosed braces/brackets. | Reject frame; log parser decoding failure including line and column. |
| `EMPTY_INPUT` | `ERR_EMPTY_INPUT` | ERROR | Empty payload, whitespace string, `null`, `[]`, `{}`, or input with zero records or zero recognized devices. | Discard and log heartbeat warning; return completeness 0.0. |
| `MISSING_REQUIRED_FIELD` | `ERR_MISSING_REQUIRED_FIELD` | ERROR | Mandatory field (`device_id`, `timestamp`, envelope headers) is absent. | Discard or request retransmission from source. |
| `WRONG_TYPE` | `ERR_WRONG_TYPE` | ERROR | Field datatype violates specification (e.g. string where float required). | Reject record; check sensor serialization. |
| `OUT_OF_RANGE` | `ERR_OUT_OF_RANGE` | ERROR | Numeric value violates canonical range bounds (e.g. utilization $> 100\%$, latency $< 0$). | Flag telemetry corruption or miscalibration. |
| `NAN_OR_NULL` | `ERR_NAN_OR_NULL` | ERROR | Field contains NaN, Infinity, or None where numeric value is mandatory. | Impute from prior step or discard sample. |
| `TIMESTAMP_DUPLICATE` | `ERR_TIMESTAMP_DUPLICATE` | ERROR | Multiple records for the same device carry identical timestamps. | Deduplicate by discarding identical copy. |
| `TIMESTAMP_OUT_OF_ORDER` | `ERR_TIMESTAMP_OUT_OF_ORDER` | ERROR | Chronological sequence reversed in time-series batch. | Re-sort batch by timestamp ascending. |
| `STALE_DATA` | `ERR_STALE_DATA` | ERROR | Record timestamp older than configured stale window ($> 300\text{ s}$). | Exclude from real-time diagnosis; mark stale. |
| `UNKNOWN_DEVICE_ID` | `ERR_UNKNOWN_DEVICE_ID` | ERROR | Device ID does not exist in IIT Bhubaneswar campus topology graph. | Flag unregistered device / rogue hardware. |
| `UNKNOWN_SCHEMA_VERSION`| `ERR_UNKNOWN_SCHEMA_VERSION` | ERROR | Schema version is not in `["1.0", "0.9"]`. Versions are never guessed. | Reject message; request sender upgrade. |
| `MIXED_UNITS` | `ERR_MIXED_UNITS` | ERROR | Incompatible unit declarations in the same telemetry batch. | Normalize per-record before batching. |

---

## 10. Concrete Protocol Message Examples

### 10.1 `task_request` Example
```json
{
  "message_id": "b182cb0e-b2d9-4b68-bf09-f64f33b1e301",
  "incident_id": "INC-2026-1042",
  "schema_version": "1.0",
  "timestamp": "2026-10-31T10:05:00Z",
  "sender": "orchestrator",
  "recipient": "wifi_subsystem_agent",
  "message_type": "task_request",
  "correlation_id": null,
  "payload": {
    "task_id": "TASK-WIFI-DIAG-01",
    "target_device_ids": [
      "AP_HOSTEL_A_FL1",
      "AP_HOSTEL_A_FL2"
    ],
    "target_segment": "hostel_wifi",
    "window_start": "2026-10-31T09:55:00Z",
    "window_end": "2026-10-31T10:05:00Z",
    "parameters": {
      "rssi_threshold_dbm": -80.0,
      "retransmission_threshold_pct": 15.0
    }
  }
}
```

### 10.2 `finding` Example
```json
{
  "message_id": "c293dc1f-c3ea-5c79-cf10-075044c2f412",
  "incident_id": "INC-2026-1042",
  "schema_version": "1.0",
  "timestamp": "2026-10-31T10:06:12Z",
  "sender": "wifi_subsystem_agent",
  "recipient": "orchestrator",
  "message_type": "finding",
  "correlation_id": "b182cb0e-b2d9-4b68-bf09-f64f33b1e301",
  "payload": {
    "agent": "wifi_subsystem_agent",
    "scope": {
      "device_ids": ["AP_HOSTEL_A_FL2"],
      "segment": "hostel_wifi"
    },
    "hypothesis_candidates": [
      {
        "cause_code": "WEAK_WIFI_SIGNAL",
        "score": 0.94,
        "supporting_metrics": [
          {
            "metric": "rssi_dbm",
            "value": -86.5,
            "unit": "dBm",
            "baseline": -55.0,
            "interpretation": "Severe signal attenuation 31.5 dBm below healthy baseline"
          },
          {
            "metric": "retransmission_pct",
            "value": 34.2,
            "unit": "%",
            "baseline": 1.0,
            "interpretation": "Massive frame retry rate due to degraded RF signal"
          }
        ],
        "contradicting_metrics": []
      },
      {
        "cause_code": "LINK_CONGESTION",
        "score": 0.12,
        "supporting_metrics": [],
        "contradicting_metrics": [
          {
            "metric": "link_utilization_pct",
            "value": 28.4,
            "unit": "%",
            "baseline": 35.0,
            "interpretation": "Ethernet backhaul utilization is low and unstressed"
          }
        ]
      }
    ],
    "data_quality": {
      "completeness": 0.95,
      "stale_fields": [],
      "missing_fields": [],
      "assumptions": ["Client distance from AP exceeds 30m with concrete wall obstruction"]
    },
    "confidence": 0.92
  }
}
```

### 10.3 `evidence_query` Example
```json
{
  "message_id": "d304ed20-d4fb-6d80-d021-186155d3a523",
  "incident_id": "INC-2026-1042",
  "schema_version": "1.0",
  "timestamp": "2026-10-31T10:06:30Z",
  "sender": "wifi_subsystem_agent",
  "recipient": "switch_subsystem_agent",
  "message_type": "evidence_query",
  "correlation_id": "b182cb0e-b2d9-4b68-bf09-f64f33b1e301",
  "payload": {
    "query_id": "QRY-UPLINK-SWITCH-01",
    "requested_by": "wifi_subsystem_agent",
    "device_ids": ["ACC_SW_HOSTEL_A"],
    "metrics": ["link_utilization_pct", "interface_errors", "queue_drops"],
    "start_time": "2026-10-31T09:55:00Z",
    "end_time": "2026-10-31T10:05:00Z",
    "filter_criteria": {}
  }
}
```

### 10.4 `evidence_response` Example
```json
{
  "message_id": "e415fe31-e50c-7e91-e132-297266e4b634",
  "incident_id": "INC-2026-1042",
  "schema_version": "1.0",
  "timestamp": "2026-10-31T10:06:45Z",
  "sender": "switch_subsystem_agent",
  "recipient": "wifi_subsystem_agent",
  "message_type": "evidence_response",
  "correlation_id": "d304ed20-d4fb-6d80-d021-186155d3a523",
  "payload": {
    "query_id": "QRY-UPLINK-SWITCH-01",
    "device_telemetry": [
      {
        "device_id": "ACC_SW_HOSTEL_A",
        "timestamp": "2026-10-31T10:00:00Z",
        "link_utilization_pct": 28.4,
        "interface_errors": 0,
        "queue_drops": 0
      },
      {
        "device_id": "ACC_SW_HOSTEL_A",
        "timestamp": "2026-10-31T10:01:00Z",
        "link_utilization_pct": 29.1,
        "interface_errors": 0,
        "queue_drops": 0
      }
    ],
    "matched_records_count": 2,
    "data_truncated": false
  }
}
```

### 10.5 `conflict_notice` Example
```json
{
  "message_id": "f5260f42-f61d-8f02-f243-308377f5c745",
  "incident_id": "INC-2026-1042",
  "schema_version": "1.0",
  "timestamp": "2026-10-31T10:07:10Z",
  "sender": "orchestrator",
  "recipient": "broadcast",
  "message_type": "conflict_notice",
  "correlation_id": null,
  "payload": {
    "conflict_id": "CONF-2026-004",
    "conflicting_hypotheses": [
      {
        "agent": "wifi_subsystem_agent",
        "cause_code": "WEAK_WIFI_SIGNAL",
        "confidence": 0.92
      },
      {
        "agent": "traffic_flow_agent",
        "cause_code": "LINK_CONGESTION",
        "confidence": 0.81
      }
    ],
    "contending_agents": [
      "wifi_subsystem_agent",
      "traffic_flow_agent"
    ],
    "disputed_metrics": [
      "link_utilization_pct",
      "throughput_mbps"
    ],
    "resolution_strategy": "Topology-weighted physical layer priority arbitration"
  }
}
```

### 10.6 `error` Example
```json
{
  "message_id": "a6371053-072e-9013-0354-419488a6d856",
  "incident_id": "INC-2026-1042",
  "schema_version": "1.0",
  "timestamp": "2026-10-31T10:07:30Z",
  "sender": "telemetry_ingest_pipeline",
  "recipient": "orchestrator",
  "message_type": "error",
  "correlation_id": "d304ed20-d4fb-6d80-d021-186155d3a523",
  "payload": {
    "error_code": "ERR_UNKNOWN_SCHEMA_VERSION",
    "error_message": "Unsupported schema version: '2.5-beta'. Supported versions are ['0.9', '1.0']. Versions are never guessed.",
    "details": {
      "received_version": "2.5-beta",
      "source_ip": "10.10.11.101"
    },
    "retryable": false
  }
}
```

### 10.7 `final_result` Example
```json
{
  "message_id": "b7482164-183f-a124-1465-520599b7e967",
  "incident_id": "INC-2026-1042",
  "schema_version": "1.0",
  "timestamp": "2026-10-31T10:08:00Z",
  "sender": "orchestrator",
  "recipient": "broadcast",
  "message_type": "final_result",
  "correlation_id": null,
  "payload": {
    "incident_id": "INC-2026-1042",
    "primary_root_cause": "WEAK_WIFI_SIGNAL",
    "confidence": 0.94,
    "affected_devices": [
      "AP_HOSTEL_A_FL2"
    ],
    "affected_segment": "hostel_wifi",
    "remediation_recommendations": [
      "Verify Aruba AP-535 RF transmit power settings on 5 GHz radio.",
      "Check antenna orientation on Hostel Block A 2nd floor corridor.",
      "Dispatch field technician to inspect physical structural attenuation."
    ],
    "summary": "Root cause identified as severe RF signal degradation (RSSI: -86.5 dBm, 34% retransmissions) isolated to AP_HOSTEL_A_FL2. Backhaul switches and distribution links are completely healthy.",
    "contributing_findings": []
  }
}
```
