# NetCoop AI API Contract

This is the stable contract the frontend is built against. **Field names in this document will not be renamed.** New optional fields may be added later; existing ones keep their name, type and meaning.

All example responses below were captured from a real running server (`netcoop serve`) using the real pipeline. To keep the document readable, long arrays are shortened to their first items (marked `... N more item(s) omitted in this document`) and very long strings are cut; the live API returns everything. Incident ids, timestamps and confidence values change from run to run.

## Conventions

- Same origin, no CORS. All endpoints live under `/api`. Interactive docs: `/docs`.
- JSON in, JSON out (except `report.md`, which is `text/markdown`).
- **Errors** are always `{"error": <code>, "detail": <text>}`; never an HTML page or a traceback.
- Status codes: `400` bad request body (not JSON / empty), `404` unknown scenario/incident/route, `405` wrong method, `413` request body over 5 MB, `422` request validation failed, `500` unexpected server error (`internal_error`).
- A diagnosis whose **input is bad** (corrupted JSON, unknown schema version, empty text) is **not** an HTTP error: it returns `200` with `report.status == "invalid_input"` and a populated `error` object.
- `report.status` is one of `diagnosed`, `insufficient_evidence`, `partial`, `invalid_input`. Only `diagnosed` asserts a root cause.
- Incident ids match `^INC-[A-Za-z0-9_-]+$`; other values on incident routes return `422`.
- Request bodies larger than 5 MB are rejected with `413` (the limit is applied to the bytes actually received, not only to the `Content-Length` header).

## Endpoint index

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness and version |
| GET | `/api/scenarios` | Built-in scenarios |
| GET | `/api/scenarios/{name}/telemetry` | Sample telemetry of a scenario (for charts) |
| GET | `/api/topology` | Campus topology as node/edge JSON |
| POST | `/api/diagnose` | Run the multi-agent diagnosis |
| GET | `/api/incidents` | Saved incidents, newest first |
| GET | `/api/incidents/{id}/trace` | Message trace of an incident |
| GET | `/api/incidents/{id}/report.json` | Final report of an incident |
| GET | `/api/incidents/{id}/report.md` | Final report as Markdown |
| POST | `/api/benchmark` | Run every scenario and score it |

## GET /api/health

`HTTP 200`, `Content-Type: application/json`

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

## GET /api/scenarios

`kind` is `root_cause` or `interoperability`. `expected_cause` is a cause code, or `null` for scenarios that are meant to be rejected or partial.

`HTTP 200`, `Content-Type: application/json`

```json
[
  {
    "name": "normal",
    "description": "All campus devices operating within nominal baseline parameters",
    "expected_cause": "NORMAL",
    "kind": "root_cause"
  },
  {
    "name": "link_congestion",
    "description": "Severe link saturation and queue drops on DIST_SW_HOSTEL uplink",
    "expected_cause": "LINK_CONGESTION",
    "kind": "root_cause"
  },
  "... 12 more item(s) omitted in this document"
]
```

## GET /api/scenarios/{name}/telemetry

`records` is the telemetry list exactly as it would be uploaded. For the deliberately malformed `corrupted_json` scenario, `valid_json` is `false`, `records` is `null` and `raw` holds the broken text. Unknown name: `404 scenario_not_found`.

Valid scenario:

`HTTP 200`, `Content-Type: application/json`

```json
{
  "scenario": "link_congestion",
  "valid_json": true,
  "records": [
    {
      "device_id": "DIST_SW_HOSTEL",
      "device_type": "distribution_switch",
      "timestamp": "2026-10-31T10:00:00+00:00",
      "status": "degraded",
      "schema_version": "1.0",
      "metrics": {
        "bandwidth_mbps": 10000.0,
        "latency_ms": 158.03,
        "jitter_ms": 73.72,
        "packet_loss_pct": 3.13,
        "link_utilization_pct": 92.76,
        "cpu_pct": 18.53,
        "memory_pct": 38.38,
        "queue_drops": 268,
        "interface_errors": 0,
        "retransmission_pct": 0.13,
        "device_status": "degraded",
        "throughput_mbps": 9276.0
      }
    },
    {
      "device_id": "DIST_SW_HOSTEL",
      "device_type": "distribution_switch",
      "timestamp": "2026-10-31T10:01:00+00:00",
      "status": "degraded",
      "schema_version": "1.0",
      "metrics": {
        "bandwidth_mbps": 10000.0,
        "latency_ms": 251.1,
        "jitter_ms": 40.6,
        "packet_loss_pct": 1.4,
        "link_utilization_pct": 94.2,
        "cpu_pct": 30.32,
        "memory_pct": 45.05,
        "queue_drops": 829,
        "interface_errors": 0,
        "retransmission_pct": 0.49,
        "device_status": "degraded",
        "throughput_mbps": 9420.0
      }
    },
    "... 13 more item(s) omitted in this document"
  ],
  "raw": null
}
```

Malformed scenario:

`HTTP 200`, `Content-Type: application/json`

