"""Version selected local reference artifacts and verify an isolated recovery.

Model files remain opaque bytes. Registration is not training or delivery approval.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


DVC_VERSION = "3.67.1"
PARTIAL_IGNORE_SHA256 = "1d8052e9672c44c62dc27a4df73ced356f20cb9c18d1a7b5aa09249309609583"
BASELINE_HEAD = "08208d734188eb59303ee25d4910e670e4cb5674"
VALIDATION_ROOT = "data/runs/validation_20261003T193310Z_56c49087"
GROUPS = {
    "raw_2021": "data/raw",
    "reference_preprocessed": "data/preprocessed",
    "preserved_reference_model": "src/models/trained_model.joblib",
    "validated_reference_run": VALIDATION_ROOT + "/reference_run",
    "validation_report": VALIDATION_ROOT + "/validation_report.json",
}
RAW_NAMES = (
    "caracteristiques-2021.csv", "lieux-2021.csv",
    "usagers-2021.csv", "vehicules-2021.csv",
)
PREPARED_NAMES = ("X_train.csv", "X_test.csv", "y_train.csv", "y_test.csv")
FILES = (
    *("data/raw/" + name for name in RAW_NAMES),
    *("data/preprocessed/" + name for name in PREPARED_NAMES),
    "src/models/trained_model.joblib",
    *(VALIDATION_ROOT + "/reference_run/preprocessed/" + name for name in PREPARED_NAMES),
    VALIDATION_ROOT + "/reference_run/model/trained_model.joblib",
    VALIDATION_ROOT + "/reference_run/run_status.json",
    VALIDATION_ROOT + "/validation_report.json",
)
EXPECTED = {
    "data/raw/caracteristiques-2021.csv": "ee2d552b426d2d29cc8cb495ec920c0228e322fde228be7827730b8b681e226d",
    "data/raw/lieux-2021.csv": "95412261cadbe5f07c2dbf31fd30ca4e0bf197570799421f59078f77f80784fd",
    "data/raw/usagers-2021.csv": "3bf27607147cae1f0215bbcae985891e19ec792572f521a91a3fcb96ef4e202c",
    "data/raw/vehicules-2021.csv": "5aad4097a38803a32eb1f2db642f50fa0aa4e2e23156096844eccbd0b4629d84",
    VALIDATION_ROOT + "/reference_run/model/trained_model.joblib": "5e8775b69782640c0ee244bfa7c427928ece0f01be877688102313a8bc7a1a2b",
    VALIDATION_ROOT + "/reference_run/run_status.json": "bfd69f4edf47b66ac5b8b15196f1d545182d70b10e8d92988dcc77b09438040e",
    VALIDATION_ROOT + "/validation_report.json": "d1d3200d428701c96f715f99fcd4912c92bb4e528023f7fe7ff5475aedfdcf79",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def snapshot(repo):
    result = {}
    for relative in FILES:
        path = repo / relative
        require(path.is_file(), "Selected reference file is missing: " + relative)
        require(not any(p.is_symlink() for p in (path, *path.parents)), "Linked reference path was preserved.")
        stat = path.stat()
        require(stat.st_size > 0, "Selected reference file is empty.")
        result[relative] = {"sha256": digest(path), "size_bytes": stat.st_size}
    for relative in ("data/raw", "data/preprocessed", GROUPS["validated_reference_run"]):
        directory = repo / relative
        require(not any(p.is_symlink() for p in directory.rglob("*")), "Linked reference entry was preserved.")
        actual = {p.relative_to(repo).as_posix() for p in directory.rglob("*") if p.is_file()}
        intended = {p for p in FILES if p.startswith(relative + "/")}
        require(actual == intended, "Reference directory contains an unexpected file: " + relative)
    return result


def command(repo, *args, quiet=False):
    env = os.environ.copy()
    env["DVC_NO_ANALYTICS"] = "1"
    if args[0] == "dvc":
        executable = [sys.executable, "-m", "dvc", *args[1:]]
    else:
        executable = ["git", "--no-optional-locks", "-c", "safe.directory=" + str(repo), "-C", str(repo), *args[1:]]
    result = subprocess.run(executable, cwd=repo, env=env, capture_output=True, text=True)
    if result.returncode:
        # Only local command output is retained; file contents are never printed.
        details = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise RuntimeError("Local operation failed: " + args[0] + " " + args[1] + "\n" + details[-6000:])
    if not quiet and result.stdout.strip():
        print(result.stdout.strip(), flush=True)
    return result.stdout.strip()


def initialise(repo, *, partial=False):
    if not partial:
        command(repo, "dvc", "init")
    command(repo, "dvc", "config", "core.analytics", "false", quiet=True)
    command(repo, "dvc", "config", "core.autostage", "false", quiet=True)
    command(repo, "dvc", "config", "cache.type", "copy", quiet=True)
    if partial:
        # Complete the observed partial repository without reinitializing or deleting it.
        from dvc.repo import Repo

        with Repo(str(repo)):
            pass


def validate_partial_initialisation(repo, store):
    """Accept only the diagnosed pre-registration state; preserve all existing paths."""
    directory = repo / ".dvc"
    require(directory.is_dir(), "Partial DVC directory is missing.")
    require({p.name for p in directory.iterdir()} == {"config", "tmp"}, "Partial DVC entries differ.")
    require((directory / "tmp").is_dir(), "Partial DVC temporary directory is missing.")
    require((directory / "config").is_file() and (directory / "config").stat().st_size == 0, "Partial DVC configuration differs.")
    require((repo / ".dvcignore").is_file() and digest(repo / ".dvcignore") == PARTIAL_IGNORE_SHA256, "Partial DVC ignore rules differ.")
    require(not any(p.is_symlink() for p in directory.rglob("*")), "Linked DVC metadata was preserved.")
    require(not (repo / ".dvcignore").is_symlink(), "Linked DVC ignore file was preserved.")
    require({p.name for p in store.iterdir()} == {"objects", "validation"}, "Partial storage entries differ.")
    remote = store / "objects"
    evidence = store / "validation"
    require(remote.is_dir() and not any(remote.iterdir()), "Existing DVC objects were preserved.")
    require(evidence.is_dir(), "Partial validation directory is missing.")
    require(not any(p.is_symlink() for p in store.rglob("*")), "Linked storage was preserved.")
    require(all(p.is_dir() for p in evidence.rglob("*")), "Existing validation files were preserved.")


def register_and_verify(repo, store, baseline, image_id, *, expected=None, historical=True, resume_partial=False):
    """Run one registration, local transfer and recovery phase; preserve failures."""
    repo = Path(repo).resolve(strict=True)
    store = Path(store).resolve(strict=True)
    require(store != repo and repo not in store.parents and store not in repo.parents, "Storage must be separate from the repository.")
    require(re.fullmatch(r"[0-9a-f]{40}", baseline) is not None, "Invalid baseline revision.")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is not None, "Invalid versioning image identity.")
    require(command(repo, "git", "rev-parse", "HEAD", quiet=True) == baseline, "Baseline revision differs.")
    require(not command(repo, "git", "diff", "--cached", "--name-only", quiet=True), "Existing staged changes were preserved.")
    targets = ("versioning",) if resume_partial else (".dvc", ".dvcignore", "versioning")
    for relative in targets:
        require(not (repo / relative).exists(), "Existing DVC target was preserved: " + relative)
    if resume_partial:
        validate_partial_initialisation(repo, store)
    else:
        require(not any(store.iterdir()), "Existing storage was preserved; this is a one-time operation.")
    require(command(repo, "dvc", "--version", quiet=True) == DVC_VERSION, "DVC version differs.")
    before = snapshot(repo)
    expected = EXPECTED if expected is None else expected
    require(all(before[name]["sha256"] == value for name, value in expected.items()), "Selected historical bytes differ.")
    for name in PREPARED_NAMES:
        require(before["data/preprocessed/" + name] == before[VALIDATION_ROOT + "/reference_run/preprocessed/" + name], "Prepared reference datasets differ.")
    ignore_hash = digest(repo / ".gitignore")

    remote = store / "objects"
    if not resume_partial:
        remote.mkdir()
    evidence = store / "validation" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
    evidence.mkdir(parents=True)
    initialise(repo, partial=resume_partial)
    # Normal DVC initialization stages three new metadata files. Unstage only those.
    staged = set(command(repo, "git", "diff", "--cached", "--name-only", quiet=True).splitlines())
    require(not resume_partial or not staged, "Partial completion staged unexpected changes; they were preserved.")
    initial = {".dvc/config", ".dvc/.gitignore", ".dvcignore"}
    require(staged <= initial, "Unexpected staged paths were preserved.")
    if staged:
        command(repo, "git", "reset", "--", *sorted(staged), quiet=True)
    require(not command(repo, "git", "diff", "--cached", "--name-only", quiet=True), "DVC initialization changed the index unexpectedly.")
    command(repo, "dvc", "remote", "add", "--local", "--default", "reference", str(remote), quiet=True)
    directory = repo / "versioning"
    directory.mkdir()
    pointers = []
    for name, target in GROUPS.items():
        relative = "versioning/" + name + ".dvc"
        with (repo / relative).open("x", encoding="utf-8") as stream:
            stream.write("wdir: ..\nouts:\n  - path: " + target + "\n")
        pointers.append(relative)
    # Force fills hashes only in these newly created metadata files. No old target is replaced.
    command(repo, "dvc", "commit", "--force", "--no-relink", *pointers)
    require(not json.loads(command(repo, "dvc", "status", "--json", *pointers, quiet=True)), "DVC cache or metadata is incomplete.")
    command(repo, "dvc", "push", "--remote", "reference", *pointers)

    manifest = {
        "scope": "historical_reference_registration" if historical else "opaque_preparation_fixture",
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "registration_baseline_git_head": baseline,
        "registration_worktree_state": "dirty",
        "versioning_image_id": image_id,
        "dvc_version": DVC_VERSION,
        "registration_tool_sha256": digest(__file__),
        "registration_mode": "resume_partial_initialisation" if resume_partial else "fresh_initialisation",
        "site_cache_base": os.environ.get("DVC_SITE_CACHE_DIR", "DVC default"),
        "source_file_sha256": before,
        "metadata_file_sha256": {p: digest(repo / p) for p in pointers},
        "preserved_reference_model_role": "Separate preserved model; not the selected serving artifact.",
        "preserved_reference_model_historical_hash": "Not independently supplied; current bytes captured here.",
        "original_training_git_revision": "unknown",
        "original_training_image_id": "unknown",
        "approved_for_delivery": False,
        "training_performed": False,
    }
    with (directory / "reference_manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    # Recover from the separate local remote with an initially empty cache.
    recovered = evidence / "recovered_repository"
    recovered.mkdir()
    command(recovered, "git", "init", "--quiet")
    (recovered / ".gitignore").write_bytes((repo / ".gitignore").read_bytes())
    initialise(recovered)
    command(recovered, "dvc", "remote", "add", "--local", "--default", "reference", str(remote), quiet=True)
    require(not (recovered / ".dvc/cache").exists(), "Recovery cache was not empty.")
    (recovered / "versioning").mkdir()
    for relative in pointers:
        (recovered / relative).write_bytes((repo / relative).read_bytes())
    command(recovered, "dvc", "pull", "--remote", "reference", *pointers)
    require(snapshot(recovered) == before, "Recovered reference bytes differ.")
    require(snapshot(repo) == before, "Original reference bytes changed.")
    require(digest(repo / ".gitignore") == ignore_hash, "Original Git exclusion rules changed.")
    require(command(repo, "git", "rev-parse", "HEAD", quiet=True) == baseline, "A new commit was created unexpectedly.")
    require(not command(repo, "git", "diff", "--cached", "--name-only", quiet=True), "Unexpected staged changes were preserved.")
    result = {
        "status": "passed", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": manifest["scope"], "file_count": len(before), "pointer_count": len(pointers),
        "recovered_sha256": "all_match", "original_sha256": "all_preserved",
        "recovery_cache": "initially_empty", "registration_baseline_git_head": baseline,
        "versioning_image_id": image_id, "dvc_version": DVC_VERSION,
        "registration_tool_sha256": manifest["registration_tool_sha256"],
        "registration_mode": manifest["registration_mode"],
        "restore_directory": str(recovered), "manifest_sha256": digest(directory / "reference_manifest.json"),
        "approved_for_delivery": False, "training_performed": False,
    }
    with (evidence / "validation_report.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="/repo")
    parser.add_argument("--store", default="/store")
    parser.add_argument("--baseline-head", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--resume-partial-init", action="store_true")
    args = parser.parse_args()
    require(args.baseline_head == BASELINE_HEAD, "Unexpected approved baseline.")
    require(os.environ.get("DVC_SITE_CACHE_DIR") == "/tmp/dvc-site-cache", "Expected writable internal cache configuration is missing.")
    try:
        result = register_and_verify(args.repository, args.store, args.baseline_head, args.image_id, resume_partial=args.resume_partial_init)
    except Exception as error:
        raise SystemExit("Versioning stopped. Preserve repository, cache, storage and output.\n" + str(error)) from None
    print("DVC FUNCTIONAL VALIDATION PASSED")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
