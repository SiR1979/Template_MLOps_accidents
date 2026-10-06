# Architecture

Project: car_accident  
Status: NON_FINAL  
Document date: 2026-10-05  
Implementation evidence: local build and functional validation on 2026-10-03

## Scope and evidence

The project operationalises the supplied 2021 road-accident data,
preprocessing and Random Forest reference model. It is an educational
demonstration, not a validated operational police system.

Docker and Docker Compose are required. Level 1 is mandatory;
Level 2 is a separately tracked extension.

The diagrams distinguish implemented behaviour from the proposed target.
They do not establish deployment approval or a live infrastructure inventory.

Functional validation evidence:
`data/runs/validation_20261003T193310Z_56c49087/validation_report.json`

That report binds the tested source files, raw data and trained model to
SHA-256 hashes and records model metrics. It does not yet provide a complete
link between Git revision, container image identity and model delivery.

## 1. Implemented data flow

```mermaid
flowchart TD
    RAW["Four supplied raw CSV files"] --> PRE["Reference transformations and row selection"]
    PRE --> SPLIT["Train/test split: 70/30"]
    SPLIT --> TRAIN["Training data: derive and apply fill values"]
    SPLIT --> TEST["Test data: apply training fill values"]
    TRAIN -->|"Derived fill values only"| TEST
    TRAIN --> FIT["Random Forest training"]
    FIT --> MODEL["Saved model in a new run directory"]
    MODEL --> EVAL["Evaluation in the separate functional test"]
    TEST --> EVAL
```

- Merging, feature calculations, fixed recoding and selected row filtering
  happen before the split.
- The split uses `test_size=0.3` and `random_state=42`.
- After the split, missing values in `surf`, `circ`, `col` and `motor`
  are filled using modes derived from the training data.
- Training preserves `RandomForestClassifier(n_jobs=-1)`, without a seed.
  Repeated fits can produce different models and predictions.
- Evaluation currently belongs to the separate functional test.
  It is not an automatic pipeline acceptance or delivery gate.

## 2. Implemented runtime boundaries

The evidenced environment uses Windows, WSL2 and Linux containers.
Compose defines one service, `workspace`. Commands run in temporary
containers created from that service.

```mermaid
flowchart TD
    subgraph HOST["Windows host: repository and persistent files"]
        DATA["data: raw files, run outputs and snapshots"]
        MODELS["src/models: scripts and reference model"]
        BUILD["Dockerfile, dependencies and source build context"]
    end

    subgraph ENGINE["Linux container runtime"]
        IMAGE["car-accident-runtime:local image"]
        subgraph WORKSPACE["Compose service: workspace"]
            PIPE["src/run_pipeline.py"]
            TRAIN["src/models/train_model.py"]
            CHECK["Separately invoked functional test"]
        end
    end

    BUILD -->|"Image build"| IMAGE
    IMAGE -->|"Container creation"| PIPE
    DATA -->|"Read inputs through /app/data"| PIPE
    PIPE -->|"Write new runs through /app/data"| DATA
    MODELS -->|"Bind mount at /app/src/models"| TRAIN
    PIPE --> TRAIN
    TRAIN -->|"Write model into the run directory"| DATA
    DATA -->|"Read outputs and reference artifacts"| CHECK
    CHECK -->|"Write validation evidence"| DATA
```

The image contains `src/run_pipeline.py` and `src/data` source files.
Changes to these files require rebuilding the image.

The host directory `src/models` is mounted over the corresponding image
directory. Executed model scripts can therefore differ from the image
contents. The completed functional test compared all three affected
source files with their host hashes.

Both existing bind mounts are writable. The pipeline protects outputs
through new run directories and exclusive file creation; the mounts
themselves do not enforce read-only protection.

### Storage contract

