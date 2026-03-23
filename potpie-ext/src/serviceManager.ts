import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

// ── Script names ──────────────────────────────────────────────────────────────

const STOP_SCRIPT = path.join('singularity', 'stop.sh');
const START_SCRIPT = path.join('singularity', 'start.sh');

/**
 * The repo-root virtual environment whose activate script must be
 * sourced before any singularity service script is run.
 */
const SC_ACTIVATE = path.join('.venv', 'bin', 'activate');

// ── Module-level logger reference ─────────────────────────────────────────────

let _log: (msg: string) => void = (msg) => console.log(msg);

export function setLogger(logger: (msg: string) => void): void {
  _log = logger;
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Stop any running Potpie backend services.
 *
 * Runs `singularity/stop.sh` inside `repoDir`.
 * Safe to call even if services are not running — the script is idempotent.
 */
export async function stopServices(repoDir: string): Promise<void> {
  _log('[Potpie] Stopping existing services…');
  try {
    await runScript(STOP_SCRIPT, repoDir, SC_ACTIVATE);
    _log('[Potpie] Backend services stopped');
  } catch (err) {
    // Non-fatal: services may already be down
    _log(`[Potpie] Warning: stop script exited with error — ${err}`);
  }
}

/**
 * Start the Potpie backend services.
 *
 * Sequence:
 *   1. Call stop.sh to ensure a clean slate.
 *   2. Call start.sh to bring services up.
 */
export async function startServices(repoDir: string): Promise<void> {
  await stopServices(repoDir);

  _log('[Potpie] Starting backend services…');
  try {
    await runScript(START_SCRIPT, repoDir, SC_ACTIVATE);
    _log('[Potpie] Backend services started');
  } catch (err) {
    _log(`[Potpie] Error: failed to start backend services — ${err}`);
    throw err;
  }
}

// ── Utility ────────────────────────────────────────────────────────────────────

/**
 * Execute a shell script relative to `cwd`, piping its output to the logger.
 *
 * @param scriptRelPath  Path to the script, relative to `cwd`.
 * @param cwd            Working directory.
 * @param activateScript Optional path (relative to `cwd`) of a Python venv
 *                       activate script to source before running the script.
 */
function runScript(
  scriptRelPath: string,
  cwd: string,
  activateScript?: string,
): Promise<void> {
  return new Promise((resolve, reject) => {
    // Build the bash command.  When an activate script is supplied, source it
    // first so the virtual environment (and its binaries) are on PATH.
    const cmd = activateScript
      ? `source "${activateScript}" && bash "${scriptRelPath}"`
      : `bash "${scriptRelPath}"`;

    // Ensure the workspace temp dir exists and set SINGULARITY_TMPDIR so that
    // Singularity uses it for host-side image builds.
    // Do NOT override TMPDIR: it is inherited by Singularity containers where
    // the workspace host-path is not mounted, causing mktemp to fail inside
    // containers (e.g. Neo4j startup scripts).
    const workspaceTempDir = path.join(path.dirname(cwd), 'temp');
    if (!fs.existsSync(workspaceTempDir)) {
      fs.mkdirSync(workspaceTempDir, { recursive: true });
    }

    // Build a clean environment: inherit everything except TMPDIR (remove it
    // so containers fall back to /tmp), and set SINGULARITY_TMPDIR explicitly.
    const childEnv: NodeJS.ProcessEnv = { ...process.env };
    delete childEnv['TMPDIR'];
    childEnv['SINGULARITY_TMPDIR'] = workspaceTempDir;

    const child = cp.spawn('bash', ['-c', cmd], {
      cwd,
      shell: false,
      env: childEnv,
    });

    child.stdout.on('data', (chunk: Buffer) =>
      _log(`[Potpie] ${chunk.toString().trim()}`),
    );
    child.stderr.on('data', (chunk: Buffer) =>
      _log(`[Potpie] ${chunk.toString().trim()}`),
    );

    child.on('error', (err) => {
      _log(`[Potpie] Script spawn error (${scriptRelPath}): ${err.message}`);
      reject(err);
    });

    // Use 'exit' (not 'close') so we resolve as soon as the bash script itself
    // exits.  Singularity daemon instances inherit the pipe FDs and keep them
    // open indefinitely; 'close' would never fire because of those daemons,
    // whereas 'exit' fires the moment the script process terminates.
    child.on('exit', (code, signal) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`Script "${scriptRelPath}" exited with code ${code ?? signal}`));
      }
    });
  });
}
