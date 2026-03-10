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

export class DspyMemoryService {
	private adkPythonPath: string;
	private venvPath: string;
	private dspyMemoryBin: string;
	private isSetup: boolean = false;
	private outputChannel: vscode.OutputChannel;

	constructor(workspaceFolder: vscode.WorkspaceFolder, outputChannel: vscode.OutputChannel) {
		this.adkPythonPath = path.join(workspaceFolder.uri.fsPath, '.tmp_repos', '.adk-python-repo');
		this.venvPath = path.join(this.adkPythonPath, '.venv');
		this.dspyMemoryBin = path.join(this.venvPath, 'bin', 'dspy-memory');
		this.outputChannel = outputChannel;
	}

	/**
	 * Setup the ADK Python repository and DSPy-Memory environment
	 */
	async setup(): Promise<void> {
		if (this.isSetup) {
			return;
		}

		try {
			this.outputChannel.appendLine('=== Setting up DSPy-Memory ===');

			// Step 1: Clone ADK Python repository if not exists
			fs.mkdirSync(path.dirname(this.adkPythonPath), { recursive: true });
			if (!fs.existsSync(this.adkPythonPath)) {
				this.outputChannel.appendLine('Cloning ADK Python repository...');
				await execAsync(
					`git clone --recurse-submodules https://github.com/fenghaitao/adk-python.git ${this.adkPythonPath}`
				);
				this.outputChannel.appendLine('✓ Repository cloned');
			} else {
				this.outputChannel.appendLine('✓ ADK Python repository already exists');
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
				await execAsync(
					'git submodule update --init --recursive --force',
					{ cwd: this.adkPythonPath }
				);
				this.outputChannel.appendLine('✓ Submodules updated');
			}

			// Step 2: Create virtual environment
			if (!fs.existsSync(this.venvPath)) {
				this.outputChannel.appendLine('Creating Python virtual environment...');
				await execAsync('uv venv', { cwd: this.adkPythonPath });
				this.outputChannel.appendLine('✓ Virtual environment created');
			} else {
				this.outputChannel.appendLine('✓ Virtual environment already exists');
			}

			// Step 3: Install DSPy-OpenSpec
			this.outputChannel.appendLine('Installing DSPy-OpenSpec...');
			await execAsync(
				`source ${path.join(this.venvPath, 'bin', 'activate')} && uv pip install ./dspy-openspec/`,
				{ cwd: this.adkPythonPath, shell: '/bin/bash' }
			);
			this.outputChannel.appendLine('✓ DSPy-OpenSpec installed');

			// Step 3.5: Create symlink workaround for contributing directory
			this.outputChannel.appendLine('Creating symlink for contributing directory...');
			const pythonLibPath = path.join(this.venvPath, 'lib', 'python3.12');
			const symlinkTarget = '../../../contributing';
			const symlinkPath = path.join(pythonLibPath, 'contributing');
			
			// Check if symlink already exists
			if (!fs.existsSync(symlinkPath)) {
				await execAsync(
					`ln -sf ${symlinkTarget} contributing`,
					{ cwd: pythonLibPath }
				);
				this.outputChannel.appendLine('✓ Symlink created');
			} else {
				this.outputChannel.appendLine('✓ Symlink already exists');
			}

			// Step 4: Install socksio
			this.outputChannel.appendLine('Installing socksio...');
			await execAsync(
				`source ${path.join(this.venvPath, 'bin', 'activate')} && uv pip install socksio`,
				{ cwd: this.adkPythonPath, shell: '/bin/bash' }
			);
			this.outputChannel.appendLine('✓ socksio installed');

			this.isSetup = true;
			this.outputChannel.appendLine('✓ DSPy-Memory setup completed');
		} catch (error) {
			this.outputChannel.appendLine(`✗ Failed to setup DSPy-Memory: ${error}`);
			throw new Error(`DSPy-Memory setup failed: ${error instanceof Error ? error.message : String(error)}`);
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
			
			const { stdout, stderr } = await execAsync(
				`${this.dspyMemoryBin} index "${documentationPath}"`,
				{ cwd: this.adkPythonPath }
			);

			if (stdout) {
				this.outputChannel.appendLine(stdout);
			}
			if (stderr) {
				this.outputChannel.appendLine(`Warnings: ${stderr}`);
			}

			this.outputChannel.appendLine('✓ Indexing completed');
		} catch (error) {
			this.outputChannel.appendLine(`✗ Failed to index documentation: ${error}`);
			throw new Error(`Failed to index documentation: ${error instanceof Error ? error.message : String(error)}`);
		}
	}

	/**
	 * Search indexed documentation
	 */
	async search(query: string, topK: number = 5): Promise<SearchResult[]> {
		try {
			const command = `${this.dspyMemoryBin} search "${query}" --k ${topK}`;
			
			const { stdout } = await execAsync(command, { cwd: this.adkPythonPath });

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
	 * Parse search results from dspy-memory output
	 */
	private parseSearchResults(output: string): SearchResult[] {
		try {
			// Try to parse as JSON first
			const jsonOutput = JSON.parse(output);
			
			if (Array.isArray(jsonOutput)) {
				return jsonOutput.map((item: any) => ({
					filePath: item.file || item.path || item.filePath || 'Unknown',
					snippet: item.snippet || item.text || item.content || '',
					score: item.score || item.relevance
				}));
			}
		} catch (e) {
			// Parse the text format: "--- Passage N ---" sections
			const results: SearchResult[] = [];
			
			// Split by passage markers
			const passageRegex = /--- Passage \d+ ---\n([\s\S]*?)(?=\n--- Passage \d+ ---|$)/g;
			let match;
			
			while ((match = passageRegex.exec(output)) !== null) {
				const passageContent = match[1].trim();
				
				// Extract the file name from the markdown heading (e.g., "# High-Level_Architecture.md")
				const fileMatch = passageContent.match(/^#\s+(.+\.md)/m);
				const filePath = fileMatch ? fileMatch[1] : 'Unknown';
				
				// The snippet is everything in the passage
				const snippet = passageContent;
				
				results.push({
					filePath,
					snippet,
					score: undefined
				});
			}
			
			return results;
		}
		
		return [];
	}

	/**
	 * Check if DSPy-Memory is setup and ready to use
	 * This checks for actual file existence rather than instance state,
	 * since setup might have been done by a different instance.
	 */
	isReady(): boolean {
		// Check if all required components exist
		const hasRepo = fs.existsSync(this.adkPythonPath);
		const hasVenv = fs.existsSync(this.venvPath);
		const hasBinary = fs.existsSync(this.dspyMemoryBin);
		
		return hasRepo && hasVenv && hasBinary;
	}
}
