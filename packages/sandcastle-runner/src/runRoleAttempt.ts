import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { Output, codex, claudeCode, run } from "@ai-hero/sandcastle";
import { noSandbox } from "@ai-hero/sandcastle/sandboxes/no-sandbox";
import { z } from "zod";

import {
  graphDecomposerResultSchema,
  roadmapDecomposerResultSchema,
  roleContractManifest,
  roleResultSchema,
  roleResultSchemaForId,
} from "./roleContracts.ts";

export {
  graphDecomposerResultSchema,
  roadmapDecomposerResultSchema,
  roleResultSchema,
} from "./roleContracts.ts";

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
    agent: z.discriminatedUnion("provider", [
      z.object({
        provider: z.literal("codex"),
        model: z.string().min(1),
        effort: z.enum(["low", "medium", "high", "xhigh"]).optional(),
      }),
      z.object({
        provider: z.literal("claudeCode"),
        model: z.string().min(1),
        effort: z
          .enum(["low", "medium", "high", "xhigh", "max"])
          .optional(),
      }),
    ]),
  })
  .refine((value) => Boolean(value.prompt) !== Boolean(value.prompt_file), {
    message: "Provide exactly one of prompt or prompt_file",
    path: ["prompt"],
  });

export type RoleAttemptRequest = z.infer<typeof roleAttemptRequestSchema>;
export type RoleResult =
  | z.infer<typeof roleResultSchema>
  | z.infer<typeof graphDecomposerResultSchema>
  | z.infer<typeof roadmapDecomposerResultSchema>;

export type RoleAttemptResult =
  | {
      status: "succeeded";
      attempt_id: string;
      schema_id: string;
      schema_package_version: string;
      result: RoleResult;
      commits: { sha: string }[];
      branch: string;
      log_file_path?: string;
    }
  | {
      status: "structured_output_failed";
      attempt_id: string;
      schema_id?: string;
      schema_package_version: string;
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
      schema_id?: string;
      schema_package_version: string;
      error_message: string;
    }
  | {
      status: "agent_protocol_failed";
      attempt_id: string;
      schema_id?: string;
      schema_package_version: string;
      error_message: string;
    };

type SandcastleDeps = {
  run: (options: Record<string, unknown>) => Promise<Record<string, unknown>>;
  outputObject: (options: { tag: string; schema: z.ZodTypeAny }) => unknown;
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
      const options =
        request.agent.effort === undefined
          ? undefined
          : { effort: request.agent.effort };
      return codex(request.agent.model, options);
    }
    return claudeCode(
      request.agent.model,
      request.agent.effort === undefined
        ? undefined
        : { effort: request.agent.effort },
    );
  },
};

export async function runRoleAttempt(
  rawRequest: unknown,
  deps: SandcastleDeps = defaultDeps,
): Promise<RoleAttemptResult> {
  try {
    const request = roleAttemptRequestSchema.parse(rawRequest);
    const resultSchema = roleResultSchemaForId(request.schema_id);
    const promptOptions = request.prompt
      ? { prompt: request.prompt }
      : { promptFile: request.prompt_file };
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
        schema: resultSchema,
      }),
    });
    const branch = stringValue(result.branch, request.branch);
    const commits = commitList(result.commits);

    return {
      status: "succeeded",
      attempt_id: request.attempt_id,
      schema_id: request.schema_id,
      schema_package_version: roleContractManifest.schema_package_version,
      result: resultSchema.parse(result.output),
      commits:
        commits.length > 0
          ? commits
          : publishDirtyWorktreeCommit({
              cwd: request.cwd,
              branch,
              attemptId: request.attempt_id,
              role: request.role,
              phase: request.phase,
            }),
      branch,
      log_file_path: optionalString(result.logFilePath),
    };
  } catch (error) {
    const attemptId =
      typeof rawRequest === "object" &&
      rawRequest !== null &&
      "attempt_id" in rawRequest &&
      typeof rawRequest.attempt_id === "string"
        ? rawRequest.attempt_id
        : "unknown";
    const schemaId =
      typeof rawRequest === "object" &&
      rawRequest !== null &&
      "schema_id" in rawRequest &&
      typeof rawRequest.schema_id === "string"
        ? rawRequest.schema_id
        : undefined;

    if (isStructuredOutputError(error)) {
      return {
        status: "structured_output_failed",
        attempt_id: attemptId,
        schema_id: schemaId,
        schema_package_version: roleContractManifest.schema_package_version,
        error_message: error.message,
        raw_matched: optionalString(error.rawMatched),
        branch: optionalString(error.branch),
        preserved_worktree_path: optionalString(error.preservedWorktreePath),
        session_id: optionalString(error.sessionId),
        session_file_path: optionalString(error.sessionFilePath),
      };
    }

    if (isProtocolError(error)) {
      return {
        status: "agent_protocol_failed",
        attempt_id: attemptId,
        schema_id: schemaId,
        schema_package_version: roleContractManifest.schema_package_version,
        error_message: error.message,
      };
    }

    return {
      status: "execution_failed",
      attempt_id: attemptId,
      schema_id: schemaId,
      schema_package_version: roleContractManifest.schema_package_version,
      error_message: error instanceof Error ? error.message : String(error),
    };
  }
}

