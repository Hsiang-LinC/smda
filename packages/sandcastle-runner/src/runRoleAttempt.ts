import { Output, codex, claudeCode, run } from "@ai-hero/sandcastle";
import { noSandbox } from "@ai-hero/sandcastle/sandboxes/no-sandbox";
import { z } from "zod";

export const roleResultSchema = z.object({
  verdict: z.string(),
  required_next_action: z.string(),
  report: z.string().optional(),
});

export const roleAttemptRequestSchema = z
  .object({
    attempt_id: z.string().min(1),
    role: z.string().min(1),
    phase: z.string().min(1),
    branch: z.string().min(1),
    cwd: z.string().min(1),
    context_packet: z.record(z.string(), z.unknown()),
    prompt: z.string().min(1).optional(),
    prompt_file: z.string().min(1).optional(),
    output_tag: z.string().min(1),
    schema_id: z.string().min(1),
    sandbox_provider: z.literal("noSandbox"),
    agent: z.object({
      provider: z.enum(["codex", "claudeCode"]),
      model: z.string().min(1),
    }),
  })
  .refine((value) => Boolean(value.prompt) !== Boolean(value.prompt_file), {
    message: "Provide exactly one of prompt or prompt_file",
    path: ["prompt"],
  });

export type RoleAttemptRequest = z.infer<typeof roleAttemptRequestSchema>;
export type RoleResult = z.infer<typeof roleResultSchema>;

export type RoleAttemptResult =
  | {
      status: "succeeded";
      attempt_id: string;
      result: RoleResult;
      commits: { sha: string }[];
      branch: string;
      log_file_path?: string;
    }
  | {
      status: "structured_output_failed";
      attempt_id: string;
      error_message: string;
      raw_matched?: string;
      branch?: string;
      preserved_worktree_path?: string;
      session_id?: string;
      session_file_path?: string;
    }
  | {
      status: "execution_failed";
      attempt_id: string;
      error_message: string;
    };

type SandcastleDeps = {
  run: (options: Record<string, unknown>) => Promise<Record<string, unknown>>;
  outputObject: (options: { tag: string; schema: typeof roleResultSchema }) => unknown;
  sandboxProvider: () => unknown;
  agentProvider: (request: RoleAttemptRequest) => unknown;
};

const defaultDeps: SandcastleDeps = {
  run: (options) =>
    run(options as never) as unknown as Promise<Record<string, unknown>>,
  outputObject: (options) => Output.object(options),
  sandboxProvider: () => noSandbox(),
  agentProvider: (request) => {
    if (request.agent.provider === "codex") {
      return codex(request.agent.model);
    }
    return claudeCode(request.agent.model);
  },
};

export async function runRoleAttempt(
  rawRequest: unknown,
  deps: SandcastleDeps = defaultDeps,
): Promise<RoleAttemptResult> {
  const request = roleAttemptRequestSchema.parse(rawRequest);
  const promptOptions = request.prompt
    ? { prompt: request.prompt }
    : { promptFile: request.prompt_file };

  try {
    const result = await deps.run({
      agent: deps.agentProvider(request),
      sandbox: deps.sandboxProvider(),
      cwd: request.cwd,
      branchStrategy: { type: "branch", branch: request.branch },
      ...promptOptions,
      maxIterations: 1,
      name: `${request.attempt_id}:${request.role}`,
      output: deps.outputObject({
        tag: request.output_tag,
        schema: roleResultSchema,
      }),
    });

    return {
      status: "succeeded",
      attempt_id: request.attempt_id,
      result: roleResultSchema.parse(result.output),
      commits: commitList(result.commits),
      branch: stringValue(result.branch, request.branch),
      log_file_path: optionalString(result.logFilePath),
    };
  } catch (error) {
    if (isStructuredOutputError(error)) {
      return {
        status: "structured_output_failed",
        attempt_id: request.attempt_id,
        error_message: error.message,
        raw_matched: optionalString(error.rawMatched),
        branch: optionalString(error.branch),
        preserved_worktree_path: optionalString(error.preservedWorktreePath),
        session_id: optionalString(error.sessionId),
        session_file_path: optionalString(error.sessionFilePath),
      };
    }

    return {
      status: "execution_failed",
      attempt_id: request.attempt_id,
      error_message: error instanceof Error ? error.message : String(error),
    };
  }
}

function isStructuredOutputError(error: unknown): error is Error & {
  rawMatched?: unknown;
  branch?: unknown;
  preservedWorktreePath?: unknown;
  sessionId?: unknown;
  sessionFilePath?: unknown;
} {
  return error instanceof Error && error.name === "StructuredOutputError";
}

function commitList(value: unknown): { sha: string }[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((commit) => {
    if (
      typeof commit === "object" &&
      commit !== null &&
      "sha" in commit &&
      typeof commit.sha === "string"
    ) {
      return [{ sha: commit.sha }];
    }
    return [];
  });
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}
