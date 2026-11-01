# NetCoop AI

### Multi-Agent Network Monitoring, Fault Diagnosis & Intelligent Recovery

NetCoop AI is a multi-agent network intelligence system designed to monitor network conditions, investigate infrastructure issues, correlate evidence from specialized agents, and generate structured diagnosis and recovery recommendations.

Instead of relying on a single monitoring rule or model, NetCoop AI coordinates multiple specialized agents to analyze different aspects of network health and combine their findings into a unified diagnosis.

---

## Table of Contents

1. [Overview](#overview)
2. [Problem Statement](#problem-statement)
3. [Key Features](#key-features)
4. [System Architecture](#system-architecture)
5. [End-to-End Workflow](#end-to-end-workflow)
6. [Technology Stack](#technology-stack)
7. [Repository Structure](#repository-structure)
8. [Installation and Setup](#installation-and-setup)
9. [Running the Application](#running-the-application)
10. [Running Tests](#running-tests)
11. [Understanding the Diagnosis Output](#understanding-the-diagnosis-output)
12. [Configuration and Data](#configuration-and-data)
13. [Troubleshooting](#troubleshooting)
14. [Future Improvements](#future-improvements)
15. [Contributing](#contributing)

---

## 1. Overview

Network environments consist of interconnected devices, links, access points, and infrastructure services. A failure in one component can affect multiple parts of the network.

Traditional monitoring systems often identify symptoms but may not explain the underlying cause.

NetCoop AI addresses this challenge through a coordinated multi-agent architecture.

The system:

- Analyzes network telemetry and infrastructure information.
- Detects abnormal network conditions.
- Investigates potential faults using specialized agents.
- Correlates findings from different agents.
- Resolves conflicting hypotheses using deterministic rules.
- Calculates diagnosis confidence based on available evidence.
- Produces structured reports with recommended recovery actions.

**Core philosophy:**

`Monitor → Detect → Investigate → Correlate → Diagnose → Recommend`

---

## 2. Problem Statement

Network administrators frequently face challenges such as:

- Network congestion and bandwidth saturation.
- Weak Wi-Fi signals and poor RF coverage.
- Interface and connectivity failures.
- DNS and DHCP service problems.
- Device CPU overload.
- Incomplete or conflicting monitoring evidence.

Identifying the actual root cause can require examining several different sources of network information.

NetCoop AI aims to reduce this complexity by distributing investigation tasks across specialized agents and synthesizing their findings.

---

## 3. Key Features

| Feature | Description |
|---|---|
| Multi-agent architecture | Specialized agents investigate different network subsystems. |
| Telemetry analysis | Examines network performance indicators and abnormal conditions. |
| Infrastructure analysis | Investigates device and infrastructure health. |
| Connectivity analysis | Examines connectivity-related symptoms. |
| Fault correlation | Combines findings and resolves competing hypotheses. |
| Evidence orchestration | Requests additional evidence when uncertainty remains. |
| Confidence scoring | Estimates diagnosis confidence using evidence quality and agreement. |
| Structured reporting | Produces standardized diagnosis results. |
| Recovery recommendations | Provides suggested actions associated with diagnosed faults. |
| Web dashboard | Provides a browser-based interface for interacting with the system. |
| Scenario-based testing | Tests diagnosis behavior against sample network incidents. |

---

## 4. System Architecture

NetCoop AI follows a modular, multi-agent architecture.

### Specialized agents

**1. Telemetry Performance Agent**

Examines network performance indicators such as throughput, bandwidth utilization, latency, packet loss, and related telemetry.

**2. Infrastructure Health Agent**

Investigates infrastructure-level problems, including device health, CPU utilization, interface conditions, and hardware-related symptoms.

**3. Connectivity Analysis Agent**

Analyzes connectivity-related evidence to identify possible communication, wireless, and network-service problems.

**4. Fault Correlation Agent**

Acts as the central diagnosis and consensus component.

Its responsibilities include:

- Receiving findings from specialized agents.
- Comparing supporting and conflicting evidence.
- Applying deterministic correlation rules.
- Requesting additional evidence when required.
- Ranking potential root causes.
- Calculating a final confidence score.
- Producing a consolidated diagnosis.

### High-level architecture

```text
                 NETWORK INPUT
                       |
                       v
              DATA / TELEMETRY
                       |
                       v
              DIAGNOSIS ORCHESTRATOR
                       |
          +------------+------------+
          |            |            |
          v            v            v
      TELEMETRY   INFRASTRUCTURE  CONNECTIVITY
       AGENT       HEALTH AGENT    ANALYSIS AGENT
          |            |            |
          +------------+------------+
                       |
                       v
              FAULT CORRELATION
                    AGENT
                       |
             +---------+---------+
             |                   |
             v                   v
       EVIDENCE QUERY       HYPOTHESIS
        IF NEEDED            RANKING
             |                   |
             +---------+---------+
                       |
                       v
               FINAL DIAGNOSIS
                       |
                       v
               STRUCTURED REPORT
                       |
                       v
             DASHBOARD / OUTPUT
```

---

## 5. End-to-End Workflow

The system follows a sequence of coordinated investigation steps.

### Step 1 — Input and monitoring

Network telemetry, infrastructure information, and available topology data are supplied to the system.

The input provides the evidence required for investigation.

### Step 2 — Initial analysis

The diagnosis orchestrator coordinates the specialized agents.

Each agent examines the information relevant to its responsibilities.

### Step 3 — Independent investigation

The specialized agents generate findings about potential network faults.

For example:

- The telemetry agent may identify abnormal bandwidth utilization.
- The infrastructure agent may identify device health problems.
- The connectivity agent may identify communication failures.

### Step 4 — Evidence correlation

The Fault Correlation Agent combines the findings.

It evaluates:

- Agreement between agents.
- Strength of supporting evidence.
- Data completeness.
- Conflicting findings.
- Differences between competing hypotheses.

### Step 5 — Additional evidence collection

When the available evidence is insufficient or conflicting, the correlation agent can dispatch targeted evidence queries.

The additional findings are considered during diagnosis.

### Step 6 — Root-cause identification

The system applies deterministic correlation rules to rank possible root causes and select a diagnosis when the evidence supports one.

It also accounts for uncertainty rather than treating every hypothesis as equally reliable.

### Step 7 — Confidence calculation

The diagnosis confidence considers factors such as:

- Weighted agent support.
- Cross-agent agreement.
- Data completeness.
- Conflicting evidence.
- Margin between competing hypotheses.

Confidence is constrained by safeguards so that limited or conflicting evidence does not automatically produce an unjustifiably strong conclusion.

### Step 8 — Report generation

The system produces a structured final report containing diagnosis information, confidence, supporting findings, and recommended actions.

### Step 9 — Dashboard presentation

The result can be inspected through the web dashboard.

The dashboard provides a convenient interface for viewing the system's diagnosis workflow and outputs.

---

## 6. Technology Stack

The project uses the following technologies:

| Technology | Purpose |
|---|---|
| Python | Core application and agent implementation |
| FastAPI | Backend application and web serving |
| React | Modern dashboard frontend |
| JavaScript / CSS | Frontend behavior and styling |
| JSON | Structured telemetry, topology, and scenario data |
| Pytest | Automated testing |
| Git | Version control |
| GitHub | Source-code hosting and collaboration |

The repository also includes a dependency-free classic frontend alternative.

---

## 7. Repository Structure

The repository is organized into modular components.

```text
netcoop-ai/
│
├── config/
│   └── Configuration files
│
├── data/
│   ├── Topology information
│   └── Sample network scenarios
│
├── docs/
│   └── Project documentation
│
├── frontend/
│   └── Production-built dashboard
│
├── frontend-classic/
│   └── Classic frontend alternative
│
├── netcoop/
│   ├── agents/
│   │   ├── base.py
│   │   ├── correlation_agent.py
│   │   ├── correlation_rules.py
│   │   ├── infrastructure_agent.py
│   │   └── Other specialized agents
│   │
│   ├── data/
│   ├── protocol/
│   ├── reporting/
│   ├── orchestration/
│   └── Application modules
│
├── scripts/
│   └── Utility scripts
│
├── tests/
│   └── Automated test suite
│
├── ui/
│   └── React frontend source
│
├── .gitignore
├── PLAN.md
├── README.md
├── pyproject.toml
└── requirements.txt
```

*Note: This is a logical overview of the repository. Some implementation files and subdirectories are omitted for readability.*

---

## 8. Installation and Setup

Follow these steps to run NetCoop AI locally.

### Prerequisites

Install the following:

- Python 3.10 or a compatible version supported by the project dependencies.
- Git.
- A modern web browser.
- PowerShell, Command Prompt, or a terminal.

### Step 1 — Clone the repository

```bash
git clone https://github.com/Anwesha-codes-10/netcoop-ai.git
```

### Step 2 — Navigate into the project

```bash
cd netcoop-ai
```

### Step 3 — Create a virtual environment

Windows:

```powershell
python -m venv .venv
```

Linux / macOS:

```bash
python3 -m venv .venv
```

### Step 4 — Activate the virtual environment

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Windows Command Prompt:

```cmd
.venv\Scripts\activate.bat
```

Linux / macOS:

```bash
source .venv/bin/activate
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then activate the environment again.

### Step 5 — Upgrade pip

```bash
python -m pip install --upgrade pip
```

### Step 6 — Install dependencies

```bash
pip install -r requirements.txt
```

Wait until the installation completes successfully.

---

## 9. Running the Application

### Start the backend and dashboard

From the project root, with the virtual environment activated:

```bash
python -m netcoop.cli serve
```

Once the server starts, open:

**http://127.0.0.1:8000**

The integrated application should be accessible through the local browser.

Keep the terminal running while using the dashboard.

To stop the server, press:

```text
CTRL + C
```

### Running the frontend separately

The repository also contains:

- `ui/` — React frontend source.
- `frontend/` — production-built frontend.
- `frontend-classic/` — classic frontend alternative.

For normal local usage, start with the integrated server command above. Separate frontend development commands depend on the scripts configured in `ui/package.json`.

---

## 10. Running Tests

NetCoop AI includes automated tests for its modules and diagnosis workflows.

Make sure the virtual environment is activated.

Run the complete test suite:

```bash
python -m pytest -q
```

For more detailed output:

```bash
python -m pytest -v
```

To run an individual test file:

```bash
python -m pytest tests/test_scenarios_e2e.py -v
```

A successful run should finish with a passing test summary and no failed tests.

Tests help verify:

- Agent behavior.
- Correlation logic.
- Diagnosis orchestration.
- Report generation.
- End-to-end sample scenarios.

---

## 11. Understanding the Diagnosis Output

The system generates structured diagnosis results.

Depending on the incident and available evidence, the report can include:

| Field | Meaning |
|---|---|
| Incident ID | Unique identifier for the diagnosis run |
| Status | Overall diagnosis status |
| Root cause | Identified or suspected network fault |
| Cause code | Standardized root-cause identifier |
| Confidence | Estimated strength of the diagnosis |
| Evidence | Findings supporting the diagnosis |
| Recommended action | Suggested recovery or remediation |
| Message trace | Reference for tracing agent communication |

A diagnosis should always be interpreted in the context of the available evidence.

A high confidence score does not independently guarantee that a real-world network fault has been resolved.

---

## 12. Configuration and Data

### Configuration

The `config/` directory contains project configuration.

Review the configuration files before changing agent behavior, scoring weights, or diagnosis rules.

### Data

The `data/` directory contains the project's topology information and sample scenarios.

Sample scenarios can be used to understand how the system processes different network conditions.

Avoid modifying the original sample data when conducting experiments. Create separate test inputs when needed.

---

## 13. Troubleshooting

### Problem 1 — Python is not recognized

Check the installation:

```bash
python --version
```

If the command is unavailable, install Python and ensure it is added to the system PATH.

### Problem 2 — Virtual environment activation fails

For PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

### Problem 3 — Missing dependencies

Run:

```bash
pip install -r requirements.txt
```

### Problem 4 — Port 8000 is already in use

Another application may already be using port 8000.

On Windows, identify the process:

```powershell
netstat -ano | findstr :8000
```

Stop only the process you have identified and confirmed is safe to close, or configure the application to use another supported port.

### Problem 5 — Dashboard does not load

1. Confirm that the backend server started successfully.
2. Check the terminal for errors.
3. Verify that you are visiting `http://127.0.0.1:8000`.
4. Confirm that the frontend build is present.
5. Check the browser console for frontend errors.

### Problem 6 — Tests fail

Run the failing test with detailed output:

```bash
python -m pytest tests/test_scenarios_e2e.py -v
```

Review the traceback and check the relevant agent, configuration, or sample input before changing the implementation.

---

## 14. Future Improvements

Potential areas for further development include:

- Integration with live network monitoring sources.
- More specialized agents for additional network fault categories.
- Improved evidence collection and diagnosis explainability.
- Historical incident analysis.
- More advanced recovery recommendation workflows.
- Human approval and execution safeguards for network changes.
- Real-time monitoring and dashboard updates.
- Expanded integration and stress testing.

---

## 15. Contributing

Contributions and suggestions are welcome.

### Suggested workflow

1. Fork the repository.
2. Clone your fork.
3. Create a feature branch.
4. Make focused changes.
5. Run the automated tests.
6. Commit your changes with a clear message.
7. Open a pull request describing the changes.

Example:

```bash
git checkout -b feature/your-feature
```

After making changes:

```bash
git add .
git commit -m "Describe your changes"
git push origin feature/your-feature
```

Please avoid committing:

- Virtual environments.
- API keys and credentials.
- `.env` files containing secrets.
- Generated logs.
- Unnecessary build or cache files.

---

## 16. Project Repository

**GitHub:** https://github.com/Anwesha-codes-10/netcoop-ai

To get started:

```bash
git clone https://github.com/Anwesha-codes-10/netcoop-ai.git
cd netcoop-ai
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m netcoop.cli serve
```

Then open **http://127.0.0.1:8000**.

---

## License

Please refer to the repository's license file, if present, for the applicable usage and distribution terms.

---

**NetCoop AI — From network signals to evidence-based diagnosis.**