function isProtocolError(error: unknown): error is Error {
  return (
    error instanceof z.ZodError ||
    (error instanceof Error &&
      error.message.startsWith("Unknown SMDA role schema id:"))
  );
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

function publishDirtyWorktreeCommit(options: {
  cwd: string;
  branch: string;
  attemptId: string;
  role: string;
  phase: string;
}): { sha: string }[] {
  const worktree = branchWorktreePath(options.cwd, options.branch);
  if (worktree === undefined || !hasWorktreeChanges(worktree)) {
    return [];
  }

  git(worktree, ["add", "-A"]);
  if (!hasWorktreeChanges(worktree)) {
    return [];
  }
  git(worktree, [
    "-c",
    "user.name=SMDA Scheduler",
    "-c",
    "user.email=smda-scheduler@local.invalid",
    "commit",
    "-m",
    `SMDA ${options.attemptId}: ${options.role} ${options.phase}`,
  ]);
  return [{ sha: git(worktree, ["rev-parse", "HEAD"]) }];
}

function branchWorktreePath(cwd: string, branch: string): string | undefined {
  const fromWorktreeList = branchWorktreeFromList(cwd, branch);
  if (fromWorktreeList !== undefined) {
    return fromWorktreeList;
  }

  const currentBranch = safeGit(cwd, ["branch", "--show-current"]);
  if (currentBranch === branch) {
    return cwd;
  }
  return undefined;
}

function branchWorktreeFromList(cwd: string, branch: string): string | undefined {
  const output = safeGit(cwd, ["worktree", "list", "--porcelain"]);
  if (output === undefined) {
    return undefined;
  }

  let currentPath: string | undefined;
  for (const line of output.split("\n")) {
    if (line.startsWith("worktree ")) {
      currentPath = line.slice("worktree ".length);
      continue;
    }
    if (
      line === `branch refs/heads/${branch}` &&
      currentPath !== undefined &&
      existsSync(currentPath)
    ) {
      return currentPath;
    }
  }
  return undefined;
}

function hasWorktreeChanges(cwd: string): boolean {
  return git(cwd, ["status", "--porcelain", "--untracked-files=all"]).length > 0;
}

function safeGit(cwd: string, args: string[]): string | undefined {
  try {
    return git(cwd, args);
  } catch {
    return undefined;
  }
}

function git(cwd: string, args: string[]): string {
  return execFileSync("git", args, {
    cwd,
    encoding: "utf8",
    env: {
      ...process.env,
      GIT_AUTHOR_NAME: "SMDA Scheduler",
      GIT_AUTHOR_EMAIL: "smda-scheduler@local.invalid",
      GIT_COMMITTER_NAME: "SMDA Scheduler",
      GIT_COMMITTER_EMAIL: "smda-scheduler@local.invalid",
    },
  }).trim();
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}