```json
{
  "scenario": "corrupted_json",
  "valid_json": false,
  "records": null,
  "raw": "{\n  \"schema_version\": \"1.0\",\n  \"device_id\": \"DIST_SW_HOSTEL\",\n  \"timestamp\": \"2026-10-31T10:00:00Z\",\n  \"metrics\": {\n    \"latency_ms\": 150.0,\n    \"packet_loss_pct\": 2.5,\n    \"link_utilization_pct\": 92.0\n  // MALFORMED_JSON_SYNTAX_ERROR: unclosed brace and invalid comment\n"
}
```

## GET /api/topology

Nodes and edges of the campus network (`edges` carry `source` and `target`).

`HTTP 200`, `Content-Type: application/json`

```json
{
  "name": "IIT Bhubaneswar Campus Network",
  "version": "1.0",
  "node_count": 22,
  "edge_count": 26,
  "nodes": [
    {
      "device_id": "ACC_SW_CSE_01",
      "device_type": "access_switch",
      "segment": "dept_ethernet",
      "location": "School of Electrical Sciences (CSE Wing)",
      "ip_address": "10.10.21.1",
      "bandwidth_mbps": 1000.0,
      "model": "Cisco Catalyst 9200",
      "id": "ACC_SW_CSE_01"
    },
    {
      "device_id": "ACC_SW_ECE_01",
      "device_type": "access_switch",
      "segment": "dept_ethernet",
      "location": "School of Electrical Sciences (ECE Wing)",
      "ip_address": "10.10.22.1",
      "bandwidth_mbps": 1000.0,
      "model": "Cisco Catalyst 9200",
      "id": "ACC_SW_ECE_01"
    },
    "... 20 more item(s) omitted in this document"
  ],
  "edges": [
    {
      "bandwidth_mbps": 10000.0,
      "medium": "fiber",
      "interface_u": "HundredGigE0/0/1",
      "interface_v": "TenGigE1/0/1",
      "source": "GW_NKN_ISP",
      "target": "CORE_RTR_01"
    },
    {
      "bandwidth_mbps": 10000.0,
      "medium": "fiber",
      "interface_u": "HundredGigE0/0/2",
      "interface_v": "TenGigE1/0/1",
      "source": "GW_NKN_ISP",
      "target": "CORE_RTR_02"
    },
    "... 24 more item(s) omitted in this document"
  ]
}
```

## POST /api/diagnose

