import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { promisify } from 'util';
import { exec } from 'child_process';

const execAsync = promisify(exec);

interface SearchResult {
	filePath: string;
	snippet: string;
	score?: number;
}

export class ChromadbMemoryService {
	private workspaceFolder: vscode.WorkspaceFolder;
	private adkPythonPath: string;
	private venvPath: string;
	private chromadbAppsDir: string;
	private isSetup: boolean = false;
	private useUv: boolean = false;
	private outputChannel: vscode.OutputChannel;

	constructor(workspaceFolder: vscode.WorkspaceFolder, outputChannel: vscode.OutputChannel) {
		this.workspaceFolder = workspaceFolder;
		this.adkPythonPath = path.join(workspaceFolder.uri.fsPath, '.tmp_repos', '.adk-python-repo');
		this.venvPath = path.join(this.adkPythonPath, '.venv');
		this.chromadbAppsDir = path.join(
			this.adkPythonPath,
			'.kiro',
			'skills',
			'chromadb-apps'
		);
		this.outputChannel = outputChannel;
	}

	/**
	 * Setup ChromaDB environment by cloning adk-python repo
	 */
	async setup(): Promise<void> {
		if (this.isSetup) {
			return;
		}

		try {
			this.outputChannel.appendLine('=== Setting up ChromaDB Memory ===');

			// Step 0: Check Python version
			try {
				const { stdout: pythonVersion } = await execAsync('python3 --version');
				this.outputChannel.appendLine(`Python version: ${pythonVersion.trim()}`);
			} catch {
				this.outputChannel.appendLine('⚠️ Could not determine Python version');
			}

			// Step 1: Check if uv is available, if not try to install it
			let useUv = false;
			try {
				await execAsync('which uv');
				useUv = true;
				this.outputChannel.appendLine('✓ uv is available');
			} catch {
				this.outputChannel.appendLine('⚠️ uv not found, attempting to install...');
				try {
					// Install uv using the official installer
					await execAsync('curl -LsSf https://astral.sh/uv/install.sh | sh', {
						shell: '/bin/bash',
					});
					// Add to PATH for this session
					process.env.PATH = `${process.env.HOME}/.local/bin:${process.env.PATH}`;
					
					// Verify installation
					await execAsync('which uv');
					useUv = true;
					this.outputChannel.appendLine('✓ uv installed successfully');
				} catch (installError) {
					this.outputChannel.appendLine('⚠️ Failed to install uv, falling back to pip');
					this.outputChannel.appendLine(`Error: ${installError}`);
				}
			}
			this.useUv = useUv;

			// Step 2: Clone ADK Python repository if not exists
			fs.mkdirSync(path.dirname(this.adkPythonPath), { recursive: true });
			if (!fs.existsSync(this.adkPythonPath)) {
				this.outputChannel.appendLine('Cloning ADK Python repository...');
				await execAsync(
					`git clone --recurse-submodules https://github.com/fenghaitao/adk-python.git ${this.adkPythonPath}`
				);
				this.outputChannel.appendLine('✓ Repository cloned');
			} else {
				this.outputChannel.appendLine('✓ ADK Python repository already exists');
				// Pull latest changes so new tracked paths (e.g. .kiro/skills) are present
				this.outputChannel.appendLine('Pulling latest changes...');
				try {
					await execAsync('git pull --ff-only', { cwd: this.adkPythonPath });
					this.outputChannel.appendLine('✓ Repository updated');
				} catch {
					this.outputChannel.appendLine('⚠ git pull failed, continuing with existing state');
				}
				// Make sure submodules are initialized
				this.outputChannel.appendLine('Updating submodules...');
				// Remove any stale git lock files that may have been left by a crashed process
				try {
					await execAsync(
						'find .git/modules -name "index.lock" -delete',
						{ cwd: this.adkPythonPath }
					);
				} catch {
					// Ignore errors – the find/delete is best-effort
				}
				await execAsync('git submodule update --init --recursive --force', {
					cwd: this.adkPythonPath,
				});
				this.outputChannel.appendLine('✓ Submodules updated');
			}

			// Step 3: Create virtual environment
			const venvMarkerFile = path.join(this.venvPath, '.venv_method');
			let recreateVenv = false;
			
			if (fs.existsSync(this.venvPath)) {
				if (fs.existsSync(venvMarkerFile)) {
					const existingMethod = fs.readFileSync(venvMarkerFile, 'utf-8').trim();
					const currentMethod = useUv ? 'uv' : 'pip';
					if (existingMethod !== currentMethod) {
						this.outputChannel.appendLine(`⚠️ Recreating venv (was ${existingMethod}, now ${currentMethod})...`);
						await execAsync(`rm -rf ${this.venvPath}`, { cwd: this.adkPythonPath });
						recreateVenv = true;
					}
				}
			}
			
			if (!fs.existsSync(this.venvPath) || recreateVenv) {
				this.outputChannel.appendLine('Creating Python virtual environment...');
				if (useUv) {
					await execAsync('uv venv', { cwd: this.adkPythonPath });
					fs.writeFileSync(venvMarkerFile, 'uv');
				} else {
					await execAsync('python3 -m venv .venv', { cwd: this.adkPythonPath });
					fs.writeFileSync(venvMarkerFile, 'pip');
				}
				this.outputChannel.appendLine('✓ Virtual environment created');
			} else {
				this.outputChannel.appendLine('✓ Virtual environment already exists');
			}

			// Step 4: Install ChromaDB dependencies
			this.outputChannel.appendLine('Installing ChromaDB dependencies...');
			if (useUv) {
				await execAsync(
					`source ${path.join(this.venvPath, 'bin', 'activate')} && uv pip install chromadb pyyaml`,
					{ cwd: this.adkPythonPath, shell: '/bin/bash' }
				);
			} else {
				this.outputChannel.appendLine('Upgrading pip...');
				await execAsync(
					`source ${path.join(this.venvPath, 'bin', 'activate')} && pip install --upgrade pip setuptools wheel`,
					{ cwd: this.adkPythonPath, shell: '/bin/bash' }
				);
				this.outputChannel.appendLine('Installing ChromaDB...');
				await execAsync(
					`source ${path.join(this.venvPath, 'bin', 'activate')} && pip install chromadb pyyaml`,
					{ cwd: this.adkPythonPath, shell: '/bin/bash' }
				);
			}
			this.outputChannel.appendLine('✓ ChromaDB dependencies installed');

			// Verify the chromadb-apps project dir exists before marking setup as complete
			if (!fs.existsSync(this.chromadbAppsDir)) {
				throw new Error(
					`chromadb-apps not found at expected path: ${this.chromadbAppsDir}. ` +
					`Ensure the ADK Python repository is up to date (git pull).`
				);
			}

			this.isSetup = true;
			this.outputChannel.appendLine('✓ ChromaDB Memory setup completed');
		} catch (error) {
			this.outputChannel.appendLine(`✗ Failed to setup ChromaDB Memory: ${error}`);
			throw new Error(
				`ChromaDB Memory setup failed: ${error instanceof Error ? error.message : String(error)}`
			);
		}
	}

