import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';
import { CodeWikiTreeProvider } from './wikiTreeProvider';
import { WikiViewerProvider } from './wikiViewerProvider';
import { DebugOutputService, IDebugOutputService } from './debugOutputService';
import { MermaidErrorFixer } from './mermaidErrorFixer';
import { WikiType, WikiTypeDetector } from './wikiTypeDetector';
import { CodeWikiGenerator, DeepWikiGenerator, IWikiGenerator, WikiEvaluator } from './generators';
import { createMemoryService, getMemoryBackendName, IMemoryService } from './memoryService';

const execAsync = promisify(exec);

/**
 * Helper function to generate wiki documentation
 */
async function generateWiki(
	workspaceRoot: string,
	wikiType: WikiType,
	treeProvider: CodeWikiTreeProvider
): Promise<void> {
	// Get the appropriate generator
	let generator: IWikiGenerator;
	if (wikiType === WikiType.CodeWiki) {
		generator = new CodeWikiGenerator();
	} else {
		generator = new DeepWikiGenerator();
	}

	const wikiDisplayName = WikiTypeDetector.getDisplayName(wikiType);

	vscode.commands.executeCommand('setContext', 'codewiki.isGenerating', true);

	await vscode.window.withProgress({
		location: vscode.ProgressLocation.Notification,
		title: `Generating ${wikiDisplayName} documentation`,
		cancellable: true
	}, async (progress, token) => {
		try {
			// Create a progress reporter
			const progressReporter = {
				report: (message: string) => {
					progress.report({ message });
				}
			};

			// Run the generator
			await generator.generate(workspaceRoot, progressReporter, token);

			// Success! Update UI to switch to view mode
			await vscode.commands.executeCommand('setContext', 'codewiki.isGenerating', false);

			// Update tree provider to show the new wiki
			treeProvider.setSelectedWikiType(wikiType);

			vscode.window.showInformationMessage(`${wikiDisplayName} documentation generated successfully!`);
		} catch (error) {
			await vscode.commands.executeCommand('setContext', 'codewiki.isGenerating', false);

			if (error instanceof Error && error.message === 'Generation cancelled') {
				vscode.window.showWarningMessage(`${wikiDisplayName} generation cancelled.`);
			} else {
				const message = error instanceof Error ? error.message : 'Unknown error';
				vscode.window.showErrorMessage(`${wikiDisplayName} generation failed: ${message}`);
			}
		}
	});
}

