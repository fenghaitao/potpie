import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { exec } from 'child_process';
import { execSync } from 'child_process';
import { promisify } from 'util';
import { IWikiGenerator, GenerationProgress } from './IWikiGenerator';
import { WikiType } from '../wikiTypeDetector';
import { createMemoryService, getMemoryBackendName } from '../memoryService';
import { UvManager } from '../utils/uvManager';

const execAsync = promisify(exec);

/**
 * Generator for DeepWiki documentation
 * Uses the deepwiki-open GitHub Copilot-powered documentation generator
 */
export class DeepWikiGenerator implements IWikiGenerator {
	private currentProcess: ReturnType<typeof exec> | undefined;
	private deepwikiPath: string | undefined;
	private outputChannel: vscode.OutputChannel | undefined;

	getWikiType(): WikiType {
		return WikiType.DeepWiki;
	}

	async checkPrerequisites(workspaceRoot: string): Promise<boolean> {
		// Basic prerequisite checks
		return true;
	}

	async generate(
		workspaceRoot: string,
		progress: GenerationProgress,
		cancellationToken: vscode.CancellationToken
	): Promise<void> {
		// Create a single output channel for the entire generation process
		this.outputChannel = vscode.window.createOutputChannel('DeepWiki Generation');
		this.outputChannel!.show();

		let cancelled = false;

		// Handle cancellation
		cancellationToken.onCancellationRequested(() => {
			cancelled = true;
			if (this.currentProcess) {
				this.currentProcess.kill();
			}
		});

		try {
			// Step 1: Get or clone deepwiki-open repository
			progress.report('Setting up DeepWiki generator...');
			this.deepwikiPath = await this.setupDeepWikiRepo(workspaceRoot);
			if (cancelled) {
				throw new Error('Generation cancelled');
			}

			// Step 2: Check and setup GITHUB_TOKEN
			progress.report('Checking GitHub token...');
			await this.setupGitHubToken();
			if (cancelled) {
				throw new Error('Generation cancelled');
			}

			// Step 3: Optionally select sub-directories and resolve README files
			progress.report('Selecting sub-directories...');
			const includeFiles = await this.collectSubdirectories(workspaceRoot);
			if (cancelled) {
				throw new Error('Generation cancelled');
			}

			// Step 4: Setup Node.js with nvm
			progress.report('Setting up Node.js environment...');
			await this.setupNodeEnvironment();
			if (cancelled) {
				throw new Error('Generation cancelled');
			}

			// Step 5: Setup Python virtual environment
			progress.report('Setting up Python environment...');
			await this.setupPythonEnvironment();
			if (cancelled) {
				throw new Error('Generation cancelled');
			}

			// Step 6: Run the generator
			progress.report('Generating DeepWiki documentation...');
			await this.runDeepWikiGenerator(workspaceRoot, includeFiles);
			if (cancelled) {
				throw new Error('Generation cancelled');
			}

			// Step 7: Index documentation
			progress.report('Indexing documentation for search...');
			await this.indexDocumentation(workspaceRoot);
			if (cancelled) {
				throw new Error('Generation cancelled');
			}

			// Success!
			await new Promise(resolve => setTimeout(resolve, 500));
		} catch (error) {
			if (cancelled || (error instanceof Error && error.message === 'Generation cancelled')) {
				throw new Error('Generation cancelled');
			}
			throw error;
		}
	}

	/**
	 * Step 3: Prompt the user to select sub-directories, then find README.md / README.txt
	 * files inside each selection.  Returns the list of absolute README paths.
	 * Cancelling the dialog is treated as "no selection" - generation continues normally.
	 */
	private async collectSubdirectories(workspaceRoot: string): Promise<string[]> {
		if (!this.outputChannel) {
			this.outputChannel = vscode.window.createOutputChannel('DeepWiki Generation');
		}

		this.outputChannel.appendLine('');
		this.outputChannel.appendLine('=== Step 3: Select Sub-directories (optional) ===');

		const uris = await vscode.window.showOpenDialog({
			canSelectFolders: true,
			canSelectFiles: false,
			canSelectMany: true,
			defaultUri: vscode.Uri.file(workspaceRoot),
			openLabel: 'Include',
			title: 'Select sub-directories to include (Cancel to skip)',
		});

		if (!uris || uris.length === 0) {
			this.outputChannel.appendLine('  No sub-directories selected — skipping.');
			return [];
		}

		const selectedDirs = uris.map(u => u.fsPath);
		this.outputChannel.appendLine(`  Selected directories: ${selectedDirs.join(', ')}`);

		// Search for README files directly inside each chosen directory
		const readmeFiles: string[] = [];
		for (const dir of selectedDirs) {
			for (const name of ['README.md', 'README.txt']) {
				const candidate = path.join(dir, name);
				if (fs.existsSync(candidate)) {
					readmeFiles.push(candidate);
					this.outputChannel.appendLine(`  Found README: ${candidate}`);
				}
			}
		}

		if (readmeFiles.length === 0) {
			this.outputChannel.appendLine('  No README files found in selected directories.');
		} else {
			this.outputChannel.appendLine(`  ${readmeFiles.length} README file(s) will be passed via --include-files.`);
		}

		return readmeFiles;
	}

