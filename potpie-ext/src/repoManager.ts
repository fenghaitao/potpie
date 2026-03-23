import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

// ── Types ─────────────────────────────────────────────────────────────────────

// ── Constants ─────────────────────────────────────────────────────────────────

const REPOS_DIR = 'repos';

/** Potpie source repository — cloned into the workspace root. */
const POTPIE_REPO_URL = 'https://github.com/intel-sandbox/potpie.git';
const POTPIE_BRANCH  = 'main';
const POTPIE_CLONE_DIR = 'potpie';

// ── Module-level logger reference ─────────────────────────────────────────────

let _log: (msg: string) => void = (msg) => console.log(msg);

export function setLogger(logger: (msg: string) => void): void {
  _log = logger;
}

// ── Clone helpers ─────────────────────────────────────────────────────────────

/**
 * Clone the Potpie source repository into <workspace>/potpie if it is not
 * already present.
 *
 * @returns Absolute path to the cloned directory.
 */
export async function ensurePotpieRepo(
  workspacePath: string,
): Promise<string> {
  const destDir = path.join(workspacePath, POTPIE_CLONE_DIR);

  if (fs.existsSync(path.join(destDir, '.git'))) {
    _log(`[Potpie] Repository already present at: ${destDir}`);
    await preparePotpieRepo(destDir);
    return destDir;
  }

  _log(`[Potpie] Cloning repository from ${POTPIE_REPO_URL} (branch: ${POTPIE_BRANCH}) …`);

  await runCommand(
    'git',
    ['clone', '--recurse-submodules', '--branch', POTPIE_BRANCH, POTPIE_REPO_URL, destDir],
    workspacePath,
  );

  _log('[Potpie] Repository cloned');

  await preparePotpieRepo(destDir);

  return destDir;
}

/**
 * Clone an arbitrary repository into <workspace>/repos/<repoName>.
 *
 * @param repoUrl  Remote URL to clone.
 * @param branch   Branch to check out (default: repository default).
 */
export async function cloneRepo(
  workspacePath: string,
  repoUrl: string,
  branch?: string,
): Promise<string> {
  const repoName = repoUrl.replace(/\.git$/, '').split('/').pop() ?? 'repo';
  const destDir = path.join(workspacePath, REPOS_DIR, repoName);

  if (fs.existsSync(path.join(destDir, '.git'))) {
    _log(`[Potpie] Repository "${repoName}" already cloned at: ${destDir}`);
    return destDir;
  }

  const args = ['clone', '--recurse-submodules'];
  if (branch) {
    args.push('--branch', branch);
  }
  args.push(repoUrl, destDir);

  _log(`[Potpie] Cloning ${repoUrl} …`);
  await runCommand('git', args, workspacePath);
  _log(`[Potpie] Repository cloned: ${repoName}`);

  return destDir;
}

// ── Utility ────────────────────────────────────────────────────────────────────

/**
 * Perform one-time post-clone setup steps inside the Potpie repo directory:
 *  0. Ensure <workspace>/temp exists (used as TMPDIR for Singularity builds).
 *  1. Copy .env.template → .env if .env is absent.
 *  2. Run `uv sync` inside singularity/singularity-compose to create the venv
 *     required by singularity/start.sh and singularity/down.sh.
 *  3. Ensure ~/.singularity exists; if not, create <workspace>/.singularity/
 *     and symlink ~/.singularity → <workspace>/.singularity.
 *  4. Run `uv venv` in the repo root to create the main virtual environment.
 */