export function activate(context: vscode.ExtensionContext) {
	console.log('[CodeWiki] Extension activating');
	console.log('[CodeWiki] Current workspace folders:', vscode.workspace.workspaceFolders?.length || 0);
	if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
		console.log('[CodeWiki] Workspace folder paths:', vscode.workspace.workspaceFolders.map((f: vscode.WorkspaceFolder) => f.uri.fsPath).join(', '));
	}

	// Create debug output service
	const debugOutputService: IDebugOutputService = new DebugOutputService();
	console.log('[CodeWiki] Debug output service created');

	// Create Mermaid error fixer
	const mermaidErrorFixer = new MermaidErrorFixer(debugOutputService);
	console.log('[CodeWiki] Mermaid error fixer created');

	// Create tree provider (pass workspaceState for persistent wiki-type selection)
	const treeProvider = new CodeWikiTreeProvider(context.workspaceState);

	// Create viewer provider with debug service
	const viewerProvider = new WikiViewerProvider(context.extensionUri, debugOutputService);
	context.subscriptions.push(viewerProvider);

	// Register tree view
	const treeView = vscode.window.createTreeView('codewiki', {
		treeDataProvider: treeProvider,
		showCollapseAll: true
	});

	console.log('[CodeWiki] Tree view created successfully');
	context.subscriptions.push(treeView);

	// Update tree view title based on wiki type and structure
	const updateTreeViewTitle = () => {
		const title = treeProvider.getViewTitle();
		treeView.title = title;
		console.log('[CodeWiki] Updated tree view title to:', title);
	};

	// Listen to tree data changes to update title
	treeProvider.onDidChangeTreeData(() => {
		// Small delay to ensure structure is loaded before getting title
		setTimeout(updateTreeViewTitle, 50);
	});

	// Trigger initial refresh to populate the view
	setTimeout(() => {
		console.log('[CodeWiki] Triggering initial refresh');
		treeProvider.refresh();
		updateTreeViewTitle();
	}, 100);

	// Register commands
	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.refresh', () => {
			console.log('[CodeWiki] Refresh command triggered');
			treeProvider.refresh();
			updateTreeViewTitle();
		})
	);

	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.generate', async () => {
			console.log('[CodeWiki] Generate command triggered');
			if (!vscode.workspace.workspaceFolders || vscode.workspace.workspaceFolders.length === 0) {
				vscode.window.showErrorMessage('No workspace folder is open. Please open a folder first.');
				return;
			}

			const workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
			const detection = WikiTypeDetector.detect(workspaceRoot);

			// Determine which wiki type to generate based on what exists
			let wikiType: WikiType | undefined;

			if (detection.hasCodeWiki && detection.hasDeepWiki) {
				// Both exist - ask user which one to regenerate
				const choice = await vscode.window.showQuickPick([
					{
						label: '$(file-code) CodeWiki',
						description: WikiTypeDetector.getDescription(WikiType.CodeWiki),
						wikiType: WikiType.CodeWiki
					},
					{
						label: '$(sparkle) DeepWiki',
						description: WikiTypeDetector.getDescription(WikiType.DeepWiki),
						wikiType: WikiType.DeepWiki
					}
				], {
					title: 'Both CodeWiki and DeepWiki exist. Which one do you want to regenerate?',
					placeHolder: 'Select wiki type to regenerate'
				});

				if (!choice) {
					return; // User cancelled
				}

				wikiType = choice.wikiType;
			} else if (detection.hasCodeWiki) {
				// Only CodeWiki exists - regenerate it
				wikiType = WikiType.CodeWiki;
			} else if (detection.hasDeepWiki) {
				// Only DeepWiki exists - regenerate it
				wikiType = WikiType.DeepWiki;
			} else {
				// Neither exists - this should be handled by the specific generate commands
				// But for backward compatibility, default to CodeWiki
				wikiType = WikiType.CodeWiki;
			}

			await generateWiki(workspaceRoot, wikiType, treeProvider);
		})
	);

	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.generateCodeWiki', async () => {
			console.log('[CodeWiki] Generate CodeWiki command triggered');
			if (!vscode.workspace.workspaceFolders || vscode.workspace.workspaceFolders.length === 0) {
				vscode.window.showErrorMessage('No workspace folder is open. Please open a folder first.');
				return;
			}

			const workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
			const detection = WikiTypeDetector.detect(workspaceRoot);

			if (detection.hasCodeWiki) {
				const answer = await vscode.window.showWarningMessage(
					'CodeWiki already exists. Regenerating will delete the existing documentation. Continue?',
					{ modal: true },
					'Regenerate'
				);
				if (answer !== 'Regenerate') { return; }
				fs.rmSync(path.join(workspaceRoot, '.codewiki'), { recursive: true, force: true });
			}

			await generateWiki(workspaceRoot, WikiType.CodeWiki, treeProvider);
		})
	);

	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.generateDeepWiki', async () => {
			try {
				console.log('[CodeWiki] Generate DeepWiki command triggered');
				if (!vscode.workspace.workspaceFolders || vscode.workspace.workspaceFolders.length === 0) {
					vscode.window.showErrorMessage('No workspace folder is open. Please open a folder first.');
					return;
				}

				const workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
				const detection = WikiTypeDetector.detect(workspaceRoot);

				if (detection.hasDeepWiki) {
					const answer = await vscode.window.showWarningMessage(
						'DeepWiki already exists. Regenerating will delete the existing documentation. Continue?',
						{ modal: true },
						'Regenerate'
					);
					if (answer !== 'Regenerate') { return; }
					fs.rmSync(path.join(workspaceRoot, '.deepwiki'), { recursive: true, force: true });
				}

				console.log('[CodeWiki] Workspace root:', workspaceRoot);
				await generateWiki(workspaceRoot, WikiType.DeepWiki, treeProvider);
			} catch (error) {
				console.error('[CodeWiki] Error in generateDeepWiki command:', error);
				vscode.window.showErrorMessage(`Failed to start DeepWiki generation: ${error instanceof Error ? error.message : String(error)}`);
			}
		})
	);

	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.viewCodeWiki', () => {
			treeProvider.setSelectedWikiType(WikiType.CodeWiki);
		})
	);

	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.viewDeepWiki', () => {
			treeProvider.setSelectedWikiType(WikiType.DeepWiki);
		})
	);

	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.evaluateWiki', async () => {
			console.log('[CodeWiki] Evaluate Wiki command triggered');
			if (!vscode.workspace.workspaceFolders || vscode.workspace.workspaceFolders.length === 0) {
				vscode.window.showErrorMessage('No workspace folder is open. Please open a folder first.');
				return;
			}
			const workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
			const evaluator = new WikiEvaluator();
			await evaluator.evaluate(workspaceRoot);
		})
	);

	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.selectWikiType', async () => {
			console.log('[CodeWiki] Select wiki type command triggered');
			if (!vscode.workspace.workspaceFolders || vscode.workspace.workspaceFolders.length === 0) {
				vscode.window.showErrorMessage('No workspace folder is open. Please open a folder first.');
				return;
			}

			const workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
			const detection = WikiTypeDetector.detect(workspaceRoot);

			if (!WikiTypeDetector.hasAnyWiki(detection)) {
				vscode.window.showWarningMessage('No wiki documentation found. Please generate one first.');
				return;
			}

			// Build options based on what exists
			const options: Array<{ label: string; description: string; wikiType: WikiType }> = [];

			if (detection.hasCodeWiki) {
				options.push({
					label: '$(file-code) CodeWiki',
					description: WikiTypeDetector.getDescription(WikiType.CodeWiki),
					wikiType: WikiType.CodeWiki
				});
			}

			if (detection.hasDeepWiki) {
				options.push({
					label: '$(sparkle) DeepWiki',
					description: WikiTypeDetector.getDescription(WikiType.DeepWiki),
					wikiType: WikiType.DeepWiki
				});
			}

			if (options.length === 1) {
				// Only one option, no need to ask
				vscode.window.showInformationMessage(`Viewing ${WikiTypeDetector.getDisplayName(options[0].wikiType)}`);
				return;
			}

			const choice = await vscode.window.showQuickPick(options, {
				title: 'Select which wiki to view',
				placeHolder: 'Choose wiki type'
			});

			if (!choice) {
				return; // User cancelled
			}

			// Update the selected wiki type
			treeProvider.setSelectedWikiType(choice.wikiType);
		})
	);

	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.openFile', (filePath: string, wikiType?: WikiType) => {
			console.log('[CodeWiki] Opening file:', filePath, 'wikiType:', wikiType);
			viewerProvider.openWikiFile(filePath);
		})
	);

	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.openInEditor', async (filePath: string) => {
			console.log('[CodeWiki] Opening file in editor:', filePath);
			const doc = await vscode.workspace.openTextDocument(filePath);
			await vscode.window.showTextDocument(doc);
		})
	);

	// Register command to show debug output
	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.showDebugOutput', () => {
			console.log('[CodeWiki] Show debug output command triggered');
			const output = debugOutputService.consoleOutput;
			
			if (output.length === 0) {
				vscode.window.showInformationMessage('No debug output captured yet.');
				return;
			}

			// Create a new document with the output
			const outputText = output.join('\n');
			vscode.workspace.openTextDocument({
				content: outputText,
				language: 'log'
			}).then(doc => {
				vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
			});
		})
	);

	// Register command to check GitHub token (debug)
	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.checkGitHubToken', () => {
			const hasToken = !!process.env.GITHUB_TOKEN;
			const tokenPreview = hasToken 
				? process.env.GITHUB_TOKEN!.substring(0, 10) + '...' 
				: 'Not set';
			
			vscode.window.showInformationMessage(
				`GitHub Token Status:\n${hasToken ? '✅ Set' : '❌ Not set'}\nValue: ${tokenPreview}`,
				'Clear Token',
				'OK'
			).then(choice => {
				if (choice === 'Clear Token') {
					delete process.env.GITHUB_TOKEN;
					vscode.window.showInformationMessage('GitHub token cleared from memory');
				}
			});
		})
	);

	// Register command to show only Mermaid errors
	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.showMermaidErrors', () => {
			console.log('[CodeWiki] Show Mermaid errors command triggered');
			const errors = debugOutputService.getMermaidErrors();
			
			if (errors.length === 0) {
				vscode.window.showInformationMessage('No Mermaid errors captured.');
				return;
			}

			// Parse and format Mermaid errors for better readability
			const formattedErrors = errors.map((error, index) => {
				try {
					const match = error.match(/\[.*?\] \[ERROR\] \[mermaid\] (.*)/);
					if (match) {
						const errorData = JSON.parse(match[1]);
						return `
=== Mermaid Error ${index + 1} ===
Diagram Index: ${errorData.diagramIndex}
Error: ${errorData.error}
Stack: ${errorData.stack || 'N/A'}

Diagram Code:
${errorData.code}

==========================================
`;
					}
				} catch (e) {
					// If parsing fails, return the raw error
					return error;
				}
				return error;
			}).join('\n');

			vscode.workspace.openTextDocument({
				content: formattedErrors,
				language: 'log'
			}).then(doc => {
				vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
			});
		})
	);

	// Register command to clear debug output
	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.clearDebugOutput', () => {
			console.log('[CodeWiki] Clear debug output command triggered');
			debugOutputService.clearOutput();
			vscode.window.showInformationMessage('Debug output cleared.');
		})
	);

	// Register command to fix Mermaid rendering errors with Copilot
	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.fixMermaidErrors', async () => {
			console.log('[CodeWiki] Analyze Mermaid rendering errors command triggered');
			await mermaidErrorFixer.sendErrorsToCopilot();
		})
	);

	// Register command to show error report in chat
	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.showErrorReport', () => {
			console.log('[CodeWiki] Show error report command triggered');
			const report = mermaidErrorFixer.createErrorReport();
			
			// Copy to clipboard for easy sharing
			vscode.env.clipboard.writeText(report);
			
			// Show in new document
			vscode.workspace.openTextDocument({
				content: report,
				language: 'markdown'
			}).then(doc => {
				vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
			});
			
			vscode.window.showInformationMessage('Error report copied to clipboard');
		})
	);

	// Register command to copy prompt for cross-workspace usage
	context.subscriptions.push(
		vscode.commands.registerCommand('codewiki.copyPromptToClipboard', () => {
			console.log('[CodeWiki] Copy prompt to clipboard command triggered');
			const prompt = mermaidErrorFixer.getCopilotPromptText();
			
			vscode.env.clipboard.writeText(prompt);
			
			vscode.window.showInformationMessage(
				'Copilot prompt copied to clipboard! You can paste it in any VS Code window.',
				'Open in This Window',
				'Done'
			).then(selection => {
				if (selection === 'Open in This Window') {
					vscode.commands.executeCommand('workbench.panel.chat.view.copilot.focus');
				}
			});
		})
	);

	// Optional: Start auto-monitoring for errors
	const config = vscode.workspace.getConfiguration('codewiki');
	if (config.get('autoDetectMermaidErrors', false)) {
		console.log('[CodeWiki] Starting auto-monitoring for Mermaid errors');
		const monitor = mermaidErrorFixer.startAutoMonitoring(5000);
		context.subscriptions.push(monitor);
	}

	// Update tree when workspace folders change
	context.subscriptions.push(
		vscode.workspace.onDidChangeWorkspaceFolders((e) => {
			console.log('[CodeWiki] Workspace folders changed event received');
			console.log('[CodeWiki] Added:', e.added.length, 'Removed:', e.removed.length);
			// Use a small delay to ensure VS Code has updated workspaceFolderCount context
			setTimeout(() => {
				console.log('[CodeWiki] Refreshing tree after workspace change');
				treeProvider.refresh();
			}, 100);
		})
	);

	// Create a single output channel for documentation search
	const searchOutputChannel = vscode.window.createOutputChannel('Documentation Search');
	context.subscriptions.push(searchOutputChannel);

	// Create a single memory service instance for the workspace
	let memoryService: IMemoryService | null = null;
	const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
	
	if (workspaceFolder) {
		memoryService = createMemoryService(workspaceFolder, searchOutputChannel);
		const backendName = getMemoryBackendName();
		searchOutputChannel.appendLine(`Using ${backendName} for documentation search`);
		// Setup memory service once during initialization
		memoryService.setup().catch((err: Error) => {
			console.error(`[${backendName}] Setup failed:`, err);
		});
	}

	// Register Chat Participant that processes docs with LLM
	const chatParticipant = vscode.chat.createChatParticipant(
		'repo-wiki.docs',
		async (request: vscode.ChatRequest, context: vscode.ChatContext, stream: vscode.ChatResponseStream, token: vscode.CancellationToken) => {
			if (!memoryService) {
				stream.markdown('⚠️ No workspace folder found. Please open a project first.\n\n');
				return;
			}

			// Show output channel and add separator for each query
			searchOutputChannel.show(true);
			searchOutputChannel.appendLine('\n' + '='.repeat(80));
			searchOutputChannel.appendLine(`Query: "${request.prompt}"`);
			searchOutputChannel.appendLine('='.repeat(80) + '\n');

			try {
				// Check if memory service is set up
				if (!memoryService.isReady()) {
					const backendName = getMemoryBackendName();
					stream.markdown('⚠️ **Documentation search is not yet set up.**\n\n');
					stream.markdown('Please generate documentation first using:\n');
					stream.markdown('- CodeWiki: Standard repository documentation\n');
					stream.markdown('- DeepWiki: Deep analysis with AI-powered insights\n\n');
					stream.markdown('Use the Repo Wiki view in the sidebar to generate documentation.\n');
					searchOutputChannel.appendLine(`${backendName} is not ready yet.`);
					return;
				}

				// Step 1: Search documentation with configured memory backend
				stream.progress('Searching documentation...');
				const results = await memoryService.search(request.prompt, 5);
				
				if (results.length === 0) {
					stream.markdown('🔍 No results found in the documentation.\n\n');
					stream.markdown('The documentation may not contain information about this topic.\n');
					return;
				}

				// Step 2: Load the actual document contents
				stream.progress('Loading documents...');
				const documentContents: string[] = [];
				
				// Get workspace folder
				const currentWorkspace = vscode.workspace.workspaceFolders?.[0];
				if (!currentWorkspace) {
					stream.markdown('⚠️ Workspace folder not available.\n');
					return;
				}
				
				// Determine wiki type based on what exists
				const hasCodeWiki = fs.existsSync(path.join(currentWorkspace.uri.fsPath, '.codewiki'));
				const hasDeepWiki = fs.existsSync(path.join(currentWorkspace.uri.fsPath, '.deepwiki'));
				const wikiType = hasDeepWiki ? '.deepwiki' : '.codewiki';
				const wikiDir = path.join(currentWorkspace.uri.fsPath, wikiType);
				
				searchOutputChannel.appendLine(`\nAttempting to load ${results.length} document(s)...`);
				searchOutputChannel.appendLine(`Wiki directory: ${wikiDir}`);
				
				for (const result of results) {
					searchOutputChannel.appendLine(`\nProcessing result with filePath: "${result.filePath}"`);
					
					// If filePath is Unknown or empty, use the snippet directly as context
					if (!result.filePath || result.filePath === 'Unknown' || result.filePath === '') {
						searchOutputChannel.appendLine('  -> Using snippet as direct context (no file path)');
						documentContents.push(`# Search Result\n\n${result.snippet}`);
						continue;
					}
					
					// The filePath from search might just be the filename
					// Try to find it in the wiki directory structure
					let fullPath: string;
					
					if (result.filePath.startsWith('.codewiki/') || result.filePath.startsWith('.deepwiki/')) {
						// Already has wiki prefix
						fullPath = path.join(currentWorkspace.uri.fsPath, result.filePath);
						searchOutputChannel.appendLine(`  -> Using prefixed path: ${fullPath}`);
					} else if (path.isAbsolute(result.filePath)) {
						// Absolute path
						fullPath = result.filePath;
						searchOutputChannel.appendLine(`  -> Using absolute path: ${fullPath}`);
					} else {
						// Just a filename - search for it in wiki directory
						fullPath = path.join(wikiDir, result.filePath);
						searchOutputChannel.appendLine(`  -> Trying direct path: ${fullPath}`);
						
						// If not found directly, try to find it recursively
						if (!fs.existsSync(fullPath)) {
							searchOutputChannel.appendLine(`  -> Not found, searching recursively in ${wikiDir}`);
							// Simple recursive search
							const findFile = (dir: string, filename: string): string | null => {
								if (!fs.existsSync(dir)) return null;
								
								const files = fs.readdirSync(dir);
								for (const file of files) {
									const filePath = path.join(dir, file);
									const stat = fs.statSync(filePath);
									
									if (stat.isDirectory()) {
										const found = findFile(filePath, filename);
										if (found) return found;
									} else if (file === filename) {
										return filePath;
									}
								}
								return null;
							};
							
							const found = findFile(wikiDir, result.filePath);
							if (found) {
								searchOutputChannel.appendLine(`  -> Found via recursive search: ${found}`);
								fullPath = found;
							} else {
								searchOutputChannel.appendLine(`  -> Not found anywhere in wiki directory`);
								continue;
							}
						} else {
							searchOutputChannel.appendLine(`  -> File exists at direct path`);
						}
					}
					
					try {
						if (fs.existsSync(fullPath)) {
							const content = fs.readFileSync(fullPath, 'utf-8');
							const relativeToWiki = path.relative(currentWorkspace.uri.fsPath, fullPath);
							documentContents.push(`# ${relativeToWiki}\n\n${content}`);
							searchOutputChannel.appendLine(`  ✓ Successfully loaded document (${content.length} bytes)`);
							
							// Add file reference
							stream.reference(vscode.Uri.file(fullPath));
						} else {
							searchOutputChannel.appendLine(`  ✗ File not found at: ${fullPath}`);
						}
					} catch (err) {
						searchOutputChannel.appendLine(`  ✗ Error reading ${fullPath}: ${err}`);
						// Silently skip files that can't be read
						continue;
					}
				}

				searchOutputChannel.appendLine(`\nLoaded ${documentContents.length} document(s) successfully`);
				searchOutputChannel.appendLine(`Total content size: ${documentContents.reduce((sum, doc) => sum + doc.length, 0)} bytes`);

				if (documentContents.length === 0) {
					stream.markdown('❌ Failed to load documentation files. Check the Output panel (CodeWiki Search) for details.\n\n');
					return;
				}

				// Step 3: Call LLM with documentation context
				stream.progress('Analyzing documentation with AI...');
				
				// Get available language models
				const models = await vscode.lm.selectChatModels({
					vendor: 'copilot',
					family: 'gpt-4o'
				});

				if (models.length === 0) {
					stream.markdown('❌ No language model available. Please ensure GitHub Copilot is active.\n');
					return;
				}

				const model = models[0];
				
				// Build prompt with documentation
				const systemPrompt = `You are a helpful assistant that answers questions about a software project based on its generated documentation.

The user has asked: "${request.prompt}"

Here is the relevant documentation:

${documentContents.join('\n\n---\n\n')}

Based on this documentation, provide a clear, structured answer to the user's question. Include specific details from the documentation and cite which files contain the information.`;

				const messages = [
					vscode.LanguageModelChatMessage.User(systemPrompt)
				];

				const llmResponse = await model.sendRequest(messages, {}, token);
				
				// Step 4: Stream the structured answer
				for await (const fragment of llmResponse.text) {
					stream.markdown(fragment);
				}
				
			} catch (error) {
				stream.markdown(`❌ **Error:**\n\n\`\`\`\n${error instanceof Error ? error.message : String(error)}\n\`\`\`\n`);
			}
		}
	);

	// Set participant properties
	chatParticipant.iconPath = new vscode.ThemeIcon('book');
	
	context.subscriptions.push(chatParticipant);

	console.log('[CodeWiki] Extension activated successfully');
}

export function deactivate() {
	console.log('[CodeWiki] Extension deactivating');
}