| Location | Purpose |
| --- | --- |
| `data/raw/` | Existing supplied raw CSV files |
| `data/runs/<run_id>/preprocessed/` | Four processed datasets for a new run |
| `data/runs/<run_id>/model/trained_model.joblib` | Newly trained model |
| `data/runs/<run_id>/run_status.json` | Run state and failure information |
| `data/preprocessed/` | Preserved reference datasets |
| `src/models/trained_model.joblib` | Preserved reference model |
| `data/reference_snapshots/20261003T182822Z_3490e1df/` | Preserved reference snapshot |

The pipeline rejects an existing run directory and returns a nonzero exit
code on failure. Failures after run-directory creation are recorded in the
run status when storage remains writable. Failures during initial input
checks occur before a run directory is created.

A completed training run has `approved_for_delivery=false`.

## 3. Proposed target architecture

Every component and connection in this diagram describes the target.
Separate services and automated model delivery are not yet implemented.
Logical layers do not imply one microservice for every pipeline stage.

```mermaid
flowchart TD
    subgraph PRESENTATION["Presentation layer"]
        APP["app: user interface"]
    end

    subgraph SERVING["Prediction layer"]
        API["api: input validation and prediction"]
    end

    subgraph JOBS["Training layer"]
        TRIGGER["Configured trigger"]
        PIPELINE["pipeline: finite preprocessing and training job"]
        GATE["Data and model validation gate"]
    end

    subgraph STORAGE["Data and artifact layer"]
        DATASETS["Versioned supplied datasets"]
        CANDIDATE["Candidate model and run artifacts"]
        ACCEPTED["Accepted model version"]
        TRACKING["Run tracking and version metadata"]
    end

    MONITOR["Operational and model monitoring"]

    APP -->|"Prediction request"| API
    API -->|"Prediction response"| APP
    ACCEPTED -->|"Load a selected version"| API
    TRIGGER --> PIPELINE
    DATASETS --> PIPELINE
    PIPELINE --> CANDIDATE
    CANDIDATE --> GATE
    GATE -->|"Only if agreed checks pass"| ACCEPTED
    PIPELINE --> TRACKING
    GATE --> TRACKING
    PIPELINE -->|"Run state and failures"| MONITOR
    API -->|"Health and prediction indicators"| MONITOR
```

### Service responsibilities and transition

| Component | Responsibility and lifecycle |
| --- | --- |
| `workspace` | Current development and test environment; may remain optional after responsibilities are covered |
| `pipeline` | Proposed finite job for preprocessing and training; independent of prediction requests |
| `api` | Proposed persistent prediction service using a selected model version |
| `app` | Proposed separate interface that calls the API |
| Tracking and storage | Record artifact identities, versions and run metadata |
| Monitoring | Track failures, service health and agreed data/model indicators |

Start with the local API and application. Add tracking, data/model
versioning, configured triggers and controlled delivery in subsequent work.

DVC and MLflow are recommended candidates for data versioning and
run/model management respectively. Their deployment and configuration
are not implemented or fixed by this document.

The API input contract still needs to specify how application inputs map
to the model's 28 ordered features, including types, encodings and missing
values. The current reference example supplies already prepared features;
it does not establish a complete raw-input serving pipeline.

## 4. Limitations and open decisions

- The inherited successive target recodings map original codes
  `[1, 2, 3, 4]` to `[1, 1, 1, 0]`. Domain labels remain unconfirmed.
- Selection of one road-user row per accident depends on observed severity.
  This limits claims about prediction before intervention.
- The measured model metrics are reference observations, not agreed
  quality thresholds. Agree thresholds before enforcing model acceptance.
- No configured recurring trigger, implemented API/application, model
  registry or complete monitoring workflow is evidenced.
- Labelled predictive performance and unlabelled drift indicators must
  remain distinct.
- Direct runtime dependencies are pinned; full dependency and base-image
  locking remain open.
- Access controls, deployment destination and recovery policy remain open.
- Level 1 acceptance is incomplete. Level 2 build/test/deployment automation
  remains a separate extension target.

## Maintenance

Update the relevant diagram when component responsibilities, data paths
or runtime boundaries change. Record the evidence date when changing an
implementation claim. Version this document with the corresponding code;
planned components must remain visibly identified until implemented.
