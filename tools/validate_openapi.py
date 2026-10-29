"""Offline OpenAPI 3.1 structure, references, JSON Schemas and recorded wire validation.

Run with the existing root interpreter (jsonschema is already installed there).
The exporter separately validates FastAPI's OpenAPI model in Member A's interpreter.
"""

import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def validate_document(document, cases=()):
    assert document["openapi"] == "3.1.0"
    assert document["info"]["title"] and document["info"]["version"]
    schemas = document["components"]["schemas"]
    schemes = document["components"].get("securitySchemes", {})
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    refs = 0
    for node in nodes(document):
        if "$ref" in node:
            ref = node["$ref"]
            assert ref.startswith("#/"), "External references are forbidden offline"
            target = document
            for segment in ref[2:].split("/"):
                target = target[segment.replace("~1", "/").replace("~0", "~")]
            refs += 1
        if "discriminator" in node:
            for ref in node["discriminator"].get("mapping", {}).values():
                assert ref.startswith("#/components/schemas/")
                assert ref.rsplit("/", 1)[1] in schemas
    identifiers = []
    operations = []
    for path, item in document["paths"].items():
        assert path.startswith("/")
        for method, operation in item.items():
            if method not in METHODS:
                continue
            identifiers.append(operation["operationId"])
            operations.append((method, path))
            parameters = item.get("parameters", []) + operation.get("parameters", [])
            keys = [(parameter["in"], parameter["name"]) for parameter in parameters]
            assert len(keys) == len(set(keys)), "Duplicate parameter"
            path_parameters = {p["name"] for p in parameters if p["in"] == "path"}
            assert path_parameters == set(re.findall(r"{([^}]+)}", path))
            assert all(p["required"] for p in parameters if p["in"] == "path")
            for requirement in operation.get("security", document.get("security", [])):
                assert set(requirement) <= set(schemes)
            assert operation["responses"]
            for status, response in operation["responses"].items():
                assert status == "default" or re.fullmatch(r"[1-5](?:[0-9]{2}|XX)", status)
                assert isinstance(response["description"], str)
                if status == "204":
                    assert not response.get("content")
            if method in ("post", "put", "patch"):
                assert operation["requestBody"]["required"]
            for node in nodes(operation):
                if "schema" in node:
                    Draft202012Validator.check_schema(node["schema"])
    assert len(identifiers) == len(set(identifiers)), "Conflicting operation IDs"

    def wire_validator(schema):
        # Local root keeps $refs offline; no registry can fetch an external resource.
        return Draft202012Validator(
            {"components": document["components"], **schema}, format_checker=FormatChecker()
        )

    for name, schema in schemas.items():
        for node in nodes(schema):
            for value in [node["default"]] if "default" in node else []:
                assert not list(wire_validator(node).iter_errors(value)), f"Invalid default: {name}"
    for case in cases:
        operation = document["paths"][case["path"]][case["method"]]
        if case.get("request") is not None:
            candidate = operation["requestBody"]["content"]["application/json"]["schema"]
            errors = list(wire_validator(candidate).iter_errors(case["request"]))
            assert (not errors) == case.get("request_valid", True), (
                f"Request schema mismatch: {case['method']} {case['path']}"
            )
        status = str(case["status"])
        response = operation["responses"][status]
        if status == "204":
            assert case["body"] is None
        else:
            candidate = response["content"][case.get("media", "application/json")]["schema"]
            errors = list(wire_validator(candidate).iter_errors(case["body"]))
            assert not errors, f"Response schema mismatch: {case['method']} {case['path']} {status}"
    return {
        "operations": len(operations),
        "schemas": len(schemas),
        "references": refs,
        "cases": len(cases),
    }


def main():
    document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cases = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")) if len(sys.argv) > 2 else ()
    print(json.dumps(validate_document(document, cases), sort_keys=True))


if __name__ == "__main__":
    main()
