import { z } from "zod";

export const verdictSchema = z.enum([
  "DONE",
  "DONE_WITH_CONCERNS",
  "PASS",
  "FAIL",
  "NEEDS_CONTEXT",
  "BLOCKED",
  "HUMAN_REVIEW",
]);

export const nextActionSchema = z.enum([
  "submit_for_graph_review",
  "submit_for_graph_execution_review",
  "publish_child_issues",
  "publish_roadmap_parents",
  "submit_for_spec_review",
  "submit_for_quality_review",
  "fix_spec",
  "fix_quality",
  "accept_candidate",
  "accept_parent",
  "plan_remediation",
  "retry_child_acceptance",
  "request_human_review",
]);

export const roleResultSchema = z.object({
  verdict: verdictSchema,
  required_next_action: nextActionSchema,
  report: z.string().optional(),
});

export const graphChildSchema = z.object({
  node_id: z.string().min(1),
  title: z.string().min(1),
  body: z.string().min(1),
  in_scope: z.array(z.string().min(1)).min(1),
  out_of_scope: z.array(z.string().min(1)).min(1),
  touched_surfaces: z.object({
    files: z.array(z.string().min(1)).min(1),
    modules: z.array(z.string().min(1)).min(1),
    contracts: z.array(z.string().min(1)).min(1),
    docs: z.array(z.string().min(1)).min(1),
    tests: z.array(z.string().min(1)).min(1),
  }),
  acceptance_criteria: z.array(z.string().min(1)).min(1),
  verification: z.object({
    required: z.array(z.string().min(1)).min(1),
    smoke: z.array(z.string().min(1)).default([]),
  }),
  risk_level: z.enum(["low", "medium", "high"]),
  dependencies: z.array(z.string().min(1)).default([]),
});

export const dependencyEdgeSchema = z.object({
  from: z.string().min(1),
  to: z.string().min(1),
  type: z.enum([
    "code_dependency",
    "contract_dependency",
    "test_dependency",
    "sequencing_only",
  ]),
  blocks_dispatch: z.boolean(),
  reason: z.string().min(1),
  required_artifacts: z.array(z.string().min(1)).min(1),
});

export const graphDecomposerResultSchema = roleResultSchema.extend({
  children: z.array(graphChildSchema).min(1),
  dependency_edges: z.array(dependencyEdgeSchema).default([]),
});

export const roadmapParentSchema = z.object({
  node_id: z.string().min(1),
  title: z.string().min(1),
  body: z.string().min(1),
  risk_level: z.enum(["low", "medium", "high"]),
  dependencies: z.array(z.string().min(1)).default([]),
});

export const roadmapEdgeSchema = z.object({
  from: z.string().min(1),
  to: z.string().min(1),
  type: dependencyEdgeSchema.shape.type,
  blocks_dispatch: z.boolean(),
  reason: z.string().min(1),
});

export const roadmapDecomposerResultSchema = roleResultSchema.extend({
  parents: z.array(roadmapParentSchema).min(1),
  roadmap_edges: z.array(roadmapEdgeSchema).default([]),
});

export const roleContractManifest = {
  schema_package_version: "0.1.0",
  roles: {
    graph_decomposer: {
      schema_id: "smda.graph-decomposer-result.v1",
      output_tag: "smda_graph_decomposer_result",
    },
    graph_fixer: {
      schema_id: "smda.graph-decomposer-result.v1",
      output_tag: "smda_graph_fixer_result",
    },
    roadmap_decomposer: {
      schema_id: "smda.roadmap-decomposer-result.v1",
      output_tag: "smda_roadmap_decomposer_result",
    },
    child_implementer: {
      schema_id: "smda.child-implementer-result.v1",
      output_tag: "smda_child_implementer_result",
    },
    child_spec_reviewer: {
      schema_id: "smda.review-result.v1",
      output_tag: "smda_child_spec_review_result",
    },
    child_fixer: {
      schema_id: "smda.child-fixer-result.v1",
      output_tag: "smda_child_fixer_result",
    },
    child_quality_reviewer: {
      schema_id: "smda.review-result.v1",
      output_tag: "smda_child_quality_review_result",
    },
    parent_qa_reviewer: {
      schema_id: "smda.review-result.v1",
      output_tag: "smda_parent_qa_review_result",
    },
    parent_integration_conflict_resolver: {
      schema_id: "smda.review-result.v1",
      output_tag: "smda_parent_integration_conflict_result",
    },
  },
} as const;

export function roleResultSchemaForId(schemaId: string) {
  if (schemaId === roleContractManifest.roles.graph_decomposer.schema_id) {
    return graphDecomposerResultSchema;
  }
  if (schemaId === roleContractManifest.roles.roadmap_decomposer.schema_id) {
    return roadmapDecomposerResultSchema;
  }
  const supportedSchemaIds: Set<string> = new Set(
    Object.values(roleContractManifest.roles).map((role) => role.schema_id),
  );
  if (!supportedSchemaIds.has(schemaId)) {
    throw new Error(`Unknown SMDA role schema id: ${schemaId}`);
  }
  return roleResultSchema;
}
