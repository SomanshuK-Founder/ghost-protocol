import { readFileSync, writeFileSync } from "node:fs";
const api = JSON.parse(
  readFileSync(
    new URL(
      "../../docs/frontend-handoff/generated/ghost-app-v1.openapi.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const screen = (path) => {
  if (path === "/health") return "Public liveness (not consumed by app client)";
  if (path.endsWith("/cancel"))
    return "Task workspace / confirmed cancellation";
  if (path.endsWith("/continue"))
    return "Task workspace / separate safe continuation";
  if (path.includes("session")) return "Pairing / session";
  if (path.includes("documents")) return "Document catalog / task composer";
  if (path.endsWith("/timeline")) return "Audit explorer / task preview";
  if (path.includes("/operations")) return "Operation history / exact record";
  if (path.includes("approvals"))
    return "Approval center / exact review / explicit decision and revocation";
  return "Dashboard / task workspace";
};
const rows = Object.entries(api.paths).flatMap(([path, methods]) =>
  Object.entries(methods)
    .filter(([method]) => ["get", "post"].includes(method))
    .map(
      ([method, op]) =>
        `| ${screen(path)} | ${method.toUpperCase()} ${path} | ${op.operationId} | ${JSON.stringify(op.security ?? [])} |`,
    ),
);
const details = Object.entries(api.paths).flatMap(([path, methods]) =>
  Object.entries(methods)
    .filter(([method]) => ["get", "post"].includes(method))
    .map(([method, op]) => {
      const name = (schema) =>
        schema?.$ref?.split("/").at(-1) ??
        (schema ? JSON.stringify(schema) : "No JSON body");
      const responses = Object.entries(op.responses)
        .map(
          ([status, response]) =>
            `${status}: ${name(response.content?.["application/json"]?.schema)}`,
        )
        .join("; ");
      const parameters =
        (op.parameters ?? [])
          .map(
            (p) =>
              `${p.in} ${p.name}${p.required ? " (required)" : " (optional)"}`,
          )
          .join(", ") || "None";
      return `### ${op.operationId}\n\n${method.toUpperCase()} ${path}\n\n- Request: ${name(op.requestBody?.content?.["application/json"]?.schema)}\n- Parameters: ${parameters}\n- Responses: ${responses}\n`;
    }),
);
writeFileSync(
  new URL("../API_OPERATIONS.md", import.meta.url),
  `# Generated operation map\n\nSource: accepted ghost-app-v1 OpenAPI; regenerate with npm run generate:api.\nAll 19 browser operations have frontend interactions in Phases 1–3. Public health is not consumed by the app client. Operation pages organize the bounded returned set; only tasks, documents and timeline expose backend cursors.\n\n| Screen / scope | Method and path | Exact operation ID | Security |\n| --- | --- | --- | --- |\n${rows.join("\n")}\n\n## Exact request and response inventory\n\n${details.join("\n")}\n`,
);
