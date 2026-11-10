#!/usr/bin/env python3
"""Create one independent update branch and pull request per Maven consumer."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from find_maven_consumers import scan
from update_maven_poms import update_repository


def branch_name(group_id, artifact_id, version):
    def slug(value, limit):
        value = re.sub(r"[^A-Za-z0-9-]+", "-", value).strip("-").lower()
        return value[:limit].rstrip("-") or "artifact"

    digest = hashlib.sha256(f"{group_id}:{artifact_id}:{version}".encode("utf-8")).hexdigest()[:10]
    return f"chore/maven-{slug(group_id, 32)}-{slug(artifact_id, 32)}-{slug(version, 48)}-{digest}"


def run(command, cwd=None, check=True):
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Command failed ({' '.join(command)}): {detail}")
    return result


def validate_repository_url(url):
    parsed = urlparse(url)
    repository_path = parsed.path.strip("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", repository_path)
    ):
        raise ValueError("Submodule URL is not an allowed HTTPS GitHub URL")


def existing_pull_request(repository_path, branch):
    result = run(["gh", "pr", "view", branch, "--json", "url", "--jq", ".url"],
                 cwd=repository_path, check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    if "no pull requests found" in result.stderr.lower():
        return None
    raise RuntimeError(f"Could not check pull request for branch {branch}: {result.stderr.strip()}")


def process_consumer(consumer, group_id, artifact_id, version):
    repository = consumer["repository"]
    repository_url = repository["url"]
    validate_repository_url(repository_url)
    base_branch = repository.get("branch") or "main"
    branch = branch_name(group_id, artifact_id, version)

    with tempfile.TemporaryDirectory(prefix="maven-dependent-") as temporary_directory:
        repository_path = Path(temporary_directory) / "consumer"
        remote_branch = run(
            ["git", "ls-remote", "--heads", repository_url, f"refs/heads/{branch}"], check=True
        ).stdout.strip()
        run(["git", "clone", "--depth", "1", "--branch", base_branch, repository_url, str(repository_path)])
        if remote_branch:
            run(["git", "fetch", "--depth", "1", "origin", branch], cwd=repository_path)
            run(["git", "checkout", "-B", branch, "FETCH_HEAD"], cwd=repository_path)
        else:
            run(["git", "checkout", "-b", branch], cwd=repository_path)

        update = update_repository(repository_path, group_id, artifact_id, version)
        if update["errors"]:
            raise RuntimeError(json.dumps(update["errors"], sort_keys=True))
        if not update["updatedFiles"]:
            pull_request = existing_pull_request(repository_path, branch)
            if pull_request:
                return {"status": "existing", "repository": repository["name"], "pullRequest": pull_request}
            return {
                "status": "ignored",
                "repository": repository["name"],
                "reason": "no-local-version-change",
                "skipped": update["skipped"],
            }

        run(["git", "diff", "--check"], cwd=repository_path)
        run(["git", "config", "user.name", "github-actions[bot]"], cwd=repository_path)
        run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
            cwd=repository_path)
        run(["git", "add", "--", *update["updatedFiles"]], cwd=repository_path)
        run(["git", "commit", "-m", f"Update {group_id}:{artifact_id} to {version}"], cwd=repository_path)
        run(["git", "push", "--set-upstream", "origin", branch], cwd=repository_path)

        pull_request = existing_pull_request(repository_path, branch)
        if not pull_request:
            title = f"Update {group_id}:{artifact_id} to {version}"
            previous_versions = sorted({change["from"] for change in update["changes"]})
            body = (
                f"Update the Maven dependency `{group_id}:{artifact_id}` to `{version}`.\n\n"
                f"Previous version(s): {', '.join(f'`{item}`' for item in previous_versions)}.\n\n"
                "This pull request was generated from the aggregator's submodule inventory."
            )
            unsupported = [
                item for item in update["skipped"]
                if item.get("status") in ("inherited", "ambiguous")
            ]
            if unsupported:
                body += "\n\nSome matching declarations were not changed because their version source is inherited or ambiguous."
            pull_request = run(
                ["gh", "pr", "create", "--base", base_branch, "--head", branch,
                 "--title", title, "--body", body],
                cwd=repository_path,
            ).stdout.strip()

        return {
            "status": "updated",
            "repository": repository["name"],
            "pullRequest": pull_request,
            "updatedFiles": update["updatedFiles"],
            "skipped": update["skipped"],
        }


def process_consumers(consumers, group_id, artifact_id, version, processor=process_consumer):
    summary = {"successes": [], "ignored": [], "errors": []}
    for consumer in consumers:
        try:
            result = processor(consumer, group_id, artifact_id, version)
            target = "ignored" if result["status"] == "ignored" else "successes"
            summary[target].append(result)
        except Exception as error:
            summary["errors"].append({
                "repository": consumer["repository"]["name"],
                "error": str(error),
            })
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        result = scan(args.root, args.group_id, args.artifact_id)
        summary = process_consumers(result["consumers"], args.group_id, args.artifact_id, args.version)
        summary["errors"] = result["errors"] + summary["errors"]
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())