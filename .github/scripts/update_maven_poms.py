#!/usr/bin/env python3
"""Update only safely locatable Maven versions for one artifact."""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.parsers import expat

from find_maven_consumers import scan_pom


VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class XmlNode:
    def __init__(self, name, inner_start):
        self.name = name
        self.inner_start = inner_start
        self.inner_end = None
        self.children = []
        self.text_parts = []

    @property
    def text(self):
        return "".join(self.text_parts)


def find_tag_end(source, start):
    quote = None
    for index in range(start, len(source)):
        character = source[index]
        if quote:
            if character == quote:
                quote = None
        elif character in (ord('"'), ord("'")):
            quote = character
        elif character == ord(">"):
            return index + 1
    raise ValueError("Unclosed XML start tag")


def parse_source_tree(source):
    parser = expat.ParserCreate(namespace_separator="}")
    stack = []
    roots = []

    def start_element(name, _attributes):
        inner_start = find_tag_end(source, parser.CurrentByteIndex)
        node = XmlNode(name.rsplit("}", 1)[-1], inner_start)
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    def end_element(_name):
        node = stack.pop()
        node.inner_end = parser.CurrentByteIndex

    def character_data(value):
        if stack:
            stack[-1].text_parts.append(value)

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = character_data
    parser.Parse(source, True)
    if len(roots) != 1:
        raise ValueError("POM must contain one project root element")
    return roots[0]


def child(node, name):
    return next((element for element in node.children if element.name == name), None) if node else None


def matching_dependencies(container, group_id, artifact_id):
    dependencies = child(container, "dependencies")
    if dependencies is None:
        return []
    return [
        dependency for dependency in dependencies.children
        if dependency.name == "dependency"
        and (child(dependency, "groupId").text.strip() if child(dependency, "groupId") else None) == group_id
        and (child(dependency, "artifactId").text.strip() if child(dependency, "artifactId") else None) == artifact_id
    ]


def find_location_node(project, location, group_id, artifact_id):
    if location["kind"] == "property":
        return child(child(project, "properties"), location["property"])

    if location["section"] == "dependencyManagement":
        dependencies = matching_dependencies(child(project, "dependencyManagement"), group_id, artifact_id)
    else:
        dependencies = matching_dependencies(project, group_id, artifact_id)
    occurrence = location["occurrence"]
    if occurrence >= len(dependencies):
        return None
    return child(dependencies[occurrence], "version")


def update_pom(pom_file, repository_path, group_id, artifact_id, new_version):
    try:
        source = pom_file.read_bytes()
        project = parse_source_tree(source)
        findings, scan_error = scan_pom(pom_file, repository_path, group_id, artifact_id)
    except (OSError, ET.ParseError, expat.ExpatError, ValueError) as error:
        return {"file": pom_file.relative_to(repository_path).as_posix(), "error": str(error), "updated": [], "skipped": []}
    if scan_error:
        return {"file": pom_file.relative_to(repository_path).as_posix(), "error": scan_error, "updated": [], "skipped": []}

    edits = {}
    skipped = []
    for finding in findings:
        location = finding.get("location")
        if finding["status"] != "update" or location is None:
            skipped.append({"status": finding["status"], "reason": finding.get("reason"),
                            "property": finding.get("property")})
            continue
        current_version = finding.get("currentVersion")
        if current_version == new_version:
            skipped.append({"status": "current", "currentVersion": current_version})
            continue

        node = find_location_node(project, location, group_id, artifact_id)
        if node is None or node.inner_end is None or node.children:
            skipped.append({"status": "ambiguous", "reason": "version-node-not-safely-locatable"})
            continue
        raw_value = source[node.inner_start:node.inner_end]
        try:
            raw_text = raw_value.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append({"status": "ambiguous", "reason": "non-UTF8-version-node"})
            continue
        leading = raw_text[:len(raw_text) - len(raw_text.lstrip())]
        trailing = raw_text[len(raw_text.rstrip()):]
        if raw_text.strip() != current_version:
            skipped.append({"status": "ambiguous", "reason": "version-node-contains-unsupported-content"})
            continue

        key = (node.inner_start, node.inner_end)
        edits[key] = {
            "replacement": (leading + new_version + trailing).encode("utf-8"),
            "currentVersion": current_version,
            "location": location,
        }

    if edits:
        updated_source = source
        for (start, end), edit in sorted(edits.items(), reverse=True):
            updated_source = updated_source[:start] + edit["replacement"] + updated_source[end:]
        pom_file.write_bytes(updated_source)

    return {
        "file": pom_file.relative_to(repository_path).as_posix(),
        "updated": [
            {"from": edit["currentVersion"], "to": new_version, "location": edit["location"]}
            for edit in edits.values()
        ],
        "skipped": skipped,
    }


def update_repository(repository_path, group_id, artifact_id, new_version):
    if not VERSION.fullmatch(new_version):
        raise ValueError("Invalid Maven version")
    repository_path = Path(repository_path).resolve()
    results = [
        update_pom(pom_file, repository_path, group_id, artifact_id, new_version)
        for pom_file in sorted(repository_path.rglob("pom.xml"))
    ]
    return {
        "updatedFiles": [result["file"] for result in results if result.get("updated")],
        "changes": [change for result in results for change in result.get("updated", [])],
        "skipped": [
            {"file": result["file"], **item}
            for result in results for item in result.get("skipped", [])
        ],
        "errors": [
            {"file": result["file"], "error": result["error"]}
            for result in results if result.get("error")
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        result = update_repository(args.repository, args.group_id, args.artifact_id, args.version)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())