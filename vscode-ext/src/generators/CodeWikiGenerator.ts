import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { exec } from 'child_process';
import { promisify } from 'util';
import { IWikiGenerator, GenerationProgress } from './IWikiGenerator';
import { WikiType } from '../wikiTypeDetector';
import { createMemoryService, getMemoryBackendName } from '../memoryService';
import { UvManager } from '../utils/uvManager';

const execAsync = promisify(exec);

/**
 * Generator for CodeWiki documentation
 */
export class CodeWikiGenerator implements IWikiGenerator {
	private currentProcess: ReturnType<typeof exec> | undefined;
	private codewikiPath: string | undefined;

	getWikiType(): WikiType {
		return WikiType.CodeWiki;
	}

	async checkPrerequisites(workspaceRoot: string): Promise<boolean> {
		// Check basic prerequisites
		return true;
	}

	async generate(
		workspaceRoot: string,
		progress: GenerationProgress,
		cancellationToken: vscode.CancellationToken
	): Promise<void> {
		const outputChannel = vscode.window.createOutputChannel('CodeWiki Setup');
		outputChannel.show();

		try {
			// Handle cancellation
			let cancelled = false;
			cancellationToken.onCancellationRequested(() => {
				cancelled = true;
				if (this.currentProcess) {
					this.currentProcess.kill();
				}
			});

			// Step 1: Setup CodeWiki repository
			outputChannel.appendLine('=== Step 1/6: Setting up CodeWiki repository ===');
			progress.report('Setting up CodeWiki repository...');
			await this.setupCodeWikiRepo(workspaceRoot, outputChannel);
			if (cancelled) { throw new Error('Generation cancelled'); }

			// Step 2: Setup Python environment
			outputChannel.appendLine('\n=== Step 2/6: Setting up Python environment ===');
			progress.report('Setting up Python environment...');
			await this.setupPythonEnvironment(outputChannel);
			if (cancelled) { throw new Error('Generation cancelled'); }

			// Step 3: Check API configuration
			outputChannel.appendLine('\n=== Step 3/6: Checking API configuration ===');
			progress.report('Checking API configuration...');
			await this.checkApiConfiguration(outputChannel);
			if (cancelled) { throw new Error('Generation cancelled'); }

			// Step 4: Run CodeWiki generation
			outputChannel.appendLine('\n=== Step 4/6: Running CodeWiki generation ===');
			progress.report('Generating documentation (this may take 30-60 minutes)...');
			await this.runCodeWikiGenerator(workspaceRoot, outputChannel);
			if (cancelled) { throw new Error('Generation cancelled'); }

			// Step 5: Index documentation with configured memory backend
			outputChannel.appendLine('\n=== Step 5/6: Indexing documentation ===');
			progress.report('Indexing documentation for search...');
			await this.indexDocumentation(workspaceRoot, outputChannel);
			if (cancelled) { throw new Error('Generation cancelled'); }

			// Step 6: Cleanup
			outputChannel.appendLine('\n=== Step 6/6: Finalizing ===');
			outputChannel.appendLine('✓ CodeWiki generation completed successfully!');
			outputChannel.appendLine(`✓ Documentation saved to: ${path.join(workspaceRoot, '.codewiki')}`);
			
			vscode.window.showInformationMessage('CodeWiki generation completed!');

		} catch (error) {
			outputChannel.appendLine(`✗ Generation failed: ${error}`);
			throw new Error(`CodeWiki generation failed: ${error instanceof Error ? error.message : String(error)}`);
		}
	}

/**
 * Step 1: Setup CodeWiki repository
 */
private async setupCodeWikiRepo(workspaceRoot: string, outputChannel: vscode.OutputChannel): Promise<void> {
	this.codewikiPath = path.join(workspaceRoot, '.tmp_repos', '.codewiki-repo');

	try {
		fs.mkdirSync(path.dirname(this.codewikiPath), { recursive: true });
		if (fs.existsSync(this.codewikiPath)) {
			outputChannel.appendLine(`CodeWiki repository already exists at: ${this.codewikiPath}`);
			outputChannel.appendLine('Updating repository...');
			await execAsync('git pull', { cwd: this.codewikiPath });
			outputChannel.appendLine('✓ Repository updated');
		} else {
			outputChannel.appendLine(`Cloning CodeWiki repository to: ${this.codewikiPath}`);
			await execAsync(`git clone https://github.com/intel-sandbox/RepoWiki ${this.codewikiPath}`);
			outputChannel.appendLine('✓ Repository cloned successfully');
		}
	} catch (error) {
		outputChannel.appendLine(`✗ Failed to setup repository: ${error}`);
		throw new Error(`Failed to setup CodeWiki repository: ${error instanceof Error ? error.message : String(error)}`);
	}
}

/**
 * Step 2: Setup Python virtual environment
 */
private async setupPythonEnvironment(outputChannel: vscode.OutputChannel): Promise<void> {
	if (!this.codewikiPath) {
		throw new Error('CodeWiki path not set');
	}
	await UvManager.ensureInstalled(outputChannel);
	await UvManager.setupVenvAndInstall(this.codewikiPath, outputChannel);
}

/**
 * Step 3: Check and configure API key
 */
private async checkApiConfiguration(outputChannel: vscode.OutputChannel): Promise<void> {
	if (!this.codewikiPath) {
		throw new Error('CodeWiki path not set');
	}

	try {
		const { stdout: configOutput } = await execAsync(
			'source .venv/bin/activate && codewiki config show',
			{ cwd: this.codewikiPath, shell: '/bin/bash' }
		);

		outputChannel.appendLine('Configuration:');
		outputChannel.appendLine(configOutput);

		const hasApiKey = configOutput.includes('(in system keychain)') ||
			(configOutput.includes('API Key:') && !configOutput.includes('Not set'));

		if (!hasApiKey) {
			outputChannel.appendLine('⚠ API key not configured');
			
			const apiKey = await vscode.window.showInputBox({
				prompt: 'API key required. Get your key from https://platform.iflow.cn/profile?tab=apiKey',
				password: true,
				placeHolder: 'Paste your API key here',
				ignoreFocusOut: true,
				validateInput: (value) => {
					if (!value || value.trim().length < 10) {
						return 'API key must be at least 10 characters';
					}
					return null;
				}
			});

			if (!apiKey) {
				throw new Error('API key required for generation');
			}

			outputChannel.appendLine('Configuring API key and GitHub Copilot model...');
			await execAsync(
				`source .venv/bin/activate && codewiki config set --api-key "${apiKey.trim()}" --base-url "https://api.githubcopilot.com" --main-model "github_copilot/gpt-4o" --cluster-model "github_copilot/gpt-4o"`,
				{ cwd: this.codewikiPath, shell: '/bin/bash' }
			);
			outputChannel.appendLine('✓ API key and model configured successfully');
		} else {
			outputChannel.appendLine('✓ API key already configured');
			
			// Still configure the model to use GitHub Copilot even if API key exists
			outputChannel.appendLine('Configuring GitHub Copilot model...');
			await execAsync(
				`source .venv/bin/activate && codewiki config set --base-url "https://api.githubcopilot.com" --main-model "github_copilot/gpt-4o" --cluster-model "github_copilot/gpt-4o"`,
				{ cwd: this.codewikiPath, shell: '/bin/bash' }
			);
			outputChannel.appendLine('✓ Model configured to use GitHub Copilot (github_copilot/gpt-4o)');
		}
	} catch (error) {
		outputChannel.appendLine(`✗ Failed to check API configuration: ${error}`);
		throw new Error(`API configuration failed: ${error instanceof Error ? error.message : String(error)}`);
	}
}

/**
 * Step 4: Run CodeWiki generation
 */
private async runCodeWikiGenerator(workspaceRoot: string, outputChannel: vscode.OutputChannel): Promise<void> {
	if (!this.codewikiPath) {
		throw new Error('CodeWiki path not set');
	}

	const outputPath = path.join(workspaceRoot, '.codewiki');

	try {
		outputChannel.appendLine(`Generating documentation for: ${workspaceRoot}`);
		outputChannel.appendLine(`Output directory: ${outputPath}`);
		outputChannel.appendLine('This may take 30-60 minutes depending on repository size...');
		outputChannel.appendLine('');

		// Exclude cloned tool repositories and generated output directories
		const generateCommand = `source .venv/bin/activate && codewiki generate --root "${workspaceRoot}" --output "${outputPath}" --exclude ".tmp_repos,.codewiki,.deepwiki"`;

		const generateProcess = exec(generateCommand, {
			cwd: this.codewikiPath,
			shell: '/bin/bash',
			maxBuffer: 50 * 1024 * 1024 // 50MB buffer
		});

		// Stream stdout
		generateProcess.stdout?.on('data', (data: Buffer) => {
			outputChannel.append(data.toString());
		});

		// Stream stderr
		generateProcess.stderr?.on('data', (data: Buffer) => {
			outputChannel.append(data.toString());
		});

		await new Promise<void>((resolve, reject) => {
			generateProcess.on('close', (code) => {
				if (code === 0) {
					resolve();
				} else {
					// Check if documentation was partially generated despite errors
					const hasPartialDocs = fs.existsSync(path.join(outputPath, 'overview.md')) || 
					                       fs.existsSync(path.join(outputPath, 'module_tree.json'));
					
					if (hasPartialDocs) {
						outputChannel.appendLine('');
						outputChannel.appendLine(`⚠ Warning: Generation completed with errors (exit code ${code})`);
						outputChannel.appendLine('⚠ Some modules may have failed, but partial documentation was generated');
						resolve(); // Treat as success since we have partial results
					} else {
						reject(new Error(`Generation process exited with code ${code}`));
					}
				}
			});
			generateProcess.on('error', (error) => {
				reject(error);
			});
		});

		outputChannel.appendLine('');
		outputChannel.appendLine('✓ Generation completed successfully');

	} catch (error) {
		outputChannel.appendLine(`✗ Generation failed: ${error}`);
		
		// Check if we have any documentation despite the error
		const outputPath = path.join(workspaceRoot, '.codewiki');
		const hasAnyDocs = fs.existsSync(outputPath) && (
			fs.existsSync(path.join(outputPath, 'overview.md')) ||
			fs.readdirSync(outputPath).some(file => file.endsWith('.md'))
		);
		
		if (hasAnyDocs) {
			outputChannel.appendLine('⚠ Partial documentation was generated despite errors');
			outputChannel.appendLine(`⚠ Check ${outputPath} for available documentation`);
			// Don't throw - continue to indexing step
		} else {
			throw new Error(`CodeWiki generation failed: ${error instanceof Error ? error.message : String(error)}`);
		}
	}
}

	/**
	 * Step 5: Index documentation with configured memory backend
	 */
	private async indexDocumentation(workspaceRoot: string, outputChannel: vscode.OutputChannel): Promise<void> {
		const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
		if (!workspaceFolder) {
			outputChannel.appendLine('⚠ Warning: No workspace folder found, skipping indexing');
			return;
		}

		const docPath = path.join(workspaceRoot, '.codewiki');
		if (!fs.existsSync(docPath)) {
			outputChannel.appendLine('⚠ Warning: Documentation directory not found, skipping indexing');
			return;
		}

		try {
			const memoryService = createMemoryService(workspaceFolder, outputChannel);
			const backendName = getMemoryBackendName();
			outputChannel.appendLine(`Using ${backendName} for indexing...`);
			await memoryService.index(docPath);
			outputChannel.appendLine('✓ Documentation indexed successfully');
		} catch (error) {
			outputChannel.appendLine(`⚠ Warning: Failed to index documentation: ${error}`);
			// Don't throw - indexing failure shouldn't fail the entire generation
		}
	}
}