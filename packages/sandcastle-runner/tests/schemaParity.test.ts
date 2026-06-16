import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { buildSchemaArtifact, serializeArtifact } from "../src/exportSchemas.js";

const ARTIFACT = fileURLToPath(
  new URL(
    "../../scheduler/src/smda_scheduler/schemas/role_schemas.v1.json",
    import.meta.url,
  ),
);

test("committed schema artifact matches the zod export (drift guard)", () => {
  const committed = readFileSync(ARTIFACT, "utf8");
  assert.equal(
    serializeArtifact(buildSchemaArtifact()),
    committed,
    "role_schemas.v1.json is stale — run `npm run schema:export` and commit",
  );
});
