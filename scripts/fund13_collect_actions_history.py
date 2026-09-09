#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
import zipfile

ARTIFACT_NAME = "fund13-calibration-observation"
SNAPSHOT_VERSION = "fund13_calibration_snapshot_3"


def _request_json(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nabi-fund13-calibration-history",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_bytes(url: str, token: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nabi-fund13-calibration-history",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def _validated_snapshot(raw: bytes, *, source: str) -> dict:
    obj = json.loads(raw.decode("utf-8"))
    if obj.get("snapshot_version") != SNAPSHOT_VERSION:
        raise SystemExit(f"FAIL unsupported FUND13 snapshot: {source}")
    if obj.get("thresholds_proposed") is not False:
        raise SystemExit(f"FAIL threshold proposal in history: {source}")
    if obj.get("thresholds_locked") is not False:
        raise SystemExit(f"FAIL threshold lock in history: {source}")
    if obj.get("band_policy_applied") is not False:
        raise SystemExit(f"FAIL band policy in history: {source}")
    safety = obj.get("safety") or {}
    if safety.get("research_only") is not True:
        raise SystemExit(f"FAIL non-research snapshot: {source}")
    if safety.get("production_persist") is not False:
        raise SystemExit(f"FAIL production persistence snapshot: {source}")
    if safety.get("execution_authority") is not False:
        raise SystemExit(f"FAIL execution authority snapshot: {source}")
    return obj


def _add_snapshot(history_dir: Path, raw: bytes, *, source: str) -> None:
    obj = _validated_snapshot(raw, source=source)
    as_of = obj.get("as_of")
    fp = obj.get("calibration_fingerprint")
    if not isinstance(as_of, str) or not as_of:
        raise SystemExit(f"FAIL missing as_of: {source}")
    if not isinstance(fp, str) or not fp:
        raise SystemExit(f"FAIL missing calibration fingerprint: {source}")

    encoded = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    target = history_dir / f"{as_of}_{fp[:12]}.json"

    for path in sorted(history_dir.glob(f"{as_of}_*.json")):
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("calibration_fingerprint") != fp:
            raise SystemExit(
                f"FAIL conflicting duplicate as_of history: {as_of}:{path}:{source}"
            )
        return

    target.write_text(encoded, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repository", required=True, help="owner/repo")
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--current-observation")
    ap.add_argument("--exclude-run-id", type=int)
    ap.add_argument("--max-artifacts", type=int, default=100)
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("FAIL GITHUB_TOKEN missing")

    history = Path(args.history_dir)
    history.mkdir(parents=True, exist_ok=True)

    if args.current_observation:
        raw = Path(args.current_observation).read_bytes()
        _add_snapshot(history, raw, source="current_observation")

    page = 1
    seen_artifacts = 0
    base = f"https://api.github.com/repos/{args.repository}/actions/artifacts"
    while seen_artifacts < args.max_artifacts:
        url = (
            f"{base}?name={ARTIFACT_NAME}&per_page=100&page={page}"
        )
        payload = _request_json(url, token)
        artifacts = payload.get("artifacts") or []
        if not artifacts:
            break

        for artifact in artifacts:
            if seen_artifacts >= args.max_artifacts:
                break
            seen_artifacts += 1

            if artifact.get("expired") is True:
                continue
            run = artifact.get("workflow_run") or {}
            if args.exclude_run_id and run.get("id") == args.exclude_run_id:
                continue

            archive_url = artifact.get("archive_download_url")
            artifact_id = artifact.get("id")
            if not archive_url:
                raise SystemExit(f"FAIL artifact download URL missing: {artifact_id}")

            data = _request_bytes(archive_url, token)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = [
                    name for name in zf.namelist()
                    if name.endswith(".json")
                    and not name.endswith("fund13_history_analysis_v3.json")
                ]
                if len(names) != 1:
                    raise SystemExit(
                        f"FAIL observation artifact must contain exactly one snapshot JSON: "
                        f"{artifact_id}:{names!r}"
                    )
                raw = zf.read(names[0])
                _add_snapshot(
                    history,
                    raw,
                    source=f"github_artifact:{artifact_id}:{names[0]}",
                )

        if len(artifacts) < 100:
            break
        page += 1

    print("PASS: FUND13 GitHub Actions history collected read-only.")
    print("history_files:", len(list(history.glob("*.json"))))
    print("artifacts_examined:", seen_artifacts)


if __name__ == "__main__":
    main()
