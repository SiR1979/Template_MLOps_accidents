# Local reference-run tracking

Project: car_accident  
Status: NON_FINAL  
Implementation addition: 2026-10-08

## Scope

`compose.tracking.yaml` adds an isolated MLflow 3.17.0 service and a temporary
`tracking-import` tool. The first tracked run imports the already completed
2021 reference run. It does not execute preprocessing, fit a model, evaluate
new predictions, register a model version, or change delivery approval.

Open the UI at `http://127.0.0.1:5000/` after successful installation. Select
the `car_accident_reference` experiment and the `2021-reference-20261003` run.
Inspect its metrics, parameters, tags and `reference/` artifacts.

The server uses a separate image. Its only build context is `src/tracking/`.
MLflow and NumPy are pinned in that image; training and serving dependencies
remain in their existing images. The resolved tracking requirements are saved
inside the image at `/opt/tracking-requirements-resolved.txt`. Transitive
dependencies and the base-image digest are not fully locked.

## Storage and boundaries

| Location | Purpose |
| --- | --- |
| `data/tracking/mlflow.db` | New local SQLite metadata store |
| `data/tracking/artifacts/` | New artifact copies managed by the MLflow proxy |
| `data/runs/validation_20261003T193310Z_56c49087/` | Preserved reference inputs, mounted read-only by the import tool |
| `data/code_backups/tracking_<UTC>_<suffix>/architecture.md` | Exact architecture backup before installation |

The server publishes only `127.0.0.1:5000`; the container listens on its own
network interface. Host headers and browser origins are explicitly restricted.
The server has no raw-data, model-source, API or application bind mounts.
Its writable storage is `/tracking`; `/tmp` is temporary. Telemetry and MLflow
background job execution are disabled for this local tracking step.

The import tool has no writable reference mount or tracking-storage mount. It
sends requests to `http://mlflow:5000` on the existing Compose project network.
Uploads and downloads pass through that server's artifact proxy. Neither
credentials nor external tracking destinations are accepted by the importer.
This is a local, unauthenticated service; keep its published address on loopback.

`data/` is ignored by Git. Source files and documents can be versioned later;
the tracking database, artifact copies and protected originals remain local.
Do not delete or replace existing tracking storage to repeat an installation.

## Historical evidence and import provenance

The selected sources are:

- `validation_report.json`:
  `d1d3200d428701c96f715f99fcd4912c92bb4e528023f7fe7ff5475aedfdcf79`
- `reference_run/run_status.json`:
  `bfd69f4edf47b66ac5b8b15196f1d545182d70b10e8d92988dcc77b09438040e`
- `reference_run/model/trained_model.joblib`:
  `5e8775b69782640c0ee244bfa7c427928ece0f01be877688102313a8bc7a1a2b`

All three files are copied as unchanged bytes. The model is an opaque joblib
artifact; the importer never deserialises or reserialises it. The original
reports remain the canonical historical evidence. Their source and raw-data
hashes are historical observations, not new verification of all those files.
The selected model is distinct from the preserved model in `src/models/`.

| Recorded time | Meaning |
| --- | --- |
| `2026-10-03T19:33:12.381422+00:00` | Original training start |
| `2026-10-03T19:33:18.640003+00:00` | Original training finish |
| `2026-10-03T19:33:32.426452+00:00` | Separate validation observation |
| `imported_at_utc` | New import time, recorded separately |

MLflow run start/end times use the original training interval, at millisecond
precision. Metric timestamps use the later validation observation. Exact
timestamp strings are retained in tags and original artifacts. Importing the
run does not make the separate evaluation an automatic pipeline gate.

The original training Git revision and container image identity are **unknown**.
The import records its own baseline Git HEAD, dirty worktree state, container
image ID and importer source hash separately in tags and
`reference/import_provenance.json`. The baseline HEAD does not contain the
newly installed, uncommitted tracking sources. Never attribute that revision
or tracking image to the original training run.

Recorded reference settings include the split seed `42`, forest seed `None`,
`n_jobs=-1`, the feature count `28`, and the inherited target mapping
`[1,2,3,4] -> [1,1,1,0]`. They do not claim a complete hyperparameter inventory.
Repeated training can produce different model bytes and predictions.

## Import integrity and repeat behaviour

Input hashes and the historical status, metric and timestamp contracts are
checked before any tracking write. Each import identity derives from the three
selected file hashes. Run exactly one import process at a time: deduplication
is designed for sequential use, not concurrent atomic imports.

A new run receives the reference metrics and artifacts. Verification downloads
each artifact and compares its size and SHA-256 with the original. A sequential
repeat verifies the same finished run without updating it or creating a duplicate.
An existing incomplete, deleted, ambiguous or inconsistent import stops the
operation and preserves the stored state. A failed new import is marked failed
when the server remains reachable. There is no automatic destructive repair or
retry of an uncertain run-creation request.

The single installation test performs the actual import, a sequential repeat,
metric-history checks and artifact hash comparisons. It also checks that invalid
destinations and altered evidence fail before metadata writes. Original input
hashes are checked again at the end. The Linux preparation test uses labelled
opaque fixture bytes against MLflow 3.17.0; only successful Windows installation
output establishes validation with the real selected reference files and Docker.

## Local commands

Use PowerShell 7.2 or newer in the repository after installation. The installer
starts only the new service, performs its functional test, and leaves source
changes uncommitted. API, app and training validation are not rerun by this step.

```powershell
$compose = @('compose', '--project-directory', 'C:\Users\simon\MLOps_car_accident',
    '-f', 'compose.yaml', '-f', 'compose.api.yaml', '-f', 'compose.app.yaml',
    '-f', 'compose.tracking.yaml')
docker @compose ps mlflow
docker @compose logs --tail 60 mlflow
```

To stop the tracking server while preserving its files:

```powershell
docker @compose stop mlflow
```

To restart the installed server without rebuilding or starting other services:

```powershell
docker @compose up -d --no-deps --no-build --pull never --wait --wait-timeout 60 mlflow
```

Do not rerun the one-time installer on an existing installation. Review the
recorded run ID and storage first if an import was interrupted. A future
import invocation must supply its actual Git baseline and image identity;
do not copy an earlier import's identity into a new invocation.

## Limits and next work

`approved_for_delivery=false` and `quality_thresholds_enforced=false` are retained.
Observed metrics do not establish operational suitability or quality acceptance.
The inherited severity-based row selection limits claims about prediction before
intervention. Domain labels for class codes 0 and 1 remain unconfirmed.

This step does not instrument future training runs automatically or change the
API's selected artifact. DVC data/model versioning, future pipeline tracking,
orchestration, monitoring, controlled delivery and model-registry policy remain
separate work. Level 1 remains incomplete; Level 2 is a separate extension.

## References

- [MLflow 3.17.0 release](https://github.com/mlflow/mlflow/releases/tag/v3.17.0)
- [Tracking server architecture](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/)
- [MLflow REST API](https://mlflow.org/docs/latest/api_reference/rest-api.html)
