"""Register one approved opaque candidate and recover it once from a local store.

This finite tool runs only in new isolated workspaces. It never loads a model,
uses the repository cache, changes serving selection, or replays a failed phase.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


RUN = "reference_20261011T144150Z_19d3274fd12e49d5b3cb9abbd73da5ea"
INVOCATION = "19d3274fd12e49d5b3cb9abbd73da5ea"
MLFLOW = "dcaea4d2f6ef4b3087f86e8bde3365d7"
MODEL = "data/runs/" + RUN + "/model/trained_model.joblib"
SHA256 = "9dcd169ed58e0b09a2367b17055abee4b7424741d1b02fa60aa196fe049f6b99"
MD5 = "b2d9206c3d45a8c77599915c46e8cacb"
SIZE = 107180009
IMAGE = "sha256:02d4a4e4c447f07446899843b89bb459edf6e79f561ccb8008974fccd1abbfb9"
HEAD = "9f7028d9702f006159d8d68b067863f6db77a766"
POINTER = "versioning/candidate_20261011_19d3274f_model.dvc"
MANIFEST = "versioning/candidate_20261011_19d3274f_manifest.json"
DVC_VERSION = "3.67.1"


def utc():
    return datetime.now(timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(path):
    path = Path(path)
    require(path.is_file(), "Required regular file is missing: " + str(path))
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Linked path rejected: " + str(path))
    sha = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
            md5.update(chunk)
    return {"size_bytes": path.stat().st_size, "sha256": sha.hexdigest(), "md5": md5.hexdigest()}


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def verify_model(path):
    actual = identity(path)
    require(actual == {"size_bytes": SIZE, "sha256": SHA256, "md5": MD5}, "Candidate byte identity differs.")
    return actual


def verify_pointer(work):
    path = work / POINTER
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(set(content) == {"wdir", "outs"} and content["wdir"] == "..", "Unexpected pointer scope.")
    require(len(content["outs"]) == 1, "Pointer must select exactly one file.")
    out = content["outs"][0]
    require(out["path"] == MODEL and out["md5"] == MD5 and out["size"] == SIZE, "Pointer identity differs.")
    require(out.get("hash", "md5") == "md5" and set(out) <= {"path", "md5", "size", "hash"}, "Unexpected pointer fields.")
    return identity(path)["sha256"]


class Phase:
    def __init__(self, mode, work):
        self.mode = mode
        self.work = work
        self.sequence = 0
        self.remote_outcome = "not_attempted"
        self.pull_attempts = 0
        self.result = {
            "schema_name": "candidate_recovery_phase_v1",
            "phase": mode, "status": "running", "started_at_utc": utc(),
            "model_relative_path": MODEL, "expected_sha256": SHA256,
            "training_performed": False, "model_deserialized": False,
            "approved_for_delivery": False, "level_1": "NON_FINAL",
        }

    def command(self, *args):
        self.sequence += 1
        record = {"argv": [sys.executable, "-m", "dvc", *args], "started_at_utc": utc(), "exit_code": None}
        try:
            process = subprocess.run(
                record["argv"], cwd=self.work, capture_output=True, text=True, timeout=600,
                env={**os.environ, "DVC_NO_ANALYTICS": "1"},
            )
            record.update(exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr)
        except Exception as error:
            record["error"] = str(error)
            raise
        finally:
            record["finished_at_utc"] = utc()
            write_json(self.work / ("command_%02d.json" % self.sequence), record)
        require(process.returncode == 0, "DVC command failed (exit %s): %s\n%s" % (
            process.returncode, " ".join(args), (process.stderr or process.stdout)[-6000:]))
        return process.stdout.strip()

    def initialise(self):
        require(not (self.work / ".dvc").exists(), "Existing DVC workspace preserved; no replay.")
        require(not (self.work / ".git").exists(), "Git repository must not be exposed.")
        version = self.command("--version")
        require(version == DVC_VERSION, "Actual DVC version differs: " + version)
        self.result["actual_dvc_version"] = version
        self.command("init", "--no-scm")
        self.command("config", "core.analytics", "false")
        self.command("config", "core.autostage", "false")
        self.command("config", "cache.type", "copy")
        self.command("config", "cache.dir", str(self.work / ".dvc" / "cache"))
        self.command("remote", "add", "--local", "--default", "reference", "/store/objects")
        cache = self.work / ".dvc" / "cache"
        require(not cache.exists() or not any(cache.iterdir()), "Phase cache is not empty.")
        self.result.update(cache_initially_empty=True, cache_path=str(cache), scm="none", cache_type="copy")

    def registration(self, context):
        require(not (self.work / "versioning").exists(), "Registration metadata already exists.")
        verify_model(self.work / MODEL)
        remote_object = Path("/store/objects/files/md5") / MD5[:2] / MD5[2:]
        require(not remote_object.exists(), "Existing candidate store object preserved; no replay.")
        self.initialise()
        (self.work / "versioning").mkdir()
        with (self.work / POINTER).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write("wdir: ..\nouts:\n  - path: " + MODEL + "\n")
        self.command("commit", "--force", "--no-relink", POINTER)
        pointer_sha = verify_pointer(self.work)
        require(not json.loads(self.command("status", "--json", POINTER)), "Candidate DVC cache is incomplete.")
        verify_model(self.work / MODEL)
        require(not remote_object.exists(), "Candidate object appeared before transfer; stop without overwriting.")
        self.remote_outcome = "unknown"
        self.command("push", "--remote", "reference", POINTER)
        verify_model(remote_object)
        self.remote_outcome = "confirmed_exact_bytes_in_local_store"
        manifest = {
            "schema_name": "candidate_model_identity_v1",
            "scope": "one_opaque_candidate_model",
            "run_id": RUN, "invocation_id": INVOCATION, "mlflow_run_id": MLFLOW,
            "model": {"relative_path": MODEL, "size_bytes": SIZE, "sha256": SHA256, "dvc_md5": MD5},
            "pointer": {"relative_path": POINTER, "sha256": pointer_sha},
            "linked_historical_evidence": context["linked_historical_evidence"],
            "registration": {
                "git_head": HEAD, "branch": context["branch"], "image_id": IMAGE,
                "dvc_version": DVC_VERSION, "registrar_sha256": identity(__file__)["sha256"],
                "launcher_sha256": context["launcher_sha256"], "registered_at_utc": utc(),
                "evidence_directory": context["evidence_directory"],
                "context_sha256": identity("/context.json")["sha256"],
                "training_identity_source": "linked historical evidence; registration identities are separate",
            },
            "historical_approved_for_delivery": False,
            "approved_for_delivery": False, "training_performed": False,
            "model_deserialized": False, "level_1": "NON_FINAL",
            "recovery_evidence": "separate phase_result.json; registration alone does not prove recovery",
        }
        write_json(self.work / MANIFEST, manifest)
        self.result.update(pointer_sha256=pointer_sha, manifest_sha256=identity(self.work / MANIFEST)["sha256"])

    def recovery(self):
        # Only detached metadata and the read-only store may be available here.
        require(not (self.work / MODEL).exists(), "Recovery destination must be absent.")
        pointer_sha = verify_pointer(self.work)
        manifest = json.loads((self.work / MANIFEST).read_text(encoding="utf-8"))
        require(manifest["schema_name"] == "candidate_model_identity_v1", "Unexpected manifest schema.")
        require((manifest["run_id"], manifest["invocation_id"], manifest["mlflow_run_id"]) == (RUN, INVOCATION, MLFLOW), "Recovery linkage differs.")
        require(manifest["model"] == {"relative_path": MODEL, "size_bytes": SIZE, "sha256": SHA256, "dvc_md5": MD5}, "Manifest model identity differs.")
        require(manifest["pointer"] == {"relative_path": POINTER, "sha256": pointer_sha}, "Manifest pointer identity differs.")
        require(manifest["approved_for_delivery"] is False, "Historical approval must remain false.")
        self.initialise()
        self.pull_attempts = 1
        self.command("pull", "--remote", "reference", POINTER)
        recovered = verify_model(self.work / MODEL)
        require(verify_pointer(self.work) == pointer_sha, "Recovery changed the pointer.")
        self.result.update(
            restored_identity=recovered, restored_path=str(self.work / MODEL),
            pointer_sha256=pointer_sha, manifest_sha256=identity(self.work / MANIFEST)["sha256"],
            source_model_access=False, primary_cache_access=False, registration_cache_access=False,
        )

    def run(self, context):
        try:
            require(context["git_head"] == HEAD and context["branch"] == "work/candidate-recovery", "Registration Git identity differs.")
            require(context["image_id"] == IMAGE, "Tool image identity differs.")
            require(context["registrar_sha256"] == identity(__file__)["sha256"], "Mounted registrar differs.")
            require(os.environ.get("DVC_SITE_CACHE_DIR") == "/work/site-cache", "Unexpected internal cache path.")
            if self.mode == "registration":
                self.registration(context)
            else:
                self.recovery()
            self.result["status"] = "passed"
        except Exception as error:
            self.result.update(status="failed", primary_error=str(error))
            raise
        finally:
            self.result.update(
                finished_at_utc=utc(), command_count=self.sequence,
                remote_transfer_outcome=self.remote_outcome, dvc_pull_attempts=self.pull_attempts,
                failure_policy="preserve all state; no cleanup or automatic replay",
            )
            write_json(self.work / "phase_result.json", self.result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("registration", "recovery"))
    args = parser.parse_args()
    work = Path("/work")
    context = json.loads(Path("/context.json").read_text(encoding="utf-8"))
    phase = Phase(args.phase, work)
    try:
        phase.run(context)
    except Exception as error:
        print("STOP: preserve partial state and command records.\n" + str(error), file=sys.stderr)
        return 1
    print(json.dumps(phase.result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
