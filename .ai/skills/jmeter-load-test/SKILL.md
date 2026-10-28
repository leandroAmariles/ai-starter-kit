---
name: jmeter-load-test
description: Design and execute a JMeter load test against a service endpoint. Use when the user asks for a load test, performance test, or stress test, or to run JMeter. Asks for the target endpoint if not provided; compares results against SLOs and draws conclusions only when the user gives an objective, otherwise reports raw results only.
---

# JMeter Load Test — Usage Instructions

## Purpose

Design, execute, and report a JMeter load test for a service endpoint in one
flow: gather inputs → build the `.jmx` test plan → run in CLI mode → analyze
results → report (and compare against objectives when provided).

## When to use it

Use when the user asks for a "load test", "performance test", "stress test",
or to "run JMeter" against an endpoint. Do not use for functional testing
(use the project's normal test suite) and never run load against an
environment the user did not explicitly authorize.

## Inputs

- **Target endpoint (required)**: base URL, path, HTTP method, required
  headers, and auth token source. If the endpoint is missing or ambiguous,
  STOP and ask the user before doing anything else. Never guess an endpoint
  or invent payloads.
- **Load objective (optional)**: TPS, max latency (p95/p99), max error rate,
  or concurrent users to sustain.
  - If provided: after execution, compare measured results against each
    objective, state pass/fail per criterion, and draw conclusions
    (bottlenecks, regressions, headroom, next steps).
  - If not provided: do NOT invent objectives. Execute the test and report
    the raw results only, offering to define objectives together if the user
    wants a comparison afterwards.
- **Environment**: local or a named shared environment. If the user did not
  name one, ask. Never run load against QA/PRE/PROD without explicit
  approval.
- **Load shape** (users, ramp-up, duration): if the user did not specify one,
  propose a reasonable shape for the endpoint and confirm before executing.

## Steps

1. **Gather the inputs above.** Do not proceed with missing mandatory input;
   record ambiguity and ask instead of inventing requirements.

2. **Locate the flow in the source** (optional, when the repo is available):
   find the controller/route for the endpoint to confirm the method, path,
   expected payload, and required headers. If a Neo4j architecture graph is
   installed (`graph-rag/`), query it first for class discovery; otherwise
   search the source directly and say so.

3. **Verify JMeter is available.** Run `jmeter --version` (or `jmeter -v`).
   If it is not installed, stop and give the user the exact install step
   (download from https://jmeter.apache.org/download_jmeter.cgi, requires
   Java 8+; on Windows add `bin/` to PATH) instead of improvising
   alternatives.

4. **Build the test plan** as `<output-dir>/<plan-name>.jmx` (default output
   dir: `load-test/`, gitignore `*.jtl` and `report/`):
   - Thread Group (users, ramp-up, duration) matching the agreed load shape.
   - HTTP Request Defaults + one sampler per endpoint.
   - CSV Data Set Config when test data must be parameterized.
   - Header Manager (Content-Type, Authorization) — take token values from
     environment variables or the user's local env file; never hardcode
     credentials in the `.jmx`.
   - Response assertions (HTTP status, JSON path when applicable).
   - Listeners limited to Simple Data Writer (CLI mode has no GUI).

5. **Execute in CLI mode** (never GUI for load):
   ```bash
   jmeter -n -t load-test/<plan>.jmx -l load-test/results.jtl -e -o load-test/report/
   ```

6. **Analyze results**: throughput (req/s), latency p50/p90/p95/p99, error
   rate, and saturation signs (actuator metrics, application logs) when
   available. Parse from the HTML report or `results.jtl`; never fabricate
   numbers.

7. **Report**:
   - Always: test plan path, command executed, results location, and a table
     of throughput / latency percentiles / error rate per endpoint.
   - If an objective was given: comparison table (measured vs target),
     pass/fail per criterion, and conclusions ranked by confidence with
     evidence.
   - If not: results only, plus an offer to define objectives for a rerun.

## Output

- The `.jmx` test plan, `results.jtl`, and the HTML report under the output
  directory.
- A results summary in the response (table + conclusions when applicable).

## Guardrails

- Never run load against QA/PRE/PROD or any environment the user did not
  explicitly authorize for load testing.
- Never hardcode or commit credentials, tokens, or environment-specific
  connection details — read them from env files at runtime and keep
  `*.jtl`, `report/`, and any env file out of version control.
- Never invent objectives, results, or percentiles — report only what the
  run actually produced.
- If JMeter is missing, report the install step instead of improvising.
- Record ambiguity (payloads, test data, load shape, SLOs) and ask instead
  of guessing.
