/**
 * cliManager.ts
 *
 * Wrapper for invoking potpie_cli.py as a subprocess from the VS Code
 * extension.  All CLI commands are run using the virtual-environment Python
 * located inside the cloned Potpie repo directory.
 */
import * as cp from 'child_process';
import * as path from 'path';

// ── Types ──────────────────────────────────────────────────────────────────────

export interface ProjectEntry {
  id: string;
  repo_name: string;
  branch_name: string;
  status: string;
  repo_path: string;
}

// ── Logger ─────────────────────────────────────────────────────────────────────

let _log: (msg: string) => void = (msg) => console.log(msg);

export function setLogger(logger: (msg: string) => void): void {
  _log = logger;
}

// ── Paths ──────────────────────────────────────────────────────────────────────

function pythonPath(repoDir: string): string {
  return path.join(repoDir, '.venv', 'bin', 'python');
}

function cliScriptPath(repoDir: string): string {
  return path.join(repoDir, 'potpie_cli.py');
}

// ── Core executor ──────────────────────────────────────────────────────────────

/**
 * Spawn potpie_cli.py with the given arguments.
 * Resolves with stdout on success; rejects with a descriptive error on
 * non-zero exit or spawn failure.
 *
 * @param cwd   Working directory for the subprocess. Defaults to repoDir.
 *              Override this to control where relative paths (like .repowiki/)
 *              are created by the CLI.
 * @param streamStdout  When true, stdout lines are forwarded to the logger.
 */
function runCli(
  repoDir: string,
  args: string[],
  streamStdout = false,
  cwd?: string,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const python = pythonPath(repoDir);
    const cli = cliScriptPath(repoDir);

    const quoted = (s: string) => /\s/.test(s) ? `"${s.replace(/"/g, '\\"')}"` : s;
    _log(`[Potpie] Running: ${python} ${cli} ${args.map(quoted).join(' ')}`);

    const proc = cp.spawn(python, [cli, ...args], { cwd: cwd ?? repoDir });

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (chunk: Buffer) => {
      const text = chunk.toString();
      stdout += text;
      if (streamStdout) {
        text.trimEnd().split('\n').forEach((line) => {
          if (line.trim()) { _log(`[Potpie] ${line}`); }
        });
      }
    });
    proc.stderr.on('data', (chunk: Buffer) => {
      const text = chunk.toString().trim();
      if (text) {
        _log(`[Potpie] ${text}`);
        stderr += text + '\n';
      }
    });

    proc.on('error', (err) => reject(err));
    proc.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(stderr.trim() || `CLI exited with code ${code}`));
      } else {
        resolve(stdout);
      }
    });
  });
}

// ── Public API ─────────────────────────────────────────────────────────────────

/**
 * Detect the active git branch of a local repository.
 * Returns the branch name, or undefined if detection fails.
 */
export function detectBranch(repoPath: string): string | undefined {
  try {
    const result = cp.spawnSync('git', ['rev-parse', '--abbrev-ref', 'HEAD'], {
      cwd: repoPath,
      encoding: 'utf8',
    });
    const branch = result.stdout?.trim();
    return branch && branch !== 'HEAD' ? branch : undefined;
  } catch {
    return undefined;
  }
}

/**
 * List all registered projects.
 *
 * Calls: `potpie_cli.py projects list --json`
 *
 * Returns an array of ProjectEntry objects (may be empty).
 */
export async function listProjects(repoDir: string): Promise<ProjectEntry[]> {
  const output = await runCli(repoDir, ['projects', 'list', '--json']);
  try {
    return JSON.parse(output.trim()) as ProjectEntry[];
  } catch {
    _log(`[Potpie] Warning: could not parse projects list output: ${output}`);
    return [];
  }
}

/**
 * Remove a project and its associated knowledge-graph data.
 *
 * Calls: `potpie_cli.py projects remove <project_id> --force`
 *
 * Note: project_id is passed as a positional argument (not -p).
 */
export async function removeProject(
  repoDir: string,
  projectId: string,
): Promise<void> {
  _log(`[Potpie] Removing project: ${projectId}`);
  await runCli(repoDir, ['projects', 'remove', projectId, '--force']);
}

/**
 * Parse a local repository and build its knowledge graph.
 *
 * Calls: `potpie_cli.py parse repo <repoPath> --branch <branch> [--force]`
 *
 * The branch is always passed explicitly: if not supplied, it is auto-detected
 * from the repo directory (git rev-parse) with 'main' as the final fallback.
 * This ensures the DB never stores an empty branch_name.
 *
 * This is a long-running operation; stdout/stderr are forwarded to the logger
 * in real time so progress is visible in the Output channel.
 */
export async function parseRepo(
  repoDir: string,
  repoPath: string,
  branch?: string,
  force = false,
): Promise<void> {
  // Always resolve to a concrete branch name before calling the CLI.
  const resolvedBranch = branch || detectBranch(repoPath) || 'main';
  const args = ['parse', 'repo', repoPath, '--branch', resolvedBranch];
  if (force) {
    args.push('--force');
  }
  await runCli(repoDir, args, /* streamStdout */ true);
}

/**
 * Ask a one-shot question via `potpie_cli.py ask`.
 *
 * The prompt (which may include prepended conversation history) is passed
 * as a positional argument using `spawn` — no shell escaping needed.
 *
 * Calls:
 *   <python> potpie_cli.py ask "<prompt>" -p <projectId> [-a <agentId>] --no-markdown --json
 *
 * Returns the raw answer string, stripping Rich/ANSI escape codes so the
 * VS Code webview can render plain text.
 */
export async function askQuestion(
  repoDir: string,
  projectId: string,
  prompt: string,
  agentId = 'codebase_qna_agent',
): Promise<string> {
  const args = [
    'ask',
    prompt,
    '-p', projectId,
    '-a', agentId,
    '--json',           // structured output — parse answer field
  ];
  const raw = await runCli(repoDir, args);
  // The potpie CLI writes log lines to stdout before the JSON answer.
  // Find the JSON block: scan for the last top-level '{' that begins a line.
  // eslint-disable-next-line no-control-regex
  const stripped = raw.replace(/\x1b\[[0-9;]*m/g, ''); // strip ANSI
  const jsonIdx = stripped.search(/^\{/m);
  if (jsonIdx >= 0) {
    try {
      const parsed = JSON.parse(stripped.slice(jsonIdx).trim()) as { answer?: string };
      if (parsed.answer) { return parsed.answer; }
    } catch { /* fallthrough */ }
  }
  // Fallback: drop log lines (timestamped) and return remaining text
  return stripped
    .split('\n')
    .filter((l) => !l.match(/^\d{4}-\d{2}-\d{2}.*\| (?:DEBUG|INFO|WARNING|ERROR) \|/))
    .join('\n')
    .trim();
}
