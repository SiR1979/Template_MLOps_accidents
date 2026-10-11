# Local prepared-feature prediction API

Contract: `prepared-features-v1`. Educational demonstration only.

The API accepts one already prepared record. It does not perform raw-data
merges, recoding, imputation, training or model selection. Raw-input application
conversion remains a separate task. No operational police suitability is claimed.

## Request and feature order

`POST /predict`, `Content-Type: application/json`, with exactly one `features`
object and the following 28 keys:

```json
{"features":{"place":10,"catu":3,"sexe":1,"secu1":0.0,"year_acc":2021,"victim_age":60,"catv":2,"obsm":1,"motor":1,"catr":3,"circ":2,"surf":1,"situ":1,"vma":50,"jour":7,"mois":12,"lum":5,"dep":77,"com":77317,"agg_":2,"int":1,"atm":0,"col":6,"lat":48.60,"long":2.89,"hour":17,"nb_victim":2,"nb_vehicules":1}}
```

The displayed order is the model order. Request key order is irrelevant; the
service explicitly constructs this ordered frame. All values must be finite
JSON numbers representable within the float32 magnitude range used by the
estimator. All features except `lat` and `long` must have integral values;
`1.0` is accepted. Nulls, booleans, strings, duplicate keys, missing keys and
extra keys are rejected. The service performs no silent imputation. The 16 KiB
request limit and float32 magnitude check are technical interface constraints,
not scientific acceptance thresholds.

## Encodings and limitations

`atm` and `catv` are already grouped by the reference preprocessing. `dep` and
`com` are already numeric after its Corsica substitutions. `year_acc`,
`victim_age`, `hour`, `nb_victim` and `nb_vehicules` must already be derived.
`nb_victim` inherits a count of road-user rows, not a newly confirmed count of
injured people. Missing `surf`, `circ`, `col` and `motor` values were filled
using training-derived modes during preprocessing; no fill values are loaded
or recomputed by this service. Observed training categories are not treated as
exhaustive domain definitions or enforced as new category bounds.

Target recoding remains `[1,2,3,4] -> [1,1,1,0]`. Responses use class codes
without unconfirmed domain labels. Severity-based road-user selection remains
an inherited limitation for prediction before intervention. The forest remains
unseeded; no exact retraining equality is promised.

## Responses

Success has `prediction_code` (integer 0 or 1), `model_sha256` (the loaded
artifact identity) and `contract_version` (`prepared-features-v1`).

| HTTP status | Meaning |
| --- | --- |
| 200 | Successful prediction or successful health check |
| 400 | Invalid UTF-8 JSON, including nonstandard NaN/Infinity tokens |
| 413 | Request body exceeds 16384 bytes |
| 415 | Content type is not application/json |
| 422 | Invalid feature structure, duplicate keys or unsupported numeric values |
| 503 | Model initialization failed; predictions remain unavailable |
| 500 | Unexpected prediction failure; no internal details are returned |

`GET /health/live` reports process availability. `GET /health/ready` returns
readiness, model hash and contract version, or 503. Readiness is not model
quality approval. Interactive documentation is disabled for this narrow manual
JSON interface. Request records are not logged and access logging is disabled.

## Artifact and runtime

Local selection:
`data/runs/reference_20261011T144150Z_19d3274fd12e49d5b3cb9abbd73da5ea/model/trained_model.joblib`

SHA-256:
`9dcd169ed58e0b09a2367b17055abee4b7424741d1b02fa60aa196fe049f6b99`

Startup checks this identity before deserialization, then verifies the estimator
type, ordered feature names, feature count and class codes. There is no fallback
artifact. The model is loaded once into the process and is mounted read-only.
Changing the model requires an explicit configuration change and API container recreation.

The candidate selected here is authorized on 2026-10-11 for one controlled
local technical demonstration only. Training records retain
approved_for_delivery=false. Model quality acceptance and Level 1 acceptance
remain separate. Delivery results are recorded separately in
data/delivery_evidence/local_delivery_20261011T195239Z_19d3274fd12e49d5b3cb9abbd73da5ea/delivery.json.

The local API is separately authorized for demonstration. The historical report
retains `approved_for_delivery=false`; no automatic delivery gate is bypassed or
reported as complete. Original data, reference model and snapshots are preserved.

Use `docker compose -f compose.yaml -f compose.api.yaml` for API commands.
The `api` image extends the existing local `car-accident-runtime:local` image.
It adds pinned direct API/test dependencies; transitive dependencies remain
resolved at build time. The model runtime uses scikit-learn 1.7.2. Source changes
require rebuilding the API image. `workspace` remains available unchanged.

The Windows host exposes only `127.0.0.1:8000`. Container port 8000 is used on
the Compose network. There is no authentication, TLS or public deployment;
those require a separately agreed access and release policy.

## Verification and local operation

The installation script builds the API image, starts only `api`, runs the
contract/model-binding/live-container suite once, and checks the host endpoint
with one valid and one invalid request. It does not retrain. A failure stops
the API created by that script and leaves files available for diagnosis.
Source installation is not evidence of successful execution. Preserve the
terminal output and report the actual result before claiming validation.

Stop locally with:
`docker compose -f compose.yaml -f compose.api.yaml stop api`

Start an existing built service with:
`docker compose -f compose.yaml -f compose.api.yaml up -d --no-deps --no-build api`

Level 1 remains incomplete. Integrated model acceptance, tracking, versioned
delivery, triggers and monitoring beyond local health checks remain open.
Level 2 remains a separate extension.
