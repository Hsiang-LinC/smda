import { z } from "zod";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  verdictSchema,
  nextActionSchema,
  graphChildSchema,
  dependencyEdgeSchema,
  roadmapParentSchema,
  roadmapEdgeSchema,
  roleContractManifest,
  roleResultSchemaForId,
} from "./roleContracts.js";

// Path to the checked-in artifact (Python package data).
const ARTIFACT_URL = new URL(
  "../../scheduler/src/smda_scheduler/schemas/role_schemas.v1.json",
  import.meta.url,
);

function uniqueSchemaIds(): string[] {
  const ids = new Set<string>();
  for (const role of Object.values(roleContractManifest.roles)) {
    ids.add(role.schema_id);
  }
  return [...ids].sort();
}

export function buildSchemaArtifact(): unknown {
  const jsonSchemas: Record<string, unknown> = {};
  for (const schemaId of uniqueSchemaIds()) {
    jsonSchemas[schemaId] = z.toJSONSchema(roleResultSchemaForId(schemaId));
  }
  return {
    schema_package_version: roleContractManifest.schema_package_version,
    enums: {
      verdict: [...verdictSchema.options],
      next_action: [...nextActionSchema.options],
      dependency_edge_type: [...dependencyEdgeSchema.shape.type.options],
      risk_level: [...graphChildSchema.shape.risk_level.options],
    },
    shapes: {
      graph_decomposer_child: Object.keys(graphChildSchema.shape),
      dependency_edge: Object.keys(dependencyEdgeSchema.shape),
      roadmap_decomposer_parent: Object.keys(roadmapParentSchema.shape),
      roadmap_edge: Object.keys(roadmapEdgeSchema.shape),
    },
    json_schemas: jsonSchemas,
  };
}

// Deterministic serialization: sort object keys recursively, preserve array
// order (enum/field order is meaningful). Keeps the parity test stable.
function sortKeysDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      out[key] = sortKeysDeep((value as Record<string, unknown>)[key]);
    }
    return out;
  }
  return value;
}

export function serializeArtifact(value: unknown): string {
  return JSON.stringify(sortKeysDeep(value), null, 2) + "\n";
}

const isMain =
  process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  writeFileSync(ARTIFACT_URL, serializeArtifact(buildSchemaArtifact()));
  console.log(`wrote ${fileURLToPath(ARTIFACT_URL)}`);
}
