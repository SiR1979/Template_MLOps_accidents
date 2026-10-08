# Local prepared-feature application

Status: NON_FINAL. Implementation addition: 2026-10-07.
Runtime validation on the Windows Docker environment remains dependent on
the installer output. File presence alone does not establish a running service.

## Purpose and boundary

`compose.app.yaml` adds the separate `app` service. Open
`http://127.0.0.1:8080/` in the local browser. The form supplies all 28 prepared
numeric features to the existing API and displays its `prediction_code`,
`model_sha256` and `contract_version`. The API remains the authoritative
request validator and prediction component.

This is an educational prepared-feature demonstration. It does not provide
raw-input merging, recoding, feature calculations or missing-value filling.
The order, types and inherited encodings remain those documented in
[api-contract.md](api-contract.md). No domain labels for class codes are invented.

The inherited target mapping is `[1, 2, 3, 4] -> [1, 1, 1, 0]`. Reference row
selection uses observed severity. These limitations constrain claims about
prediction before intervention; the interface does not resolve them.

## Use

1. Open the local address and check that the connection indicator says `API ready`.
2. Select `Load reference example`, or supply every already prepared value.
3. Select `Get prediction` and inspect the returned class code and model identity.

The example is copied from the preserved `src/models/test_features.json` during
the app image build. It is a demonstration record, not a complete input-conversion
specification. Blank fields are not filled automatically. Categorical features
use numeric codes; the form does not infer category names or enforce guessed
category ranges. All fields are required, finite and float32-compatible.
Only `lat` and `long` accept non-integral values.

Editing an input clears the displayed prediction. Inputs are disabled while a
prediction is pending. Errors are displayed without assigning a prediction code.
`Check API` refreshes the readiness indicator; it is not continuous monitoring.

## Runtime and endpoints

The app image extends the already validated local API image and adds no runtime
dependencies. The browser uses same-origin application endpoints. The application
forwards requests to `http://api:8000` on the existing Compose network.

| App endpoint | Behaviour |
| --- | --- |
| `GET /` | Serve the local form |
| `GET /static/app.js`, `/static/styles.css` | Serve the explicit browser assets |
| `GET /api/example` | Return the baked reference example in a `features` object |
| `GET /health/live` | Report application liveness |
| `GET /health/ready`, `/api/health/ready` | Forward API readiness and model identity |
| `POST /api/predict` | Forward JSON bytes and preserve API response codes |

The gateway requires `application/json`, limits prediction bodies to 16384 bytes
and preserves the body bytes for the API's duplicate-key and value checks.
Connection failures return 503; unexpected non-JSON upstream responses return
502. The browser does not send credentials to the API. Neither service logs
input records, and the app does not save records or predictions. Browser inputs
remain in memory during the page session. Access logging is disabled.

The container filesystem is read-only, with temporary `/tmp` storage. The app
has no dataset, model or repository bind mounts. Only `127.0.0.1:8080` is published
on Windows. The existing API continues to publish `127.0.0.1:8000` and retains
its selected read-only artifact. API and workspace configuration are preserved.

After successful installation, subsequent local starts use:

```powershell
docker compose -f compose.yaml -f compose.api.yaml -f compose.app.yaml up -d --no-build --pull never api app
```

Run that command from `C:\Users\simon\MLOps_car_accident`. It starts the existing
local services and images; it does not train or select another model.

## Verification and remaining work

`src/app/test_service.py` checks the new gateway with an isolated upstream
fixture. With `RUN_LIVE_TESTS=1`, it also checks the running app's response
against a direct request to the existing API, including invalid-input rejection.
The installer includes this suite and Windows host access in one functional phase.

Preparation checks on 2026-10-07 passed seven isolated gateway tests and a
JavaScript syntax check. The two live API tests were skipped in that environment.
The planned browser interaction check could not start because its Chromium
executable was unavailable. Browser interactions and visual layout therefore
remain unverified. None of these preparation results establishes Windows Compose
execution or real-artifact predictions; use the dated installation output for
those runtime results.

The application does not change preprocessing, training, model selection or
historical delivery approval. Full Level 1 acceptance, raw-input conversion,
tracking, versioning, orchestration, monitoring and controlled delivery remain
open work. The original MIT notice is copied into `src/app/LICENSE` and included
in the app image. The repository's existing licence and attribution are preserved.
