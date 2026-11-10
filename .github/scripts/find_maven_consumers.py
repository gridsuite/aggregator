#!/usr/bin/env python3
"""Find backend Maven POMs that declare a dependency on an artifact."""

import argparse
import configparser
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


PROPERTY_REFERENCE = re.compile(r"^\$\{([^}]+)}$")


def local_name(element):
    return element.tag.rsplit("}", 1)[-1]


def child(element, name):
    if element is None:
        return None
    return next((item for item in element if local_name(item) == name), None)


def text(element, name):
    item = child(element, name)
    return item.text.strip() if item is not None and item.text else None


def backend_repositories(root):
    """Read backend repositories from the submodule inventory."""
    config = configparser.ConfigParser(interpolation=None)
    inventory = root / ".gitmodules"
    if not inventory.is_file():
        raise ValueError(f"Missing submodule inventory: {inventory}")
    config.read(inventory, encoding="utf-8")

    repositories = []
    for section in config.sections():
        if not section.startswith("submodule "):
            continue
        path = config.get(section, "path", fallback="").strip()
        if not path.startswith("backend/"):
            continue
        repositories.append({
            "name": section[len('submodule "'):-1] if section.endswith('"') else section,
            "path": path,
            "url": config.get(section, "url", fallback="").strip(),
            "branch": config.get(section, "branch", fallback="main").strip(),
        })
    return repositories


def property_elements(project):
    properties = child(project, "properties")
    if properties is None:
        return {}
    result = {}
    for element in properties:
        result.setdefault(local_name(element), []).append(element)
    return result


def make_location(pom_path, kind, property_name=None, section=None, occurrence=None, dependency_management=False):
    location = {"file": pom_path.as_posix(), "kind": kind}
    if property_name is not None:
        location["property"] = property_name
    if kind == "version":
        location["section"] = section
        location["occurrence"] = occurrence
    if dependency_management and kind == "version":
        location["source"] = "dependencyManagement"
    return location


def property_is_exclusive(project, property_name, group_id, artifact_id):
    parents = {child_element: parent for parent in project.iter() for child_element in parent}
    reference = re.compile(r"\$\{" + re.escape(property_name) + r"}")
    for element in project.iter():
        value = element.text.strip() if element.text else ""
        if not reference.search(value):
            continue
        dependency = parents.get(element)
        if (
            local_name(element) != "version"
            or dependency is None
            or local_name(dependency) != "dependency"
            or text(dependency, "groupId") != group_id
            or text(dependency, "artifactId") != artifact_id
            or value != "${" + property_name + "}"
        ):
            return False
    return True


def version_finding(version_element, properties, pom_path, project, group_id, artifact_id,
                    section, occurrence, dependency_management=False):
    value = version_element.text.strip() if version_element is not None and version_element.text else None
    if value is None:
        return {
            "status": "inherited",
            "reason": "version-not-declared-locally",
            "currentVersion": None,
            "location": None,
        }

    reference = PROPERTY_REFERENCE.fullmatch(value)
    if reference is None:
        return {
            "status": "update",
            "reason": None,
            "currentVersion": value,
            "location": make_location(pom_path, "version", section=section, occurrence=occurrence,
                                       dependency_management=dependency_management),
        }

    property_name = reference.group(1)
    definitions = properties.get(property_name, [])
    if len(definitions) > 1:
        return {
            "status": "ambiguous",
            "reason": "property-defined-multiple-times",
            "currentVersion": value,
            "location": None,
            "property": property_name,
        }
    if not definitions:
        return {
            "status": "inherited",
            "reason": "version-property-not-defined-locally",
            "currentVersion": value,
            "location": None,
            "property": property_name,
        }

    property_value = definitions[0].text.strip() if definitions[0].text else None
    if not property_value or "${" in property_value:
        return {
            "status": "ambiguous",
            "reason": "version-property-is-not-a-literal",
            "currentVersion": property_value,
            "location": None,
            "property": property_name,
        }
    if not property_is_exclusive(project, property_name, group_id, artifact_id):
        return {
            "status": "ambiguous",
            "reason": "version-property-is-shared",
            "currentVersion": property_value,
            "location": None,
            "property": property_name,
        }
    return {
        "status": "update",
        "reason": None,
        "currentVersion": property_value,
        "location": make_location(pom_path, "property", property_name, section=section,
                                   occurrence=occurrence, dependency_management=dependency_management),
    }