	/**
	 * Index a documentation directory
	 */
	async index(documentationPath: string): Promise<void> {
		await this.setup();

		if (!fs.existsSync(documentationPath)) {
			throw new Error(`Documentation path does not exist: ${documentationPath}`);
		}

		try {
			this.outputChannel.appendLine(`Indexing documentation at: ${documentationPath}`);

			// Invoke via the project's entry point: uv run --directory <chromadb-apps> chromadb-memory
			// Falls back to activating the local venv + python if uv is unavailable.
			let command: string;
			if (this.useUv) {
				command = `uv run --directory "${this.chromadbAppsDir}" chromadb-memory index "${documentationPath}"`;
			} else {
				const script = path.join(this.chromadbAppsDir, 'chromadb_apps', 'chromadb_memory.py');
				command = `source ${path.join(this.venvPath, 'bin', 'activate')} && python3 ${script} index "${documentationPath}"`;
			}
			
			const { stdout, stderr } = await execAsync(command, {
				cwd: this.adkPythonPath,
				shell: '/bin/bash'
			});

			if (stdout) {
				this.outputChannel.appendLine(stdout);
			}
			if (stderr) {
				this.outputChannel.appendLine(`Warnings: ${stderr}`);
			}

			this.outputChannel.appendLine('✓ Indexing completed');
		} catch (error) {
			this.outputChannel.appendLine(`✗ Failed to index documentation: ${error}`);
			throw new Error(
				`Failed to index documentation: ${error instanceof Error ? error.message : String(error)}`
			);
		}
	}