	/**
	 * Step 1: Get or clone deepwiki-open repository
	 */
	private async setupDeepWikiRepo(workspaceRoot: string): Promise<string> {
		// Ask user for deepwiki-open path
		const selectedPath = await vscode.window.showInputBox({
			prompt: 'Enter the path to deepwiki-open repository (leave empty to clone automatically)',
			placeHolder: '/path/to/deepwiki-open',
			ignoreFocusOut: true,
			validateInput: (value) => {
				if (value && !path.isAbsolute(value)) {
					return 'Please enter an absolute path';
				}
				return null;
			}
		});

		if (selectedPath && fs.existsSync(selectedPath)) {
			// Use provided path
			return selectedPath;
		}

		// Clone deepwiki-open to workspace (using .tmp_repos/.deepwiki-repo to avoid conflicts)
		const deepwikiPath = path.join(workspaceRoot, '.tmp_repos', '.deepwiki-repo');
		
		if (fs.existsSync(deepwikiPath)) {
			// Already exists, use it
			const useExisting = await vscode.window.showQuickPick(['Yes', 'No'], {
				title: '.tmp_repos/.deepwiki-repo directory already exists. Use it?',
				placeHolder: 'Select an option'
			});

			if (useExisting === 'Yes') {
				return deepwikiPath;
			}
		}

		// Clone the repository
		if (!this.outputChannel) {
			this.outputChannel = vscode.window.createOutputChannel('DeepWiki Generation');
			this.outputChannel!.show();
		}
		
		this.outputChannel!.appendLine('');
		this.outputChannel!.appendLine('=== Cloning DeepWiki Repository ===');
		this.outputChannel!.appendLine('Cloning deepwiki-open repository...');

		try {
			fs.mkdirSync(path.dirname(deepwikiPath), { recursive: true });
			const { stdout, stderr } = await execAsync(
				'git clone https://github.com/intel-sandbox/deepwiki-open .tmp_repos/.deepwiki-repo',
				{ cwd: workspaceRoot }
			);
			
			if (stdout) this.outputChannel!.appendLine(stdout);
			if (stderr) this.outputChannel!.appendLine(stderr);
			
			this.outputChannel!.appendLine('✓ Repository cloned successfully');
			return deepwikiPath;
		} catch (error) {
			this.outputChannel!.appendLine(`✗ Failed to clone repository: ${error}`);
			throw new Error(`Failed to clone deepwiki-open: ${error instanceof Error ? error.message : String(error)}`);
		}
	}

	/**
	 * Step 2: Check and setup GITHUB_TOKEN
	 */
	private async setupGitHubToken(): Promise<void> {
		// Check if GITHUB_TOKEN is already set
		if (process.env.GITHUB_TOKEN) {
			return;
		}

		// Prompt user for token with instructions embedded
		const token = await vscode.window.showInputBox({
			prompt: 
				'GitHub Personal Access Token Required\n\n' +
				'Setup: Go to https://github.com/settings/tokens → Generate new token (classic) → ' +
				'Enable Copilot access → Select scopes: read:user and repo → Copy token and paste below',
			password: true,
			placeHolder: 'Paste your GitHub token here, it is something like ghp_*',
			ignoreFocusOut: true,
			validateInput: (value) => {
				if (!value || value.trim().length < 10) {
					return 'GitHub token is required (minimum 10 characters)';
				}
				return null;
			},
			title: 'GitHub Token for DeepWiki'
		});

		if (!token) {
			throw new Error('GitHub token is required for DeepWiki generation');
		}

		// Set the environment variable
		process.env.GITHUB_TOKEN = token.trim();
		
		// Also set it in the shell for child processes
		this.currentProcess = exec(`export GITHUB_TOKEN="${token.trim()}"`, { cwd: this.deepwikiPath });
	}

