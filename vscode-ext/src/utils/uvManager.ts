import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

/**
 * Centralised helper for all `uv`-related operations used by generators and
 * evaluators throughout the extension.
 *
 * Public API
 * ──────────
 * UvManager.ensureInstalled(output)
 *   Verify that `uv` is on PATH.  If it is not, download and run the official
 *   installer script, then extend `process.env.PATH` so subsequent execs find it.
 *
 * UvManager.sync(cwd, output, skipIfVenvExists?)
 *   Run `uv sync --directory <cwd>` to install a pyproject.toml-based project
 *   into `.venv`.  When `skipIfVenvExists` is true (the default) the call is a
 *   no-op when `.venv` already exists, saving time on repeated runs.
 *
 * UvManager.setupVenvAndInstall(cwd, output)
 *   Create `.venv` with `uv venv` (skipped when it already exists), then run
 *   `uv pip install -e .` to perform an editable install.  Suitable for the
 *   generators that ship their own `setup.py` / `pyproject.toml`.
 */
export class UvManager {

	// -----------------------------------------------------------------------
	// Public methods
	// -----------------------------------------------------------------------

	/**
	 * Ensure `uv` is available on PATH.
	 * Installs it via the official astral.sh installer if it is missing.
	 * Throws on failure.
	 */
	static async ensureInstalled(output: vscode.OutputChannel): Promise<void> {
		if (await UvManager.isUvOnPath()) {
			const version = await UvManager.getVersion();
			output.appendLine(`✓ uv ${version} is available`);
			return;
		}

		output.appendLine('⚠ uv not found – installing via the official installer…');

		try {
			const { stdout, stderr } = await execAsync(
				'curl -LsSf https://astral.sh/uv/install.sh | sh',
				{ shell: '/bin/bash' }
			);
			if (stdout) output.appendLine(stdout.trimEnd());
			if (stderr) output.appendLine(stderr.trimEnd());

			// Make the newly installed binary available to this Node process.
			const localBin = path.join(process.env.HOME ?? '~', '.local', 'bin');
			if (!process.env.PATH?.includes(localBin)) {
				process.env.PATH = `${localBin}:${process.env.PATH}`;
			}
		} catch (error) {
			throw new Error(
				`Failed to install uv automatically.\n` +
				`Please install it manually: https://docs.astral.sh/uv/getting-started/installation/\n` +
				`Error: ${error instanceof Error ? error.message : String(error)}`
			);
		}

		// Verify the install succeeded.
		if (!(await UvManager.isUvOnPath())) {
			throw new Error(
				'uv installer ran but the binary could not be found on PATH.\n' +
				'Please install uv manually and restart VS Code: https://docs.astral.sh/uv/getting-started/installation/'
			);
		}

		const version = await UvManager.getVersion();
		output.appendLine(`✓ uv ${version} installed successfully`);
	}

	/**
	 * Run `uv sync --directory <cwd>`.
	 *
	 * @param cwd                Directory containing `pyproject.toml`.
	 * @param output             Output channel for log messages.
	 * @param skipIfVenvExists   When `true` (default) skip the sync when a
	 *                           `.venv` already exists to avoid redundant work.
	 */
	static async sync(
		cwd: string,
		output: vscode.OutputChannel,
		skipIfVenvExists = true
	): Promise<void> {
		const venvPath = path.join(cwd, '.venv');

		if (skipIfVenvExists && fs.existsSync(venvPath)) {
			output.appendLine('ℹ  Virtual environment already exists – skipping uv sync.');
			return;
		}

		output.appendLine(`Running: uv sync --directory "${cwd}" …`);

		try {
			const { stdout, stderr } = await execAsync(
				`uv sync --directory "${cwd}"`,
				{ cwd, shell: '/bin/bash' }
			);
			if (stdout) output.appendLine(stdout.trimEnd());
			if (stderr) output.appendLine(stderr.trimEnd());
			output.appendLine('✓ uv sync completed');
		} catch (error) {
			throw new Error(
				`uv sync failed in ${cwd}: ${error instanceof Error ? error.message : String(error)}`
			);
		}
	}

	/**
	 * Create a `.venv` with `uv venv` (skipped when it already exists), then
	 * install the project in editable mode with `uv pip install -e .`.
	 *
	 * This is the pattern used by the generators that have their own
	 * `setup.py` / `pyproject.toml` and activate the environment manually.
	 *
	 * @param cwd    Directory containing `setup.py` or `pyproject.toml`.
	 * @param output Output channel for log messages.
	 */
	static async setupVenvAndInstall(
		cwd: string,
		output: vscode.OutputChannel
	): Promise<void> {
		const venvPath = path.join(cwd, '.venv');

		// ── Create venv ────────────────────────────────────────────────────
		if (!fs.existsSync(venvPath)) {
			output.appendLine('Creating Python virtual environment (uv venv)…');
			try {
				const { stdout, stderr } = await execAsync('uv venv', { cwd });
				if (stdout) output.appendLine(stdout.trimEnd());
				if (stderr) output.appendLine(stderr.trimEnd());
				output.appendLine('✓ Virtual environment created');
			} catch (error) {
				throw new Error(
					`uv venv failed in ${cwd}: ${error instanceof Error ? error.message : String(error)}`
				);
			}
		} else {
			output.appendLine('ℹ  Virtual environment already exists');
		}

		// ── Install dependencies ────────────────────────────────────────────
		output.appendLine('Installing dependencies (uv pip install -e .)…');
		try {
			const { stdout, stderr } = await execAsync(
				'source .venv/bin/activate && uv pip install -e .',
				{ cwd, shell: '/bin/bash' }
			);
			if (stdout) output.appendLine(stdout.trimEnd());
			if (stderr) output.appendLine(stderr.trimEnd());
			output.appendLine('✓ Dependencies installed');
		} catch (error) {
			throw new Error(
				`uv pip install failed in ${cwd}: ${error instanceof Error ? error.message : String(error)}`
			);
		}
	}

	// -----------------------------------------------------------------------
	// Private helpers
	// -----------------------------------------------------------------------

	private static async isUvOnPath(): Promise<boolean> {
		try {
			await execAsync('uv --version');
			return true;
		} catch {
			return false;
		}
	}

	private static async getVersion(): Promise<string> {
		try {
			const { stdout } = await execAsync('uv --version');
			return stdout.trim();
		} catch {
			return '(unknown)';
		}
	}
}