	/**
	 * Search indexed documentation
	 */
	async search(query: string, topK: number = 5): Promise<SearchResult[]> {
		try {
			let command: string;
			if (this.useUv) {
				command = `uv run --directory "${this.chromadbAppsDir}" chromadb-memory search "${query}" --k ${topK}`;
			} else {
				const script = path.join(this.chromadbAppsDir, 'chromadb_apps', 'chromadb_memory.py');
				command = `source ${path.join(this.venvPath, 'bin', 'activate')} && python3 ${script} search "${query}" --k ${topK}`;
			}

			const { stdout } = await execAsync(command, {
				cwd: this.adkPythonPath,
				shell: '/bin/bash',
			});

			this.outputChannel.appendLine(stdout);

			// Parse the output to extract results
			const results = this.parseSearchResults(stdout);

			return results;
		} catch (error) {
			// Return empty array instead of throwing to handle gracefully
			return [];
		}
	}

	/**
	 * Parse search results from chromadb_memory output
	 */
	private parseSearchResults(output: string): SearchResult[] {
		const results: SearchResult[] = [];

		try {
			// The chromadb_memory.py outputs results in a specific format
			// Example:
			// === Result 1 ===
			// File: path/to/file.md
			// Score: 0.85
			// ---
			// Snippet content here
			// ===

			const resultRegex = /=== Result \d+ ===\nFile: (.+?)\nScore: (.+?)\n---\n([\s\S]*?)(?=\n===|$)/g;
			let match;

			while ((match = resultRegex.exec(output)) !== null) {
				const filePath = match[1].trim();
				const score = parseFloat(match[2]);
				const snippet = match[3].trim();

				results.push({
					filePath,
					snippet,
					score: isNaN(score) ? undefined : score,
				});
			}

			// If the above regex didn't match, try parsing as plain text passages
			if (results.length === 0) {
				const passageRegex = /--- Passage \d+ ---\n([\s\S]*?)(?=\n--- Passage \d+ ---|$)/g;
				let passageMatch;

				while ((passageMatch = passageRegex.exec(output)) !== null) {
					const passageContent = passageMatch[1].trim();

					// Extract the file name from markdown heading if present
					const fileMatch = passageContent.match(/^#\s+(.+\.md)/m);
					const filePath = fileMatch ? fileMatch[1] : 'Unknown';

					results.push({
						filePath,
						snippet: passageContent,
						score: undefined,
					});
				}
			}

			return results;
		} catch (error) {
			this.outputChannel.appendLine(`Warning: Failed to parse search results: ${error}`);
			return [];
		}
	}

	/**
	 * Check if ChromaDB Memory is setup and ready to use
	 * This checks for actual file existence rather than instance state,
	 * since setup might have been done by a different instance.
	 */
	isReady(): boolean {
		// Check if all required components exist
		const hasRepo = fs.existsSync(this.adkPythonPath);
		const hasVenv = fs.existsSync(this.venvPath);
		const hasScript = fs.existsSync(this.chromadbAppsDir);

		return hasRepo && hasVenv && hasScript;
	}
}
