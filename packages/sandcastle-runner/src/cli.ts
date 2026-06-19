import { mkdir, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { runRoleAttempt, type RoleAttemptResult } from "./runRoleAttempt.ts";

type Runner = (request: unknown) => Promise<RoleAttemptResult>;
type CliArtifact =
  | RoleAttemptResult
  | {
      status: "agent_protocol_failed";
      error_message: string;
    };

type CliOptions = {
  resultFilePath?: string;
  runner?: Runner;
};

export type CliResult = {
  exitCode: number;
  stdout: string;
  stderr: string;
};

export async function runCli(
  input: string,
  options: CliOptions = {},
): Promise<CliResult> {
  const runner = options.runner ?? runRoleAttempt;
  if (!options.resultFilePath) {
    return {
      exitCode: 1,
      stdout: "",
      stderr: "Missing required --result-file",
    };
  }

  let request: unknown;
  try {
    request = JSON.parse(input);
  } catch {
    await writeJsonFileAtomically(options.resultFilePath, {
      status: "agent_protocol_failed",
      error_message: "Invalid JSON IPC request",
    });
    return {
      exitCode: 1,
      stdout: "",
      stderr: "",
    };
  }

  try {
    const result = await runner(request);
    await writeJsonFileAtomically(options.resultFilePath, result);
    return {
      exitCode: result.status === "succeeded" ? 0 : 1,
      stdout: "",
      stderr: "",
    };
  } catch (error) {
    await writeJsonFileAtomically(options.resultFilePath, {
      status: "agent_protocol_failed",
      error_message: error instanceof Error ? error.message : String(error),
    });
    return {
      exitCode: 1,
      stdout: "",
      stderr: "",
    };
  }
}

export async function readStream(
  stream: AsyncIterable<Buffer | string>,
): Promise<string> {
  let input = "";
  for await (const chunk of stream) {
    input += typeof chunk === "string" ? chunk : chunk.toString("utf-8");
  }
  return input;
}

async function writeJsonFileAtomically(
  resultFilePath: string,
  artifact: CliArtifact,
): Promise<void> {
  await mkdir(dirname(resultFilePath), { recursive: true });
  const tempPath = `${resultFilePath}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(tempPath, JSON.stringify(artifact), "utf-8");
  await rename(tempPath, resultFilePath);
}

function resultFilePathFromArgs(argv: string[]): string | undefined {
  const index = argv.indexOf("--result-file");
  if (index === -1) {
    return undefined;
  }
  return argv[index + 1];
}

async function main() {
  const input = await readStream(process.stdin);
  const result = await runCli(input, {
    resultFilePath: resultFilePathFromArgs(process.argv.slice(2)),
  });
  if (result.stdout) {
    process.stdout.write(`${result.stdout}\n`);
  }
  if (result.stderr) {
    process.stderr.write(`${result.stderr}\n`);
  }
  process.exitCode = result.exitCode;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  void main();
}