Body: **exactly one** of `scenario` (name of a built-in scenario) or `telemetry` (a JSON object/array, or raw JSON text such as an uploaded file's contents). `topology` (node/edge object as returned by `GET /api/topology`) is optional. Unknown fields are rejected with `422`.

Response fields: `report` (the final report), `trace` (every agent message of this incident, in order), `markdown` (the report rendered as Markdown) and `error` (`null`, or `{code, detail, line, column}` when `report.status` is `invalid_input`; `line`/`column` are `null` when not applicable). `trace[].summary` is the one-line text produced by the message bus summariser (`sender -> recipient | message_type | details`). `trace[].payload` is the full message payload.

Request `{"scenario": "link_congestion"}` (trace payloads shortened):

`HTTP 200`, `Content-Type: application/json`

```json
{
  "report": {
    "incident_id": "INC-B1BC6BA2",
    "status": "diagnosed",
    "suspected_root_cause": "Link Congestion & Bandwidth Saturation",
    "root_cause_code": "LINK_CONGESTION",
    "confidence": 0.831,
    "confidence_category": "high",
    "affected_devices": [
      "DIST_SW_HOSTEL",
      "ACC_SW_HOSTEL_A",
      "... 1 more item(s) omitted in this document"
    ],
    "affected_segments": [
      "hostel_wifi"
    ],
    "supporting_evidence": [
      {
        "metric": "link_utilization_pct",
        "value": 94.86,
        "unit": "%",
        "baseline": 35.0,
        "interpretation": "DIST_SW_HOSTEL: Link utilization critically saturated at 94.9%",
        "device_id": "DIST_SW_HOSTEL",
        "source_agent": "telemetry_agent"
      },
      {
        "metric": "throughput_mbps",
        "value": 9485.6,
        "unit": "Mbps",
        "baseline": 450.0,
        "interpretation": "DIST_SW_HOSTEL: Throughput (9485.6 Mbps) saturated near link capacity (10000 Mbps)",
        "device_id": "DIST_SW_HOSTEL",
        "source_agent": "telemetry_agent"
      },
      "... 3 more item(s) omitted in this document"
    ],
    "alternative_causes": [
      {
        "cause": "WEAK_WIFI_SIGNAL",
        "score": 0.75,
        "why_less_likely": "Lower correlation confidence score (0.75) compared to primary root cause (0.83)."
      },
      {
        "cause": "INTERFACE_FAULT",
        "score": 0.5,
        "why_less_likely": "Lower correlation confidence score (0.50) compared to primary root cause (0.83)."
      },
      "... 1 more item(s) omitted in this document"
    ],
    "recommended_actions": [
      {
        "priority": 1,
        "action": "Apply egress QoS rate-limiting and buffer threshold reservation on congested interface.",
        "rationale": "Mitigates buffer overflows and reduces queue drop latency spikes for real-time traffic.",
        "requires_human_review": true
      },
      {
        "priority": 2,
        "action": "Schedule link bandwidth capacity expansion from 10G to 20G with network operations.",
        "rationale": "Relieves steady-state link bandwidth saturation under peak student traffic loads.",
        "requires_human_review": true
      }
    ],
    "evidence_sources": [
      "connectivity_agent",
      "infrastructure_agent",
      "... 1 more item(s) omitted in this document"
    ],
    "limitations": [
      "This diagnosis is generated from synthetic/supplied telemetry and requires human review and confirmation prior to operational changes."
    ],
    "conflicts_resolved": [],
    "data_quality": {
      "completeness": 1.0,
      "stale_fields": [],
      "missing_fields": [],
      "assumptions": []
    },
    "normalization_log": [
      {
        "field_original": "bandwidth_mbps",
        "canonical_field": "bandwidth_mbps",
        "original_value": 10000.0,
        "original_unit": "Mbps",
        "canonical_value": 10000.0,
        "canonical_unit": "Mbps",
        "rule": "identity"
      },
      {
        "field_original": "latency_ms",
        "canonical_field": "latency_ms",
        "original_value": 158.03,
        "original_unit": "ms",
        "canonical_value": 158.03,
        "canonical_unit": "ms",
        "rule": "identity"
      },
      "... 188 more item(s) omitted in this document"
    ],
    "agent_status": {
      "telemetry_agent": "ok",
      "infrastructure_agent": "ok",
      "connectivity_agent": "ok"
    },
    "simulated_remediation_preview": "SIMULATED: Reallocate egress queue buffer threshold on saturated link.\nSIMULATED: Enforce traffic policing profile for bulk background traffic.",
    "message_trace_ref": "TRACE-INC-B1BC6BA2"
  },
  "trace": [
    {
      "index": 0,
      "timestamp": "2026-10-31T23:39:28.987369Z",
      "sender": "orchestrator",
      "recipient": "telemetry_agent",
      "message_type": "task_request",
      "summary": "orchestrator -> telemetry_agent | task_request | task=analyze",
      "payload": {
        "task_id": "8bb6cfba-2eed-46ac-84b9-39b4f2d829ec",
        "task": "analyze",
        "target_device_ids": [
          "DIST_SW_HOSTEL",
          "ACC_SW_HOSTEL_A",
          "... 1 more item(s) omitted in this document"
        ],
        "target_segment": null,
        "window_start": null,
        "window_end": null,
        "parameters": {},
        "telemetry": {
          "DIST_SW_HOSTEL": [
            {
              "device_id": "DIST_SW_HOSTEL",
              "timestamp": "2026-10-31T10:00:00+00:00",
              "status": "degraded",
              "schema_version": "1.0",
              "device_type": "distribution_switch",
              "bandwidth_mbps": 10000.0,
              "latency_ms": 158.03,
              "jitter_ms": 73.72,
              "packet_loss_pct": 3.13,
              "link_utilization_pct": 92.76,
              "cpu_pct": 18.53,
              "memory_pct": 38.38,
              "queue_drops": 268,
              "interface_errors": 0,
              "retransmission_pct": 0.13,
              "device_status": "degraded",
              "throughput_mbps": 9276.0
            },
            {
              "device_id": "DIST_SW_HOSTEL",
              "timestamp": "2026-10-31T10:01:00+00:00",
              "status": "degraded",
              "schema_version": "1.0",
              "device_type": "distribution_switch",
              "bandwidth_mbps": 10000.0,
              "latency_ms": 251.1,
              "jitter_ms": 40.6,
              "packet_loss_pct": 1.4,
              "link_utilization_pct": 94.2,
              "cpu_pct": 30.32,
              "memory_pct": 45.05,
              "queue_drops": 829,
              "interface_errors": 0,
              "retransmission_pct": 0.49,
              "device_status": "degraded",
              "throughput_mbps": 9420.0
            },
            "... 3 more item(s) omitted in this document"
          ],
          "ACC_SW_HOSTEL_A": [
            {
              "device_id": "ACC_SW_HOSTEL_A",
              "timestamp": "2026-10-31T10:00:00+00:00",
              "status": "up",
              "schema_version": "1.0",
              "device_type": "access_switch",
              "bandwidth_mbps": 1000.0,
              "latency_ms": 92.96,
              "jitter_ms": 2.81,
              "packet_loss_pct": 0.0,
              "link_utilization_pct": 33.9,
              "cpu_pct": 20.63,
              "memory_pct": 49.17,
              "queue_drops": 0,
              "interface_errors": 0,
              "retransmission_pct": 0.72,
              "device_status": "up",
              "throughput_mbps": 339.0
            },
            {
              "device_id": "ACC_SW_HOSTEL_A",
              "timestamp": "2026-10-31T10:01:00+00:00",
              "status": "up",
              "schema_version": "1.0",
              "device_type": "access_switch",
              "bandwidth_mbps": 1000.0,
              "latency_ms": 90.85,
              "jitter_ms": 2.08,
              "packet_loss_pct": 0.0,
              "link_utilization_pct": 22.81,
              "cpu_pct": 19.48,
              "memory_pct": 45.75,
              "queue_drops": 0,
              "interface_errors": 0,
              "retransmission_pct": 1.2,
              "device_status": "up",
              "throughput_mbps": 228.1
            },
            "... 3 more item(s) omitted in this document"
          ],
          "AP_HOSTEL_A_FL1": [
            {
              "device_id": "AP_HOSTEL_A_FL1",
              "timestamp": "2026-10-31T10:00:00+00:00",
              "status": "up",
              "schema_version": "1.0",
              "device_type": "access_point",
              "bandwidth_mbps": 1000.0,
              "latency_ms": 91.8,
              "jitter_ms": 3.93,
              "packet_loss_pct": 0.0,
              "link_utilization_pct": 44.34,
              "cpu_pct": 34.93,
              "memory_pct": 46.27,
              "queue_drops": 0,
              "interface_errors": 0,
              "retransmission_pct": 0.63,
              "device_status": "up",
              "throughput_mbps": 443.4,
              "rssi_dbm": -58.7,
              "snr_db": 40.0
            },
            {
              "device_id": "AP_HOSTEL_A_FL1",
              "timestamp": "2026-10-31T10:01:00+00:00",
              "status": "up",
              "schema_version": "1.0",
              "device_type": "access_point",
              "bandwidth_mbps": 1000.0,
              "latency_ms": 91.89,
              "jitter_ms": 2.2,
              "packet_loss_pct": 0.0,
              "link_utilization_pct": 27.55,
              "cpu_pct": 32.65,
              "memory_pct": 41.75,
              "queue_drops": 0,
              "interface_errors": 0,
              "retransmission_pct": 0.76,
              "device_status": "up",
              "throughput_mbps": 275.5,
              "rssi_dbm": -60.7,
              "snr_db": 33.3
            },
            "... 3 more item(s) omitted in this document"
          ]
        },
        "topology": {
          "name": "IIT Bhubaneswar Campus Network",
          "version": "1.0",
          "node_count": 22,
          "edge_count": 26,
          "nodes": [
            {
              "device_id": "ACC_SW_CSE_01",
              "device_type": "access_switch",
              "segment": "dept_ethernet",
              "location": "School of Electrical Sciences (CSE Wing)",
              "ip_address": "10.10.21.1",
              "bandwidth_mbps": 1000.0,
              "model": "Cisco Catalyst 9200",
              "id": "ACC_SW_CSE_01"
            },
            {
              "device_id": "ACC_SW_ECE_01",
              "device_type": "access_switch",
              "segment": "dept_ethernet",
              "location": "School of Electrical Sciences (ECE Wing)",
              "ip_address": "10.10.22.1",
              "bandwidth_mbps": 1000.0,
              "model": "Cisco Catalyst 9200",
              "id": "ACC_SW_ECE_01"
            },
            "... 20 more item(s) omitted in this document"
          ],
          "edges": [
            {
              "bandwidth_mbps": 10000.0,
              "medium": "fiber",
              "interface_u": "HundredGigE0/0/1",
              "interface_v": "TenGigE1/0/1",
              "source": "GW_NKN_ISP",
              "target": "CORE_RTR_01"
            },
            {
              "bandwidth_mbps": 10000.0,
              "medium": "fiber",
              "interface_u": "HundredGigE0/0/2",
              "interface_v": "TenGigE1/0/1",
              "source": "GW_NKN_ISP",
              "target": "CORE_RTR_02"
            },
            "... 24 more item(s) omitted in this document"
          ]
        },
        "data_quality": {
          "completeness": 1.0,
          "stale_fields": [],
          "missing_fields": [],
          "assumptions": []
        },
        "findings": null,
        "agent_status": null,
        "evidence_responses": null,
        "round": 0,
        "correlation_result": null,
        "normalization_log": [
          {
            "field_original": "bandwidth_mbps",
            "canonical_field": "bandwidth_mbps",
            "original_value": 10000.0,
            "original_unit": "Mbps",
            "canonical_value": 10000.0,
            "canonical_unit": "Mbps",
            "rule": "identity"
          },
          {
            "field_original": "latency_ms",
            "canonical_field": "latency_ms",
            "original_value": 158.03,
            "original_unit": "ms",
            "canonical_value": 158.03,
            "canonical_unit": "ms",
            "rule": "identity"
          },
          "... 188 more item(s) omitted in this document"
        ],
        "message_trace_ref": null
      }
    },
    {
      "index": 1,
      "timestamp": "2026-10-31T23:39:28.988553Z",
      "sender": "telemetry_agent",
      "recipient": "correlation_agent",
      "message_type": "finding",
      "summary": "telemetry_agent -> correlation_agent | finding | LINK_CONGESTION 0.97 on 3 device(s)",
      "payload": {
        "agent": "telemetry_agent",
        "scope": {
          "device_ids": [
            "DIST_SW_HOSTEL",
            "ACC_SW_HOSTEL_A",
            "... 1 more item(s) omitted in this document"
          ],
          "segment": "hostel_wifi"
        },
        "hypothesis_candidates": [
          {
            "cause_code": "LINK_CONGESTION",
            "score": 0.97,
            "supporting_metrics": [
              {
                "metric": "link_utilization_pct",
                "value": 94.86,
                "unit": "%",
                "baseline": 35.0,
                "interpretation": "DIST_SW_HOSTEL: Link utilization critically saturated at 94.9%"
              },
              {
                "metric": "throughput_mbps",
                "value": 9485.6,
                "unit": "Mbps",
                "baseline": 450.0,
                "interpretation": "DIST_SW_HOSTEL: Throughput (9485.6 Mbps) saturated near link capacity (10000 Mbps)"
              },
              "... 2 more item(s) omitted in this document"
            ],
            "contradicting_metrics": []
          },
          {
            "cause_code": "WEAK_WIFI_SIGNAL",
            "score": 0.75,
            "supporting_metrics": [
              {
                "metric": "link_utilization_pct",
                "value": 31.1,
                "unit": "%",
                "baseline": 35.0,
                "interpretation": "AP_HOSTEL_A_FL1: Link backhaul utilization is normal/unstressed (31.1%)"
              },
              {
                "metric": "latency_ms",
                "value": 91.74,
                "unit": "ms",
                "baseline": 12.0,
                "interpretation": "AP_HOSTEL_A_FL1: High delay (91.7 ms) caused by Wi-Fi retransmission timeouts"
              }
            ],
            "contradicting_metrics": []
          },
          "... 2 more item(s) omitted in this document"
        ],
        "data_quality": {
          "completeness": 1.0,
          "stale_fields": [],
          "missing_fields": [],
          "assumptions": []
        },
        "confidence": 0.98
      }
    },
    "... 8 more item(s) omitted in this document"
  ],
  "markdown": "# Incident INC-B1BC6BA2 - Diagnosed\n\n**Status:** diagnosed\n\n## Suspected Cause\n\n**Link Congestion & Bandwidth Saturation**\n\n- **Cause code:** LINK_CONGESTION\n- **Confidence:** 0.83 (high)\n\n## Affected Devices and Segments\n\n**Devices:** `DIST_SW_HOSTEL`, `ACC_SW_HOSTEL_A`, `AP_HOSTEL_A_FL1`\n\n**Segments:** `hostel_wifi`\n\n## Supporting Evidence\n\n| Metric | Value | Unit | Device | Source agent | Inter... (5961 more characters omitted in this document)",
  "error": null
}
```

Request `{"scenario": "ambiguous_insufficient"}` returns `report.status == "insufficient_evidence"` with no asserted cause (only the first lines shown):

```json
{
  "report": {
    "incident_id": "INC-63704047",
    "status": "insufficient_evidence",
    "suspected_root_cause": "Undetermined",
    "root_cause_code": "UNKNOWN",
    "confidence": 0.237,
    "confidence_category": "insufficient"
  },
  "error": null
}
```

Corrupted upload (telemetry text that is not valid JSON) returns `200` with an `invalid_input` report and an `error` object with line and column:

`HTTP 200`, `Content-Type: application/json`

```json
{
  "report": {
    "incident_id": "INC-206035D8",
    "status": "invalid_input",
    "suspected_root_cause": "Undetermined",
    "root_cause_code": "UNKNOWN",
    "confidence": 0.0,
    "confidence_category": "insufficient",
    "affected_devices": [],
    "affected_segments": [],
    "supporting_evidence": [],
    "alternative_causes": [],
    "recommended_actions": [
      {
        "priority": 1,
        "action": "Verify telemetry JSON syntax, schema version ('1.0' or '0.9'), and required device/timestamp fields, then re-ingest.",
        "rationale": "Input telemetry payload failed validation constraints.",
        "requires_human_review": true
      }
    ],
    "evidence_sources": [],
    "limitations": [
      "Validation error: Corrupted JSON syntax: Expecting ',' delimiter at line 6 column 1",
      "This diagnosis is generated from synthetic/supplied telemetry and requires human review and confirmation prior to operational changes."
    ],
    "conflicts_resolved": [],
    "data_quality": {
      "completeness": 0.0,
      "missing_fields": [],
      "stale_fields": [],
      "assumptions": [
        "Payload failed schema validation; no telemetry ingested."
      ]
    },
    "normalization_log": [],
    "agent_status": {},
    "simulated_remediation_preview": "SIMULATED: Reject malformed payload and request sensor re-transmission.",
    "message_trace_ref": null
  },
  "trace": [],
  "markdown": "# Incident INC-206035D8 - Invalid input\n\n**Status:** invalid_input\n\n## Suspected Cause\n\nThe telemetry input was rejected during validation. No diagnosis was produced and no root cause is asserted.\n\n## Limitations\n\n- Validation error: Corrupted JSON syntax: Expecting ',' delimiter at line 6 column 1\n- This diagnosis is generated from synthetic/supplied telemetry and requires human review and confir... (733 more characters omitted in this document)",
  "error": {
    "code": "CORRUPTED_JSON",
    "detail": "Corrupted JSON syntax: Expecting ',' delimiter at line 6 column 1",
    "line": 6,
    "column": 1
  }
}
```

Unknown scenario:

`HTTP 404`, `Content-Type: application/json`

```json
{
  "error": "scenario_not_found",
  "detail": "Unknown scenario 'nope'."
}
```

Invalid body (neither `scenario` nor `telemetry`):

`HTTP 422`, `Content-Type: application/json`

```json
{
  "error": "validation_error",
  "detail": "provide exactly one of 'scenario' or 'telemetry'"
}
```

## GET /api/incidents

`HTTP 200`, `Content-Type: application/json`

```json
[
  {
    "incident_id": "INC-206035D8",
    "status": "invalid_input",
    "suspected_root_cause": "Undetermined",
    "root_cause_code": "UNKNOWN",
    "confidence": 0.0,
    "confidence_category": "insufficient",
    "last_stage": "ingested",
    "updated_at": "2026-10-31T23:39:29.519035+00:00"
  },
  {
    "incident_id": "INC-63704047",
    "status": "insufficient_evidence",
    "suspected_root_cause": "Undetermined",
    "root_cause_code": "UNKNOWN",
    "confidence": 0.237,
    "confidence_category": "insufficient",
    "last_stage": "reported",
    "updated_at": "2026-10-31T23:39:29.252947+00:00"
  },
  "... 1 more item(s) omitted in this document"
]
```

## GET /api/incidents/{id}/trace

Same objects as `trace` in the diagnose response. Incidents rejected at ingestion have an empty trace (`[]`).

`HTTP 200`, `Content-Type: application/json`

```json
[
  {
    "index": 0,
    "timestamp": "2026-10-31T23:39:28.987369Z",
    "sender": "orchestrator",
    "recipient": "telemetry_agent",
    "message_type": "task_request",
    "summary": "orchestrator -> telemetry_agent | task_request | task=analyze",
    "payload": {
      "task_id": "8bb6cfba-2eed-46ac-84b9-39b4f2d829ec",
      "task": "analyze",
      "target_device_ids": [
        "DIST_SW_HOSTEL",
        "... 2 more item(s) omitted in this document"
      ],
      "target_segment": null,
      "window_start": null,
      "window_end": null,
      "parameters": {},
      "telemetry": {
        "DIST_SW_HOSTEL": [
          {
            "device_id": "DIST_SW_HOSTEL",
            "timestamp": "2026-10-31T10:00:00+00:00",
            "status": "degraded",
            "schema_version": "1.0",
            "device_type": "distribution_switch",
            "bandwidth_mbps": 10000.0,
            "latency_ms": 158.03,
            "jitter_ms": 73.72,
            "packet_loss_pct": 3.13,
            "link_utilization_pct": 92.76,
            "cpu_pct": 18.53,
            "memory_pct": 38.38,
            "queue_drops": 268,
            "interface_errors": 0,
            "retransmission_pct": 0.13,
            "device_status": "degraded",
            "throughput_mbps": 9276.0
          },
          "... 4 more item(s) omitted in this document"
        ],
        "ACC_SW_HOSTEL_A": [
          {
            "device_id": "ACC_SW_HOSTEL_A",
            "timestamp": "2026-10-31T10:00:00+00:00",
            "status": "up",
            "schema_version": "1.0",
            "device_type": "access_switch",
            "bandwidth_mbps": 1000.0,
            "latency_ms": 92.96,
            "jitter_ms": 2.81,
            "packet_loss_pct": 0.0,
            "link_utilization_pct": 33.9,
            "cpu_pct": 20.63,
            "memory_pct": 49.17,
            "queue_drops": 0,
            "interface_errors": 0,
            "retransmission_pct": 0.72,
            "device_status": "up",
            "throughput_mbps": 339.0
          },
          "... 4 more item(s) omitted in this document"
        ],
        "AP_HOSTEL_A_FL1": [
          {
            "device_id": "AP_HOSTEL_A_FL1",
            "timestamp": "2026-10-31T10:00:00+00:00",
            "status": "up",
            "schema_version": "1.0",
            "device_type": "access_point",
            "bandwidth_mbps": 1000.0,
            "latency_ms": 91.8,
            "jitter_ms": 3.93,
            "packet_loss_pct": 0.0,
            "link_utilization_pct": 44.34,
            "cpu_pct": 34.93,
            "memory_pct": 46.27,
            "queue_drops": 0,
            "interface_errors": 0,
            "retransmission_pct": 0.63,
            "device_status": "up",
            "throughput_mbps": 443.4,
            "rssi_dbm": -58.7,
            "snr_db": 40.0
          },
          "... 4 more item(s) omitted in this document"
        ]
      },
      "topology": {
        "name": "IIT Bhubaneswar Campus Network",
        "version": "1.0",
        "node_count": 22,
        "edge_count": 26,
        "nodes": [
          {
            "device_id": "ACC_SW_CSE_01",
            "device_type": "access_switch",
            "segment": "dept_ethernet",
            "location": "School of Electrical Sciences (CSE Wing)",
            "ip_address": "10.10.21.1",
            "bandwidth_mbps": 1000.0,
            "model": "Cisco Catalyst 9200",
            "id": "ACC_SW_CSE_01"
          },
          "... 21 more item(s) omitted in this document"
        ],
        "edges": [
          {
            "bandwidth_mbps": 10000.0,
            "medium": "fiber",
            "interface_u": "HundredGigE0/0/1",
            "interface_v": "TenGigE1/0/1",
            "source": "GW_NKN_ISP",
            "target": "CORE_RTR_01"
          },
          "... 25 more item(s) omitted in this document"
        ]
      },
      "data_quality": {
        "completeness": 1.0,
        "stale_fields": [],
        "missing_fields": [],
        "assumptions": []
      },
      "findings": null,
      "agent_status": null,
      "evidence_responses": null,
      "round": 0,
      "correlation_result": null,
      "normalization_log": [
        {
          "field_original": "bandwidth_mbps",
          "canonical_field": "bandwidth_mbps",
          "original_value": 10000.0,
          "original_unit": "Mbps",
          "canonical_value": 10000.0,
          "canonical_unit": "Mbps",
          "rule": "identity"
        },
        "... 189 more item(s) omitted in this document"
      ],
      "message_trace_ref": null
    }
  },
  "... 9 more item(s) omitted in this document"
]
```

## GET /api/incidents/{id}/report.json

Same object as `report` in the diagnose response.

`HTTP 200`, `Content-Type: application/json`

```json
{
  "incident_id": "INC-B1BC6BA2",
  "status": "diagnosed",
  "suspected_root_cause": "Link Congestion & Bandwidth Saturation",
  "root_cause_code": "LINK_CONGESTION",
  "confidence": 0.831,
  "confidence_category": "high",
  "affected_devices": [
    "DIST_SW_HOSTEL",
    "ACC_SW_HOSTEL_A",
    "... 1 more item(s) omitted in this document"
  ],
  "affected_segments": [
    "hostel_wifi"
  ],
  "supporting_evidence": [
    {
      "metric": "link_utilization_pct",
      "value": 94.86,
      "unit": "%",
      "baseline": 35.0,
      "interpretation": "DIST_SW_HOSTEL: Link utilization critically saturated at 94.9%",
      "device_id": "DIST_SW_HOSTEL",
      "source_agent": "telemetry_agent"
    },
    {
      "metric": "throughput_mbps",
      "value": 9485.6,
      "unit": "Mbps",
      "baseline": 450.0,
      "interpretation": "DIST_SW_HOSTEL: Throughput (9485.6 Mbps) saturated near link capacity (10000 Mbps)",
      "device_id": "DIST_SW_HOSTEL",
      "source_agent": "telemetry_agent"
    },
    "... 3 more item(s) omitted in this document"
  ],
  "alternative_causes": [
    {
      "cause": "WEAK_WIFI_SIGNAL",
      "score": 0.75,
      "why_less_likely": "Lower correlation confidence score (0.75) compared to primary root cause (0.83)."
    },
    {
      "cause": "INTERFACE_FAULT",
      "score": 0.5,
      "why_less_likely": "Lower correlation confidence score (0.50) compared to primary root cause (0.83)."
    },
    "... 1 more item(s) omitted in this document"
  ],
  "recommended_actions": [
    {
      "priority": 1,
      "action": "Apply egress QoS rate-limiting and buffer threshold reservation on congested interface.",
      "rationale": "Mitigates buffer overflows and reduces queue drop latency spikes for real-time traffic.",
      "requires_human_review": true
    },
    {
      "priority": 2,
      "action": "Schedule link bandwidth capacity expansion from 10G to 20G with network operations.",
      "rationale": "Relieves steady-state link bandwidth saturation under peak student traffic loads.",
      "requires_human_review": true
    }
  ],
  "evidence_sources": [
    "connectivity_agent",
    "infrastructure_agent",
    "... 1 more item(s) omitted in this document"
  ],
  "limitations": [
    "This diagnosis is generated from synthetic/supplied telemetry and requires human review and confirmation prior to operational changes."
  ],
  "conflicts_resolved": [],
  "data_quality": {
    "completeness": 1.0,
    "stale_fields": [],
    "missing_fields": [],
    "assumptions": []
  },
  "normalization_log": [
    {
      "field_original": "bandwidth_mbps",
      "canonical_field": "bandwidth_mbps",
      "original_value": 10000.0,
      "original_unit": "Mbps",
      "canonical_value": 10000.0,
      "canonical_unit": "Mbps",
      "rule": "identity"
    },
    {
      "field_original": "latency_ms",
      "canonical_field": "latency_ms",
      "original_value": 158.03,
      "original_unit": "ms",
      "canonical_value": 158.03,
      "canonical_unit": "ms",
      "rule": "identity"
    },
    "... 188 more item(s) omitted in this document"
  ],
  "agent_status": {
    "telemetry_agent": "ok",
    "infrastructure_agent": "ok",
    "connectivity_agent": "ok"
  },
  "simulated_remediation_preview": "SIMULATED: Reallocate egress queue buffer threshold on saturated link.\nSIMULATED: Enforce traffic policing profile for bulk background traffic.",
  "message_trace_ref": "TRACE-INC-B1BC6BA2"
}
```

## GET /api/incidents/{id}/report.md

`HTTP 200`, `Content-Type: text/markdown; charset=utf-8`

```markdown
# Incident INC-B1BC6BA2 - Diagnosed

**Status:** diagnosed

## Suspected Cause

**Link Congestion & Bandwidth Saturation**

- **Cause code:** LINK_CONGESTION
- **Confidence:** 0.83 (high)

## Affected Devices and Segments

**Devices:** `DIST_SW_HOSTEL`, `ACC_SW_HOSTEL_A`, `AP_HOSTEL_A_FL1`

**Segments:** `hostel_wifi`

## Supporting Evidence

| Metric | Value | Unit | Device | Source agent | Interpretation |
| --- | --- | --- | --- | --- | --- |
| link_utilization_pct | 94.86 | % | DIST_SW_HOSTEL | telemetry_agent | DIST_SW_HOSTEL: Link utilization critically saturated at 94.9% |
| throughput_mbps | 9485.6 | Mbps | DIST_SW_HOSTEL | telemetry_agent | DIST_SW_HOSTEL: Throughput (9485.6 Mbps) saturated near link capacity (10000 Mbps) |
| latency_ms | 206.27 | ms | DIST_SW_HOSTEL | telemetry_agent | DIST_SW_HOSTEL: High latency (206.3 ms) due to buffer queue backlog |
| packet_loss_pct | 2.45 | % | DIST_SW_HOSTEL | telemetry_agent | DIST_SW_HOSTEL: Moderate tail drops/loss (2.4%) consistent with buffer saturation |
| queue_drops | 717 | packets | DIST_SW_HOSTEL | telemetry_agent | DIST_SW_HOSTEL: High buffer overflow packet discards (717 pkts) |

## Alternative Causes

- **WEAK_WIFI_SIGNAL** (score 0.75): Lower correlation confidence score (0.75) compared to primary root cause (0.83).
- **INTERFACE_FAULT** (score 0.50): Lower correlation confidence score (0.50) compared to primary root cause (0.83).
- **NORMAL** (score 0.15): Contradicted by link_utilization_pct (96.8%): DIST_SW_HOSTEL: Metric exceeds critical boundary threshold.

## Recommended Actions

1. **[P1]** Apply egress QoS rate-limiting and buffer threshold reservation on congested interface. *(requires human review)*
   - Rationale: Mitigates buffer overflows and reduces queue drop latency spikes for real-time tr
... (rest of the document omitted here)
```

Unknown incident (also used by `trace` and `report.md`):

`HTTP 404`, `Content-Type: application/json`

```json
{
  "error": "incident_not_found",
  "detail": "No incident 'INC-MISSING1' was found."
}
```

## POST /api/benchmark

No request body. Runs every built-in scenario through the pipeline. `accuracy` is `passed / total` (0 to 1). `expected` is a cause code, or `INVALID_OR_PARTIAL` for scenarios that must be rejected or only partly processed.

`HTTP 200`, `Content-Type: application/json`

```json
{
  "accuracy": 1.0,
  "total": 14,
  "passed": 14,
  "results": [
    {
      "scenario": "normal",
      "description": "All campus devices operating within nominal baseline parameters",
      "expected": "NORMAL",
      "predicted": "NORMAL",
      "status": "diagnosed",
      "confidence": 0.891,
      "confidence_category": "high",
      "passed": true,
      "incident_id": "INC-5A6B1B27"
    },
    {
      "scenario": "link_congestion",
      "description": "Severe link saturation and queue drops on DIST_SW_HOSTEL uplink",
      "expected": "LINK_CONGESTION",
      "predicted": "LINK_CONGESTION",
      "status": "diagnosed",
      "confidence": 0.831,
      "confidence_category": "high",
      "passed": true,
      "incident_id": "INC-E962D1D3"
    },
    "... 12 more item(s) omitted in this document"
  ]
}
```
