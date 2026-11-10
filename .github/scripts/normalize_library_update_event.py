#!/usr/bin/env python3
"""Normalize and validate manual and release-triggered Maven update events."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from find_maven_consumers import backend_repositories


COORDINATE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
RELEASE_EVENT = "maven-library-released"


def github_repository(url):
    if url.startswith("git@github.com:"):
        repository = url[len("git@github.com:"):]
    else:
        parsed = urlparse(url)
        if parsed.hostname != "github.com":
            return None
        repository = parsed.path.lstrip("/")
    repository = repository.removesuffix(".git")
    return repository.lower() if repository.count("/") == 1 else None


def allowed_library_repositories(root):
    return {
        github_repository(repository["url"])
        for repository in backend_repositories(Path(root))
        if repository["path"].startswith("backend/libs/") and github_repository(repository["url"])
    }


def normalize_event(event_name, event_payload, manual_inputs, allowed_repositories):
    if event_name == "workflow_dispatch":
        values = manual_inputs
    elif event_name == "repository_dispatch":
        if event_payload.get("action") != RELEASE_EVENT:
            raise ValueError("Unsupported repository dispatch event")
        client_payload = event_payload.get("client_payload") or {}
        source_repository = client_payload.get("sourceRepository")
        if not isinstance(source_repository, str):
            raise ValueError("Release source is not an inventoried backend library")
        if source_repository.lower() not in allowed_repositories:
            raise ValueError("Release source is not an inventoried backend library")
        values = client_payload
    else:
        raise ValueError("Unsupported workflow event")

    result = {
        "groupId": str(values.get("groupId", "")).strip(),
        "artifactId": str(values.get("artifactId", "")).strip(),
        "version": str(values.get("version", "")).strip(),
    }
    if any(len(value) > 255 for value in result.values()):
        raise ValueError("Maven coordinates and version must be at most 255 characters")
    if not COORDINATE.fullmatch(result["groupId"]):
        raise ValueError("Invalid Maven groupId")
    if not COORDINATE.fullmatch(result["artifactId"]):
        raise ValueError("Invalid Maven artifactId")
    if not VERSION.fullmatch(result["version"]):
        raise ValueError("Invalid Maven version")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not event_path or not output_path:
        print("GITHUB_EVENT_PATH and GITHUB_OUTPUT are required", file=sys.stderr)
        return 2

    try:
        with open(event_path, encoding="utf-8") as event_file:
            event_payload = json.load(event_file)
        result = normalize_event(
            os.environ.get("GITHUB_EVENT_NAME", ""),
            event_payload,
            {
                "groupId": os.environ.get("MANUAL_GROUP_ID", ""),
                "artifactId": os.environ.get("MANUAL_ARTIFACT_ID", ""),
                "version": os.environ.get("MANUAL_VERSION", ""),
            },
            allowed_library_repositories(args.root),
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1

    with open(output_path, "a", encoding="utf-8") as output_file:
        for name, value in result.items():
            output_file.write(f"{name}={value}\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())