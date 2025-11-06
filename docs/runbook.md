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
this header as part of its API client configuration.

## Deployment Workflow

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

## Operational Tasks

* **Session management** – API clients should open a session via `POST /sessions`
  and reuse the returned `session_id` for reads/writes. The orchestrator keeps
  connections alive with an ENIP UDP pattern that can be inspected through
  `GET /sessions/{id}/diagnostics`.
* **Assembly configuration** – The `services.assembly_config` helpers can be
  executed offline by enabling the fixtures described in the README. The
  repository’s unit tests demonstrate how to mock PLC responses when performing
  multi-attribute updates.
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
