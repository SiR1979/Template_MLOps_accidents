# Local reference artifact versioning

Project: car_accident  
Status: NON_FINAL  
Implementation addition: 2026-10-08

Configuration repair: 2026-10-09; successful local repair output is required.

## Scope

The separate finite tool in `compose.versioning.yaml` pins DVC 3.67.1 and uses
Python 3.12. It registers the existing reference artifacts, transfers their
contents to a new local store, and verifies an isolated recovery. It never fits
or loads a model, changes delivery approval, or replaces the serving artifact.
Successful Windows installation output establishes validation with real files.

| Metadata file under `versioning/` | Selected artifact |
| --- | --- |
| `raw_2021.dvc` | Four supplied files in `data/raw/` |
| `reference_preprocessed.dvc` | Four original files in `data/preprocessed/` |
| `preserved_reference_model.dvc` | `src/models/trained_model.joblib` |
| `validated_reference_run.dvc` | Six files under `data/runs/validation_20261003T193310Z_56c49087/reference_run/` |
| `validation_report.dvc` | `data/runs/validation_20261003T193310Z_56c49087/validation_report.json` |

These are five groups and 16 source files. The validated run consists of four
prepared CSVs, the selected model and its run status. Unexpected source files or
linked paths stop registration. The original and validated prepared files must
match. The two model files retain distinct roles and are never substituted.

## Storage and boundaries

| Location | Purpose |
| --- | --- |
| `.dvc/cache/` | Ignored working cache; copy mode |
| `/tmp/dvc-site-cache/` in the tool container | Temporary internal state cache, selected by `DVC_SITE_CACHE_DIR` |
| `versioning/*.dvc` | Small Git-versioned pointers using `wdir: ..` |
| `versioning/reference_manifest.json` | File SHA-256 values, roles and registration provenance |
| `.dvc/config.local` | Ignored machine-specific local-store configuration |
| `C:\Users\simon\MLOps_car_accident_dvc_store\objects\` | Separate local DVC object store, mounted at `/store/objects` |
| `C:\Users\simon\MLOps_car_accident_dvc_store\validation\<UTC>_<suffix>\` | Preserved recovery directory and validation report |
| `data/code_backups/versioning_<UTC>_<suffix>/architecture.md` | Exact architecture backup before installation |
| `data/code_backups/versioning_resume_<UTC>_<suffix>/` | Exact repair backups of four updated files, the partial config and DVC ignore rules |

The existing `/data/` and model exclusions remain. Metadata sits outside the
ignored data directory. DVC's own content identifiers are separate from the
SHA-256 values used to verify preservation and recovery.

The tool has no port or runtime network. Docker build requires dependency
downloads. At runtime, the repository metadata and cache are writable, while
`data/` and the preserved model file are mounted read-only. The local object
store is writable. Global host configuration and credentials are not mounted.
No Git hooks are installed. Normal DVC initialization temporarily stages three
new metadata files; only those are unstaged after an empty-index guard.

The internal state cache is separate from the persistent content cache and
local object store. DVC 3.67.1 defaults to `/var/tmp/dvc`, which is outside the
tool's writable temporary mounts. The October 9 read-only diagnosis observed
that default path on a read-only filesystem, functioning Git backends, an empty
Git index, an empty `.dvc/config`, the generated `.dvcignore`, and no content
cache or versioning pointers. This explains the incomplete initialisation.
The environment setting redirects internal state to the existing `/tmp` mount.

The bounded repair completes only that recognised partial state. It preserves
the existing DVC files and empty storage directories, creates new evidence in
another directory, and rejects any existing object, validation file or pointer.
The empty configuration is populated after its original bytes are backed up;
the existing `.dvcignore` remains unchanged.
It never uses `dvc init --force`. Recovery uses a new repository and normal
initialisation. Initialization errors remain visible in captured command output.
The repair builds `car-accident-versioning:resume-20261009`; the previous local
image remains preserved. Only the versioning tool is rebuilt.

The local store is on the same drive as the repository. It is not protection
against drive loss and is not accessible to external CI. A different approved
storage destination and release policy are required for such later use.
MLflow storage, reference snapshots, code backups and assets are excluded.

## Integrity and provenance

The four raw file hashes, selected model, report and status are bound to the
previously supplied validation evidence. Other selected file hashes are captured
at registration. The preserved original model's historical hash was not supplied
independently; this phase records its current bytes without claiming its original
training identity. The current raw and model content is never reinterpreted.

Registration records its own baseline Git HEAD, dirty worktree, DVC version and
actual tool image identity, executed tool hash and registration mode. It does
not assign those values to the historical training run. Original training Git
revision and image remain unknown.
The reports retain `approved_for_delivery=false`.

The resolved tool requirements remain inside its image at
`/opt/versioning-requirements-resolved.txt`. The tool image uses the base tag
`python:3.12-slim-bookworm`; full transitive and base-image locking remain open.

## Validation and failure handling

One phase registers the five groups, checks DVC status, transfers objects only to
the local store and pulls them into a new recovery repository with an initially
empty cache. All 16 restored files must match the initial SHA-256 values. The
original files, Git exclusion rules, baseline HEAD and empty index are checked
again. The recovery cache cannot fall back to the primary cache.

An opaque preparation fixture exercises real DVC 3.67.1 with the same 16-file
layout. It is not a model or evidence of Windows, Docker or real-file execution.
The repair preparation exercises the diagnosed partial initialisation and
preservation of existing metadata and empty evidence directories.

Installation leaves source files and generated metadata uncommitted. Existing
pipeline, API, app and MLflow services are not rebuilt or tested. A failure
preserves new source files, cache, local store, recovery files, backup and output.
Do not rerun the one-time installer on a partial installation or clear storage
to make it pass. Diagnose the reported phase first.

## Remaining work

This phase versions one historical baseline. Automatic registration of new
training outputs, Git versioning of accepted metadata, an external data store,
CI access, model acceptance and controlled delivery remain separate steps.
Level 1 remains incomplete; Level 2 is tracked separately.

## References

- [DVC 3.67.1 release](https://github.com/treeverse/dvc/releases/tag/3.67.1)
- [DVC metadata schema](https://doc.dvc.org/user-guide/project-structure/dvc-files)
- [DVC commit](https://doc.dvc.org/command-reference/commit)
- [DVC local remote storage](https://doc.dvc.org/user-guide/data-management/remote-storage)
