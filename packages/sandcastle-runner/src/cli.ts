import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { runRoleAttempt, type RoleAttemptResult } from "./runRoleAttempt.ts";

type Runner = (request: unknown) => Promise<RoleAttemptResult>;

export type CliResult = {
  exitCode: number;
  stdout: string;
  stderr: string;
};

export async function runCli(
  input: string,
  runner: Runner = runRoleAttempt,
): Promise<CliResult> {
  let request: unknown;
  try {
    request = JSON.parse(input);
  } catch {
    return {
      exitCode: 1,
      stdout: "",
      stderr: JSON.stringify({
        status: "agent_protocol_failed",
        error_message: "Invalid JSON IPC request",
      }),
    };
  }

  try {
    const result = await runner(request);
    return {
      exitCode: result.status === "succeeded" ? 0 : 1,
      stdout: JSON.stringify(result),
      stderr: "",
    };
  } catch (error) {
    return {
      exitCode: 1,
      stdout: "",
      stderr: JSON.stringify({
        status: "agent_protocol_failed",
        error_message: error instanceof Error ? error.message : String(error),
      }),
    };
  }
}

async function main() {
  const input = readFileSync(0, "utf-8");
  const result = await runCli(input);
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
