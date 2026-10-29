import { readFileSync, writeFileSync } from "node:fs";
import openapiTS, { astToString } from "openapi-typescript";

const schema = JSON.parse(
  readFileSync(
    new URL(
      "../../docs/frontend-handoff/generated/ghost-app-v1.openapi.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
// The generator treats discriminator mapping keys as strings, overriding boolean consts.
// Remove only redundant discriminator metadata in memory; retain oneOf and exact consts.
for (const model of Object.values(schema.components.schemas)) {
  for (const field of Object.values(model.properties ?? {})) {
    const discriminator = field.discriminator;
    if (!discriminator) continue;
    const targets = Object.values(discriminator.mapping ?? {}).map(
      (ref) => schema.components.schemas[ref.split("/").at(-1)],
    );
    if (
      targets.length &&
      targets.every(
        (target) =>
          target.properties?.[discriminator.propertyName]?.type === "boolean",
      )
    )
      delete field.discriminator;
  }
}
const result = await openapiTS(schema);
writeFileSync(
  new URL("../src/lib/api/schema.d.ts", import.meta.url),
  astToString(result),
);