def matching_dependencies(container, group_id, artifact_id):
    if container is None:
        return []
    dependencies = child(container, "dependencies")
    if dependencies is None:
        return []
    return [
        dependency for dependency in dependencies
        if text(dependency, "groupId") == group_id and text(dependency, "artifactId") == artifact_id
    ]


def scan_pom(pom_file, repository_path, group_id, artifact_id):
    try:
        project = ET.parse(pom_file).getroot()
    except (ET.ParseError, OSError) as error:
        return [], str(error)

    properties = property_elements(project)
    pom_path = pom_file.relative_to(repository_path)
    dependency_management = child(child(project, "dependencyManagement"), "dependencies")
    managed = [
        dependency for dependency in list(dependency_management or [])
        if local_name(dependency) == "dependency"
        and text(dependency, "groupId") == group_id
        and text(dependency, "artifactId") == artifact_id
    ]

    findings = []
    dependencies = matching_dependencies(project, group_id, artifact_id)
    for occurrence, dependency in enumerate(dependencies):
        version = child(dependency, "version")
        if version is not None:
            findings.append(version_finding(version, properties, pom_path, project, group_id, artifact_id,
                                            "dependencies", occurrence))
        elif len(managed) == 1:
            findings.append(version_finding(child(managed[0], "version"), properties, pom_path, project,
                                            group_id, artifact_id, "dependencyManagement", 0, True))
        elif len(managed) > 1:
            findings.append({
                "status": "ambiguous",
                "reason": "multiple-local-managed-dependencies",
                "currentVersion": None,
                "location": None,
            })
        else:
            findings.append(version_finding(None, properties, pom_path, project, group_id, artifact_id,
                                            "dependencies", occurrence))

    # A dependency-management POM is itself a consumer declaration, even when it
    # does not use the managed dependency in its own <dependencies> section.
    for occurrence, dependency in enumerate(managed):
        findings.append(version_finding(child(dependency, "version"), properties, pom_path, project,
                                        group_id, artifact_id, "dependencyManagement", occurrence, True))

    unique = {}
    for finding in findings:
        location = finding.get("location")
        key = (
            location.get("file"), location.get("kind"), location.get("property"),
            location.get("section"), location.get("occurrence"), location.get("source"),
        ) if location else None
        if key is not None:
            unique.setdefault(key, finding)
        else:
            unique[(finding["status"], finding["reason"], finding.get("property"))] = finding
    return list(unique.values()), None


def scan(root, group_id, artifact_id):
    root = Path(root).resolve()
    consumers = []
    errors = []
    for repository in backend_repositories(root):
        relative_path = Path(repository["path"])
        repository_path = (root / relative_path).resolve()
        if relative_path.is_absolute() or ".." in relative_path.parts or root not in repository_path.parents:
            errors.append({"repository": repository, "error": "Submodule path escapes the workspace"})
            continue
        if not repository_path.is_dir():
            errors.append({"repository": repository, "error": "Submodule is not checked out"})
            continue

        matches = []
        for pom_file in sorted(repository_path.rglob("pom.xml")):
            findings, error = scan_pom(pom_file, repository_path, group_id, artifact_id)
            if error:
                errors.append({"repository": repository, "pom": pom_file.relative_to(root).as_posix(), "error": error})
            if findings:
                matches.append({"pom": pom_file.relative_to(root).as_posix(), "matches": findings})
        if matches:
            consumers.append({"repository": repository, "poms": matches})

    return {
        "groupId": group_id,
        "artifactId": artifact_id,
        "consumers": consumers,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="aggregator checkout root")
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--artifact-id", required=True)
    args = parser.parse_args()
    if not args.group_id.strip() or not args.artifact_id.strip():
        parser.error("groupId and artifactId must not be empty")
    try:
        result = scan(args.root, args.group_id.strip(), args.artifact_id.strip())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