	/**
	 * Step 3: Setup Node.js environment with nvm
	 */
	private async setupNodeEnvironment(): Promise<void> {
		if (!this.deepwikiPath) {
			throw new Error('DeepWiki path not set');
		}

		if (!this.outputChannel) {
			this.outputChannel = vscode.window.createOutputChannel('DeepWiki Generation');
			this.outputChannel!.show();
		}

		this.outputChannel!.appendLine('');
		this.outputChannel!.appendLine('=== Setting up Node.js Environment ===');

		try {
			// Check if nvm is available
			if (!this.isNvmInstalled()) {
				// nvm not installed, install it
				this.outputChannel!.appendLine('nvm not found, installing...');
				
				const installNvm = `
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"
`;
				
				await execAsync(installNvm, {
					cwd: this.deepwikiPath,
					shell: '/bin/bash'
				});
				
				this.outputChannel!.appendLine('✓ nvm installed successfully');
			}

			// Check Node.js version
			const checkNodeScript = `
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"
node --version
`;
			
			let needsNode22 = false;
			try {
				const { stdout } = await execAsync(checkNodeScript, {
					cwd: this.deepwikiPath,
					shell: '/bin/bash'
				});
				
				const version = stdout.trim();
				const majorVersion = parseInt(version.replace('v', '').split('.')[0]);
				
				if (majorVersion < 22) {
					needsNode22 = true;
				}
			} catch {
				needsNode22 = true;
			}

			// Install and use Node 22 if needed
			if (needsNode22) {
				this.outputChannel!.appendLine('Installing Node.js 22...');
				
				const setupNode22 = `
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"
nvm install 22
nvm use 22
`;
				
				await execAsync(setupNode22, {
					cwd: this.deepwikiPath,
					shell: '/bin/bash'
				});
				
				this.outputChannel!.appendLine('✓ Node.js 22 installed and activated');
			}

		} catch (error) {
			this.outputChannel!.appendLine(`✗ Failed to setup Node.js: ${error}`);
			throw new Error(`Failed to setup Node.js environment: ${error instanceof Error ? error.message : String(error)}`);
		}
	}

	/**
	 * Step 4: Setup Python virtual environment
	 */
	private async setupPythonEnvironment(): Promise<void> {
		if (!this.deepwikiPath) {
			throw new Error('DeepWiki path not set');
		}
		if (!this.outputChannel) {
			this.outputChannel = vscode.window.createOutputChannel('DeepWiki Generation');
			this.outputChannel.show();
		}
		this.outputChannel.appendLine('');
		this.outputChannel.appendLine('=== Setting up Python Environment ===');

		await UvManager.ensureInstalled(this.outputChannel);
		await UvManager.setupVenvAndInstall(this.deepwikiPath, this.outputChannel);
	}