async function preparePotpieRepo(repoDir: string): Promise<void> {
  // ── Step 0: workspace temp dir ───────────────────────────────────────────
  const workspaceTempDir = path.join(path.dirname(repoDir), 'temp');
  if (!fs.existsSync(workspaceTempDir)) {
    fs.mkdirSync(workspaceTempDir, { recursive: true });
    _log(`[Potpie] Created workspace temp dir: ${workspaceTempDir}`);
  } else {
    _log('[Potpie] Workspace temp dir already exists — skipping');
  }

  // ── Step 1: .env ──────────────────────────────────────────────────────────
  const envFile = path.join(repoDir, '.env');
  const envTemplate = path.join(repoDir, '.env.template');
  if (!fs.existsSync(envFile)) {
    if (fs.existsSync(envTemplate)) {
      fs.copyFileSync(envTemplate, envFile);
      _log('[Potpie] Copied .env.template → .env (edit it to set API keys and DB settings)');
    } else {
      _log('[Potpie] Warning: .env.template not found — .env was not created');
    }
  } else {
    _log('[Potpie] .env already present — skipping copy');
  }

  // ── Step 2: singularity-compose venv via uv sync ─────────────────────────
  const scDir = path.join(repoDir, 'singularity', 'singularity-compose');
  const scVenv = path.join(scDir, '.venv');
  if (!fs.existsSync(scVenv)) {
    _log('[Potpie] Setting up singularity-compose virtual environment (uv sync)…');
    await ensureUv();
    await runCommand('uv', ['sync', '--directory', scDir], repoDir);
    _log('[Potpie] singularity-compose venv created');
  } else {
    _log('[Potpie] singularity-compose venv already exists — skipping uv sync');
  }

  // ── Step 3: ~/.singularity symlink ────────────────────────────────────────
  let homeDir: string | undefined;
  try {
    homeDir = os.homedir();
  } catch (err) {
    _log('[Potpie] Warning: Unable to determine home directory; skipping ~/.singularity symlink');
  }

  if (homeDir) {
    const homeSingularity = path.join(homeDir, '.singularity');
    if (!fs.existsSync(homeSingularity)) {
      const wsSingularity = path.join(path.dirname(repoDir), '.singularity');
      if (!fs.existsSync(wsSingularity)) {
        fs.mkdirSync(wsSingularity, { recursive: true });
        _log(`[Potpie] Created workspace singularity cache dir: ${wsSingularity}`);
      }
      try {
        fs.symlinkSync(wsSingularity, homeSingularity);
        _log(`[Potpie] Created symlink ${homeSingularity} → ${wsSingularity}`);
      } catch (err: any) {
        const code = (err as NodeJS.ErrnoException).code;
        if (code === 'EEXIST') {
          _log(`[Potpie] ~/.singularity already exists at ${homeSingularity} — skipping symlink`);
        } else if (process.platform === 'win32' && code === 'EPERM') {
          _log(`[Potpie] Warning: Insufficient permissions to create symlink at ${homeSingularity} on Windows — singularity cache may not be shared`);
        } else {
          _log(`[Potpie] Warning: Failed to create symlink ${homeSingularity} → ${wsSingularity}: ${String(err)}`);
        }
      }
    } else {
      _log(`[Potpie] ~/.singularity already exists at ${homeSingularity} — skipping symlink`);
    }
  }

  // ── Step 4: repo-root venv via uv venv ────────────────────────────────────
  const repoVenv = path.join(repoDir, '.venv');
  if (!fs.existsSync(repoVenv)) {
    _log('[Potpie] Creating repo-root virtual environment (uv venv)…');
    await ensureUv();
    await runCommand('uv', ['venv'], repoDir);
    _log('[Potpie] Repo-root venv created');
  } else {
    _log('[Potpie] Repo-root venv already exists — skipping uv venv');
  }
}

/**
 * Ensure the `uv` package manager is available on PATH.
 * If it is not found, installs it via the official astral.sh installer.
 */
async function ensureUv(): Promise<void> {
  try {
    await execAsync('uv --version', { shell: '/bin/bash' });
    return; // already available
  } catch {
    // not on PATH — install it
  }

  _log('[Potpie] uv not found — installing via official installer…');
  try {
    const { stdout, stderr } = await execAsync(
      'curl -LsSf https://astral.sh/uv/install.sh | sh',
      { shell: '/bin/bash' },
    );
    if (stdout) { _log(`[Potpie] ${stdout.trimEnd()}`); }
    if (stderr) { _log(`[Potpie] ${stderr.trimEnd()}`); }
  } catch (err) {
    throw new Error(
      `Failed to install uv automatically. ` +
      `Please install it manually: https://docs.astral.sh/uv/getting-started/installation/ — ${err}`,
    );
  }

  // Extend PATH of this process so subsequent spawns can find the new binary
  const localBin = path.join(process.env.HOME ?? '~', '.local', 'bin');
  if (!process.env.PATH?.includes(localBin)) {
    process.env.PATH = `${localBin}:${process.env.PATH}`;
  }

  try {
    await execAsync('uv --version', { shell: '/bin/bash' });
    _log('[Potpie] uv installed successfully');
  } catch {
    throw new Error(
      'uv installer ran but the binary was not found on PATH. ' +
      'Please install uv manually: https://docs.astral.sh/uv/getting-started/installation/',
    );
  }
}

/**
 * Spawn a child process and resolve/reject based on exit code.
 * stdout/stderr are forwarded to the logger.
 */
function runCommand(
  cmd: string,
  args: string[],
  cwd: string,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = cp.spawn(cmd, args, { cwd, shell: false });

    child.stdout.on('data', (chunk: Buffer) =>
      _log(`[Potpie] ${chunk.toString().trim()}`),
    );
    child.stderr.on('data', (chunk: Buffer) =>
      _log(`[Potpie] ${chunk.toString().trim()}`),
    );

    child.on('error', (err) => {
      _log(`[Potpie] Command error (${cmd}): ${err.message}`);
      reject(err);
    });

    child.on('close', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`Command "${cmd} ${args.join(' ')}" exited with code ${code}`));
      }
    });
  });
}
