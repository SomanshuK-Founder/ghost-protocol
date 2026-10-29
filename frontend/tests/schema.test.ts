import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { Session } from "../src/lib/api/types.ts";
test("generated session boolean constants match canonical schema", () => {
  const schema = JSON.parse(
    readFileSync(
      new URL(
        "../../docs/frontend-handoff/generated/ghost-app-v1.openapi.json",
        import.meta.url,
      ),
      "utf8",
    ),
  );
  const anonymous: Session["authenticated"] = false;
  const authenticated: Session["authenticated"] = true;
  assert.equal(
    schema.components.schemas.AnonymousSession.properties.authenticated.const,
    anonymous,
  );
  assert.equal(
    schema.components.schemas.OwnerSession.properties.authenticated.const,
    authenticated,
  );
  const generated = readFileSync(
    new URL("../src/lib/api/schema.d.ts", import.meta.url),
    "utf8",
  );
  assert.match(generated, /authenticated: false;/);
  assert.match(generated, /authenticated: true;/);
  assert.doesNotMatch(generated, /authenticated: "(?:true|false)"/);
});
test("all 19 browser operation IDs appear in the generated map", () => {
  const schema = JSON.parse(
    readFileSync(
      new URL(
        "../../docs/frontend-handoff/generated/ghost-app-v1.openapi.json",
        import.meta.url,
      ),
      "utf8",
    ),
  );
  const mapping = readFileSync(
    new URL("../API_OPERATIONS.md", import.meta.url),
    "utf8",
  );
  const operations = Object.entries(schema.paths)
    .filter(([path]) => path.startsWith("/api/app/v1/"))
    .flatMap(([, methods]) =>
      Object.values(methods as Record<string, { operationId: string }>),
    );
  assert.equal(operations.length, 19);
  for (const operation of operations)
    assert.ok(mapping.includes(operation.operationId));
});