	/**
	 * Step 6: Run the DeepWiki generator
	 */
	private async runDeepWikiGenerator(workspaceRoot: string, includeFiles: string[] = []): Promise<void> {
		if (!this.deepwikiPath) {
			throw new Error('DeepWiki path not set');
		}

		if (!this.outputChannel) {
			this.outputChannel = vscode.window.createOutputChannel('DeepWiki Generation');
		}
		
		this.outputChannel.show();
		this.outputChannel.appendLine('');
		this.outputChannel.appendLine('=== Running DeepWiki Generator ===');

		try {
			const outputPath = path.join(workspaceRoot, '.deepwiki');
			
			// Log important paths for debugging
			this.outputChannel!.appendLine('=== DeepWiki Generator Configuration ===');
			this.outputChannel!.appendLine(`Workspace Root: ${workspaceRoot}`);
			this.outputChannel!.appendLine(`DeepWiki Path: ${this.deepwikiPath}`);
			this.outputChannel!.appendLine(`Output Path: ${outputPath}`);
			this.outputChannel!.appendLine(`GitHub Token Set: ${process.env.GITHUB_TOKEN ? 'Yes' : 'No'}`);
			this.outputChannel!.appendLine('========================================');
			this.outputChannel!.appendLine('');
			
			// Build --include-files flags for any README files found in designated sub-directories
			const includeFilesArgs = includeFiles
				.map(f => `  --include-files "${f}" \\`)
				.join('\n');

			// Build the command with deactivate at the end
			// Exclude cloned tool repositories and generated output directories
			const command = `
source .venv/bin/activate && \\
.venv/bin/python -m api.cli generate \\
  --repo-type github \\
  --model-provider github_copilot \\
  --model gpt-4o \\
  --exclude-dirs ".tmp_repos" \\
  --exclude-dirs ".codewiki" \\
  --exclude-dirs ".deepwiki" \\
${includeFilesArgs ? includeFilesArgs + '\n' : ''}  --output "${outputPath}" \\
  "${workspaceRoot}"; \\
deactivate
`;

			this.outputChannel!.appendLine('Running DeepWiki generator...');
			this.outputChannel!.appendLine(`Command: ${command}`);
			this.outputChannel!.appendLine('---');

			this.currentProcess = exec(command, {
				cwd: this.deepwikiPath,
				shell: '/bin/bash',
				maxBuffer: 10 * 1024 * 1024 // 10MB buffer
			});

			// Stream output
			this.currentProcess.stdout?.on('data', (data) => {
				this.outputChannel!.appendLine(data.toString());
			});

			this.currentProcess.stderr?.on('data', (data) => {
				this.outputChannel!.appendLine(data.toString());
			});

			await new Promise((resolve, reject) => {
				this.currentProcess!.on('close', (code) => {
					if (code === 0) {
						this.outputChannel!.appendLine('---');
						this.outputChannel!.appendLine('✓ DeepWiki generation completed successfully');
						resolve(null);
					} else {
						// Check if documentation was partially generated despite errors
						const hasPartialDocs = fs.existsSync(path.join(outputPath, 'overview.md')) || 
						                       fs.existsSync(path.join(outputPath, 'module_tree.json')) ||
						                       (fs.existsSync(outputPath) && fs.readdirSync(outputPath).some(file => file.endsWith('.md')));
						
						this.outputChannel!.appendLine('---');
						if (hasPartialDocs) {
							this.outputChannel!.appendLine(`⚠ Warning: Generation completed with errors (exit code ${code})`);
							this.outputChannel!.appendLine('⚠ Some modules may have failed, but partial documentation was generated');
							resolve(null); // Treat as success since we have partial results
						} else {
							this.outputChannel!.appendLine(`✗ DeepWiki generation failed with code ${code}`);
							reject(new Error(`DeepWiki generation failed with code ${code}`));
						}
					}
				});
			});

		// Post-process: Fix file references to add ../ prefix
		this.outputChannel!.appendLine('');
		this.outputChannel!.appendLine('Post-processing: Fixing file references...');
		await this.fixFileReferences(outputPath, workspaceRoot);
		this.outputChannel!.appendLine('✓ File references fixed');

		// Post-process: Fix Mermaid syntax issues
		this.outputChannel!.appendLine('Post-processing: Fixing Mermaid syntax...');
		await this.fixMermaidSyntax(outputPath);
		this.outputChannel!.appendLine('✓ Mermaid syntax fixed');		} catch (error) {
			this.outputChannel!.appendLine(`✗ Generation failed: ${error}`);
			throw new Error(`DeepWiki generation failed: ${error instanceof Error ? error.message : String(error)}`);
		} finally {
			// Ensure deactivate is called even if there's an error
			try {
				await execAsync('deactivate 2>/dev/null || true', {
					cwd: this.deepwikiPath,
					shell: '/bin/bash'
				});
			} catch {
				// Ignore errors from deactivate
			}
		}
	}

