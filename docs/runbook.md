# Operational Runbook

This runbook complements the legacy details in [`README.rst`](../README.rst) with
practical guidance for running the combined FastAPI backend and Vite frontend
included in this repository.

## Architecture Overview

* **Backend** – The `webapi` package exposes a FastAPI application wrapping the
  `PLCManager` and `SessionOrchestrator` helpers. Requests ultimately interact
  with programmable logic controllers (PLCs) over ENIP/CIP using the packet
  dissectors described in the README.
* **Frontend** – The Vite project in `frontend/` builds a static operator
  console that consumes the `/sessions` API.
* **Containerisation** – A multi-stage [`Dockerfile`](../Dockerfile) composes the
  frontend build artefacts with the backend runtime. [`docker-compose.yaml`](../docker-compose.yaml)
  can orchestrate the stack while exposing the API on port `8000`.

## Configuration and Environment Variables

The ASGI entrypoint (`webapi/main.py`) reads the following environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `PLC_HOST` | `127.0.0.1` | PLC hostname or IP reachable from the container. |
| `PLC_PORT` | `44818` | ENIP TCP port on the PLC. |
| `PLC_POOL_SIZE` | `2` | Number of TCP clients kept in the connection pool. |
| `PLC_API_TOKEN` | _empty_ | Bearer token required by the `/sessions` API.
  Generate and share this secret with trusted operators only. |
| `PLC_API_PORT` | `8000` (compose only) | Host port published for HTTP access. |
| `PLC_NETWORK_MODE` | `bridge` (compose only) | Override with `host` when the
  container must use the host network to reach plant VLANs. |

Authentication is optional by default but strongly recommended. When
`PLC_API_TOKEN` is set the API rejects requests that do not include an
`Authorization: Bearer <token>` header. The frontend fetch code should inject
this header as part of its API client configuration. The operator console
exposes an **API bearer token** field inside the *Device configuration* card;
paste the same secret value provided in `PLC_API_TOKEN` and click **Save token**.
The browser stores the token locally and attaches it to every request so the
drop zone and diagnostic panels work without manual cURL sessions.

## Deployment Workflow

### Local container workflow

1. **Build and run locally**

   ```bash
   docker compose build
   PLC_HOST=192.168.1.10 PLC_API_TOKEN=$(openssl rand -hex 16) \
     docker compose up
   ```

   Set `PLC_NETWORK_MODE=host` if the PLC resides on a network only reachable
   from the host NIC. The container will publish the API at
   `http://localhost:8000/` and serve the static UI at `/ui` after the frontend
   assets have been built.

2. **Kubernetes or remote deployments**

   Use the published Docker image as a base and provide the environment variables
   above through your orchestration platform. Ensure the pod joins a network that
   can route to the PLC subnet; on bare metal clusters this may involve
   `hostNetwork: true` or a dedicated Multus attachment.

### Local Python workflow (no Docker)

When Docker is unavailable, the backend can run directly on the host. This
approach reuses the same environment variables documented above.

1. **Create a virtual environment and install dependencies**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

2. **Build the optional frontend** (skip if you only need the API)

   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```

   Building the Vite project produces `frontend/dist`, which FastAPI serves under
   `/ui` when present. Without this directory only the REST API will be exposed.

3. **Run the API with Uvicorn**

   ```bash
   PLC_HOST=192.168.1.10 PLC_API_TOKEN=$(openssl rand -hex 16) \
     uvicorn webapi.main:app --host 0.0.0.0 --port 8000
   ```

   Replace `PLC_HOST` with the address of the target PLC. The service becomes
   available at `http://localhost:8000/` (and `/ui` if the frontend has been
   built).

## Operational Tasks

* **Session management** – API clients should open a session via `POST /sessions`
  and reuse the returned `session_id` for reads/writes. The orchestrator keeps
  connections alive with an ENIP UDP pattern that can be inspected through
  `GET /sessions/{id}/diagnostics`.
* **Target alternate PLCs** – Provide `host` and/or `port` in the `POST /sessions`
  payload to override the default endpoint for a single session. The backend will
  establish or reuse a connection pool for that address so operators can bounce
  between benches without restarting the service. The Vite console persists the
  last-used host/port in the browser to speed up subsequent runs.
* **Assembly configuration** – The `services.assembly_config` helpers can be
  executed offline by enabling the fixtures described in the README. The
  repository’s unit tests demonstrate how to mock PLC responses when performing
  multi-attribute updates.
* **Sample CIP payloads** – The repository ships with
  [`docs/samples/plant_controller_example.xml`](../docs/samples/plant_controller_example.xml),
  a multi-assembly configuration that can be uploaded through the web UI drop
  zone for local experiments, and
  [`docs/samples/generic_adapter_template.xml`](../docs/samples/generic_adapter_template.xml),
  a ready-to-use EtherNet/IP adapter template illustrating implicit Class 1
  connections, assemblies, and QoS defaults for simulators.
* **Frontend refresh** – Run `npm install && npm run build` in `frontend/` after
  UI changes. The Dockerfile performs these steps automatically for production
  images.

## Troubleshooting

* **401 Unauthorized** – Confirm that the client sends the bearer token defined
  by `PLC_API_TOKEN`. Inspect the API logs for `Invalid bearer token` entries.
* **PLC connectivity issues** – When using containers, verify that the network
  mode grants access to the PLC subnet. For quick diagnostics run
  `docker compose run --rm plc-stack ping <plc-host>`.
* **Frontend not loading** – Make sure `frontend/dist` exists (run `npm run build`).
  The FastAPI app only mounts `/ui` when the build output is present.

Refer to [`README.rst`](../README.rst) for low-level packet examples and manual
Scapy workflows that remain invaluable for deep-dive debugging.