	/**
	 * Fix file references in generated markdown files to add ../ prefix
	 * Since .deepwiki is a subdirectory, references to source files need to go up one level
	 */
	private async fixFileReferences(deepwikiPath: string, workspaceRoot: string): Promise<void> {
		const glob = require('glob');
		const util = require('util');
		const globAsync = util.promisify(glob);

		// Find all markdown files in .deepwiki
		const mdFiles = await globAsync('**/*.md', { cwd: deepwikiPath });

		for (const file of mdFiles) {
			const filePath = path.join(deepwikiPath, file);
			let content = fs.readFileSync(filePath, 'utf-8');
			let modified = false;

			// Fix markdown links like [text](path/to/file)
			// If the file is in .deepwiki, no fix needed. Otherwise add ../
			content = content.replace(
				/\[([^\]]+)\]\(([^)#]+)(#[^\)]*)?\)/g,
				(match, text, linkPath, anchor = '') => {
					// Skip URLs (http://, https://, mailto:, etc.)
					if (/^[a-z]+:\/\//i.test(linkPath) || linkPath.startsWith('mailto:')) {
						return match;
					}
					
					// Skip if already has ../
					if (linkPath.startsWith('../')) {
						return match;
					}
					
					// Check if the referenced file exists in .deepwiki
					const absolutePath = path.join(deepwikiPath, path.dirname(file), linkPath);
					if (fs.existsSync(absolutePath)) {
						// File is in .deepwiki, no modification needed
						return match;
					}
					
					// File is outside .deepwiki, add ../
					modified = true;
					return `[${text}](../${linkPath}${anchor})`;
				}
			);

			// Write back if modified
			if (modified) {
				fs.writeFileSync(filePath, content, 'utf-8');
			}
		}
	}

	/**
	 * Fix Mermaid syntax issues in generated markdown files
	 * Common issues:
	 * - Quotes inside node labels need to be removed or escaped
	 * - Invalid character sequences in labels
	 */
	private async fixMermaidSyntax(deepwikiPath: string): Promise<void> {
		const glob = require('glob');
		const util = require('util');
		const globAsync = util.promisify(glob);

		// Find all markdown files in .deepwiki
		const mdFiles = await globAsync('**/*.md', { cwd: deepwikiPath });

		for (const file of mdFiles) {
			const filePath = path.join(deepwikiPath, file);
			let content = fs.readFileSync(filePath, 'utf-8');
			let modified = false;

			// Fix Mermaid code blocks
			content = content.replace(
				/```mermaid\n([\s\S]*?)```/g,
				(match, mermaidCode) => {
					let fixedCode = mermaidCode;
					let codeModified = false;

					// Fix 1: Remove quotes from node labels (e.g., B[Hook: "onRender"] -> B[Hook: onRender])
					// This handles labels like: A[Text "with quotes"] or B["Quoted"]
					const quotesInLabels = /(\w+)\[([^\]]*)"([^"]*)"/g;
					if (quotesInLabels.test(mermaidCode)) {
						fixedCode = fixedCode.replace(
							/(\w+)\[([^\]]*)"([^"]*)"([^\]]*)\]/g,
							(_labelMatch: string, nodeId: string, before: string, quoted: string, after: string) => {
								codeModified = true;
								// Remove the quotes but keep the text
								return `${nodeId}[${before}${quoted}${after}]`;
							}
						);
					}

					if (codeModified) {
						modified = true;
						return '```mermaid\n' + fixedCode + '```';
					}
					return match;
				}
			);

			// Write back if modified
			if (modified) {
				fs.writeFileSync(filePath, content, 'utf-8');
			}
		}
	}

	/**
	 * Check if nvm is installed
	 */
	private isNvmInstalled(): boolean {
		try {
			execSync('command -v nvm', { stdio: 'ignore', shell: '/bin/bash' });
			return true;
		} catch {
			return false;
		}
	}

	/**
	 * Index documentation with configured memory backend
	 */
	private async indexDocumentation(workspaceRoot: string): Promise<void> {
		const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
		if (!workspaceFolder) {
			return;
		}

		const docPath = path.join(workspaceRoot, '.deepwiki');
		if (!fs.existsSync(docPath)) {
			return;
		}

		// Reuse the existing output channel
		if (!this.outputChannel) {
			this.outputChannel = vscode.window.createOutputChannel('DeepWiki Generation');
			this.outputChannel!.show();
		}

		try {
			this.outputChannel!.appendLine('');
			this.outputChannel!.appendLine('=== Indexing DeepWiki documentation ===');
			const memoryService = createMemoryService(workspaceFolder, this.outputChannel);
			const backendName = getMemoryBackendName();
			this.outputChannel!.appendLine(`Using ${backendName} for indexing...`);
			await memoryService.index(docPath);
			this.outputChannel!.appendLine('✓ Documentation indexed successfully');
		} catch (error) {
			this.outputChannel!.appendLine(`⚠ Warning: Failed to index documentation: ${error}`);
			// Don't throw - indexing failure shouldn't fail the entire generation
		}
	}
}
