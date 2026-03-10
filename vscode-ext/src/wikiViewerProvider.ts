import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { MarkdownProcessor } from './markdownProcessor';
import { ThemeDetector } from './themeDetector';
import { IDebugOutputService } from './debugOutputService';
import {
	WebviewToExtensionMessage,
	ExtensionToWebviewMessage,
	isOpenWikiLinkMessage,
	isOpenExternalLinkMessage,
	isConsoleLogMessage
} from './webviewMessages';

export class WikiViewerProvider {
	private static readonly viewType = 'codewiki.viewer';
	private readonly _panels = new Map<string, vscode.WebviewPanel>();
	private readonly _markdownProcessor: MarkdownProcessor;
	private _themeChangeListener: vscode.Disposable | undefined;

	constructor(
		private readonly _extensionUri: vscode.Uri,
		private readonly debugOutputService?: IDebugOutputService
	) {
		this._markdownProcessor = new MarkdownProcessor();
		
		// Set up theme change listener
		this._themeChangeListener = ThemeDetector.onThemeChange((theme) => {
			// Update all open panels with new theme
			this._panels.forEach((panel) => {
				panel.webview.postMessage({
					command: 'updateTheme',
					theme: theme
				});
			});
		});
	}

	public dispose(): void {
		if (this._themeChangeListener) {
			this._themeChangeListener.dispose();
		}
	}

	public async openWikiFile(filePath: string) {
		const fileName = path.basename(filePath);

		// Check if we already have a panel for this file
		const existingPanel = this._panels.get(filePath);
		if (existingPanel) {
			existingPanel.reveal();
			return;
		}

		// Create and show a new webview panel
		const panel = vscode.window.createWebviewPanel(
			WikiViewerProvider.viewType,
			`Wiki: ${fileName}`,
			vscode.ViewColumn.One,
			{
				enableScripts: true,
				retainContextWhenHidden: true,
				localResourceRoots: [this._extensionUri]
			}
		);

		this._panels.set(filePath, panel);

		// Handle panel disposal
		panel.onDidDispose(() => {
			this._panels.delete(filePath);
		}, null);

		// Handle messages from webview with type safety
		panel.webview.onDidReceiveMessage(async (message: WebviewToExtensionMessage) => {
			if (isOpenWikiLinkMessage(message)) {
				await this.handleWikiLink(message.href, filePath);
			} else if (isOpenExternalLinkMessage(message)) {
				vscode.env.openExternal(vscode.Uri.parse(message.href));
			} else if (isConsoleLogMessage(message)) {
				// Capture console output from webview
				if (this.debugOutputService) {
					this.debugOutputService.addOutput(
						message.message,
						message.level,
						message.source
					);
				}
			}
		}, null);

		// Load and display the content
		await this.updateWebviewContent(panel, filePath);

		// Watch for file changes and update
		const watcher = vscode.workspace.createFileSystemWatcher(filePath);
		watcher.onDidChange(async () => {
			if (this._panels.has(filePath)) {
				await this.updateWebviewContent(panel, filePath);
			}
		});

		panel.onDidDispose(() => {
			watcher.dispose();
		});
	}

	private async handleWikiLink(href: string, currentFilePath: string) {
		try {
			// Check if it's an anchor link (same page)
			if (href.startsWith('#')) {
				// For anchor links, send message back to webview to scroll to the element
				const panel = this._panels.get(currentFilePath);
				if (panel) {
					panel.webview.postMessage({
						command: 'scrollToAnchor',
						anchor: href.substring(1) // Remove the # prefix
					});
				}
				return;
			}

			// Handle file:// URLs
			if (href.startsWith('file://')) {
				// Remove the file:// prefix
				let filePathPart = href.substring(7); // Remove 'file://'
				
				// Check for line numbers or anchors (e.g., #L1-L113 or #anchor)
				let selection: vscode.Selection | undefined;
				const hashIndex = filePathPart.indexOf('#');
				if (hashIndex !== -1) {
					const fragment = filePathPart.substring(hashIndex + 1);
					filePathPart = filePathPart.substring(0, hashIndex);
					
					// Parse line numbers (e.g., L1-L113 or L42)
					const lineMatch = fragment.match(/^L(\d+)(?:-L(\d+))?$/);
					if (lineMatch) {
						const startLine = parseInt(lineMatch[1], 10) - 1; // VS Code uses 0-based line numbers
						const endLine = lineMatch[2] ? parseInt(lineMatch[2], 10) - 1 : startLine;
						selection = new vscode.Selection(startLine, 0, endLine, Number.MAX_VALUE);
					}
				}
				
				const workspaceRoot = vscode.workspace.workspaceFolders![0].uri.fsPath;
				const targetPath = path.join(workspaceRoot, filePathPart);
				
				if (fs.existsSync(targetPath)) {
					const uri = vscode.Uri.file(targetPath);
					const doc = await vscode.workspace.openTextDocument(uri);
					const editor = await vscode.window.showTextDocument(doc);
					
					// If we have a selection/line range, reveal it
					if (selection) {
						editor.selection = selection;
						editor.revealRange(selection, vscode.TextEditorRevealType.InCenter);
					}
				} else {
					vscode.window.showErrorMessage(`File not found: ${targetPath}`);
				}
				return;
			}

			// Get the directory of the current file to determine wiki root
			const currentDir = path.dirname(currentFilePath);
			
			// Wiki root is the parent of the current directory tree
			// (it will be .codewiki or .deepwiki)
			let wikiRoot = currentDir;
			while (wikiRoot !== path.dirname(wikiRoot)) {
				const dirName = path.basename(wikiRoot);
				if (dirName === '.codewiki' || dirName === '.deepwiki') {
					break;
				}
				wikiRoot = path.dirname(wikiRoot);
			}
			
			// Resolve the href relative to the current file's directory
			let targetPath = path.resolve(currentDir, href);
			
			// If the href doesn't have an extension, try adding .md
			if (!path.extname(targetPath)) {
				targetPath += '.md';
			}
			
			// Check if the file exists
			if (fs.existsSync(targetPath)) {
				// If it's a markdown file, open it in the wiki viewer
				if (targetPath.endsWith('.md')) {
					await this.openWikiFile(targetPath);
				} else {
					// For other files, open in VS Code editor
					const uri = vscode.Uri.file(targetPath);
					await vscode.commands.executeCommand('vscode.open', uri);
				}
			} else {
				// If the file doesn't exist, try to find it relative to the wiki root
				const wikiRelativePath = path.resolve(wikiRoot, href);
				let wikiTargetPath = wikiRelativePath;
				
				if (!path.extname(wikiTargetPath)) {
					wikiTargetPath += '.md';
				}
				
				if (fs.existsSync(wikiTargetPath)) {
					await this.openWikiFile(wikiTargetPath);
				} else {
					vscode.window.showErrorMessage(`Wiki link target not found: ${href}`);
				}
			}
		} catch (error) {
			vscode.window.showErrorMessage(`Failed to open wiki link: ${error}`);
		}
	}

	private async updateWebviewContent(panel: vscode.WebviewPanel, filePath: string) {
		try {
			const content = await fs.promises.readFile(filePath, 'utf8');
			const html = this.getWebviewContent(panel, content, path.basename(filePath));
			panel.webview.html = html;
		} catch (error) {
			vscode.window.showErrorMessage(`Failed to read wiki file: ${error}`);
		}
	}

	/**
	 * Get URI for bundled Mermaid.js script
	 * Following architectural principle: Offline-Capable
	 * Bundle Mermaid.js as extension resource to avoid CDN dependency
	 */
	private getMermaidScriptUri(): vscode.Uri {
		const mermaidPath = vscode.Uri.joinPath(
			this._extensionUri,
			'resources',
			'mermaid',
			'mermaid.min.js'
		);
		return mermaidPath;
	}

	private getWebviewContent(panel: vscode.WebviewPanel, markdownContent: string, fileName: string): string {
		// Get current theme
		const theme = ThemeDetector.getCurrentTheme();
		
		// Convert markdown to HTML using the new processor
		const htmlContent = this._markdownProcessor.convertToHtml(markdownContent);

		// Get URI for bundled Mermaid.js resource
		const mermaidUri = panel.webview.asWebviewUri(this.getMermaidScriptUri());

		return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>${fileName}</title>
	<style>
		body {
			font-family: var(--vscode-font-family);
			font-size: var(--vscode-font-size);
			color: var(--vscode-foreground);
			background-color: var(--vscode-editor-background);
			line-height: 1.6;
			padding: 20px;
			max-width: 900px;
			margin: 0 auto;
		}
		h1, h2, h3, h4, h5, h6 {
			color: var(--vscode-foreground);
			margin-top: 24px;
			margin-bottom: 16px;
			font-weight: 600;
			line-height: 1.25;
		}
		h1 {
			font-size: 2em;
			border-bottom: 1px solid var(--vscode-panel-border);
			padding-bottom: 0.3em;
		}
		h2 {
			font-size: 1.5em;
			border-bottom: 1px solid var(--vscode-panel-border);
			padding-bottom: 0.3em;
		}
		h3 {
			font-size: 1.25em;
		}
		code {
			font-family: var(--vscode-editor-font-family);
			font-size: 0.9em;
			background-color: var(--vscode-textCodeBlock-background);
			padding: 2px 4px;
			border-radius: 3px;
		}
		pre {
			background-color: var(--vscode-textCodeBlock-background);
			padding: 16px;
			border-radius: 6px;
			overflow-x: auto;
			line-height: 1.45;
		}
		pre code {
			background-color: transparent;
			padding: 0;
		}
		a {
			color: var(--vscode-textLink-foreground);
			text-decoration: none;
			cursor: pointer;
		}
		a:hover {
			text-decoration: underline;
		}
		blockquote {
			border-left: 4px solid var(--vscode-textBlockQuote-border);
			background-color: var(--vscode-textBlockQuote-background);
			padding: 8px 16px;
			margin: 16px 0;
		}
		ul, ol {
			padding-left: 2em;
		}
		li {
			margin: 4px 0;
		}
		table {
			border-collapse: collapse;
			width: 100%;
			margin: 16px 0;
		}
		th, td {
			border: 1px solid var(--vscode-panel-border);
			padding: 8px 12px;
			text-align: left;
		}
		th {
			background-color: var(--vscode-editor-inactiveSelectionBackground);
			font-weight: 600;
		}
		img {
			max-width: 100%;
			height: auto;
		}
		hr {
			border: none;
			border-top: 1px solid var(--vscode-panel-border);
			margin: 24px 0;
		}
		.cite {
			border: 1px solid var(--vscode-panel-border) !important;
			border-radius: 4px;
			padding: 16px;
			margin: 16px 0;
			font-size: 0.95em;
		}
		.cite > p:first-child {
			margin-top: 0;
		}
		.cite > p:last-child,
		.cite > ul:last-child,
		.cite > ol:last-child {
			margin-bottom: 0;
		}
		.cite *,
		.cite blockquote,
		.cite > *,
		.cite p,
		.cite ul,
		.cite ol,
		.cite li {
			border-left: 0 !important;
			border-right: 0 !important;
			border-top: 0 !important;
			border-bottom: 0 !important;
			background-color: transparent !important;
		}
		.mermaid {
			background-color: var(--vscode-editor-background);
			padding: 16px;
			margin: 16px 0;
			text-align: center;
		}
		.mermaid-error {
			background-color: var(--vscode-inputValidation-errorBackground);
			border: 1px solid var(--vscode-inputValidation-errorBorder);
			border-radius: 4px;
			padding: 16px;
			margin: 16px 0;
		}
		.error-header {
			display: flex;
			align-items: center;
			gap: 8px;
			margin-bottom: 8px;
			font-weight: 600;
			color: var(--vscode-errorForeground);
		}
		.error-icon {
			font-size: 1.2em;
		}
		.error-message {
			margin: 8px 0;
			font-family: var(--vscode-editor-font-family);
			font-size: 0.9em;
		}
		.error-details {
			margin-top: 12px;
		}
		.error-details summary {
			cursor: pointer;
			color: var(--vscode-textLink-foreground);
			margin-bottom: 8px;
		}
		.error-details pre {
			margin-top: 8px;
			max-height: 200px;
			overflow-y: auto;
		}
		.error-actions {
			margin-top: 12px;
			display: flex;
			gap: 12px;
		}
		.error-actions button,
		.error-actions a {
			padding: 4px 12px;
			border-radius: 2px;
			font-size: 0.9em;
		}
		.error-actions button {
			background-color: var(--vscode-button-background);
			color: var(--vscode-button-foreground);
			border: none;
			cursor: pointer;
		}
		.error-actions button:hover {
			background-color: var(--vscode-button-hoverBackground);
		}
	</style>
	<!-- Load Mermaid.js: bundled version with CDN fallback -->
	<script>
		// Try to load bundled Mermaid.js first
		window.mermaidLoadAttempt = 'bundled';
	</script>
	<script src="${mermaidUri}" 
		onload="console.log('[Mermaid] Bundled library loaded successfully')"
		onerror="console.warn('[Mermaid] Bundled library failed, trying CDN fallback'); window.mermaidLoadAttempt = 'cdn'; var script = document.createElement('script'); script.src = 'https://cdn.jsdelivr.net/npm/mermaid@11.12.1/dist/mermaid.min.js'; script.onload = function() { console.log('[Mermaid] CDN library loaded successfully'); }; script.onerror = function() { console.error('[Mermaid] Both bundled and CDN failed to load'); }; document.head.appendChild(script);"></script>
</head>
<body>
	${htmlContent}
	<script>
		(function() {
			const vscode = acquireVsCodeApi();
			
			// Helper function to send console messages to extension
			function sendConsoleMessage(message, level, source) {
				vscode.postMessage({
					command: 'consoleLog',
					message: message,
					level: level,
					source: source
				});
			}
			
			// Override console methods to capture output
			const originalConsoleLog = console.log;
			const originalConsoleError = console.error;
			const originalConsoleWarn = console.warn;
			const originalConsoleInfo = console.info;
			
			console.log = function(...args) {
				const message = args.join(' ');
				sendConsoleMessage(message, 'log', 'webview');
				originalConsoleLog.apply(console, args);
			};
			
			console.error = function(...args) {
				const message = args.join(' ');
				sendConsoleMessage(message, 'error', 'webview');
				originalConsoleError.apply(console, args);
			};
			
			console.warn = function(...args) {
				const message = args.join(' ');
				sendConsoleMessage(message, 'warn', 'webview');
				originalConsoleWarn.apply(console, args);
			};
			
			console.info = function(...args) {
				const message = args.join(' ');
				sendConsoleMessage(message, 'info', 'webview');
				originalConsoleInfo.apply(console, args);
			};
			
			// Store theme info
			let currentTheme = ${JSON.stringify(theme)};
			
			// Track Mermaid initialization state
			let mermaidReady = false;
			let mermaidInitAttempts = 0;
			const MAX_INIT_ATTEMPTS = 3;
			
			// Initialize Mermaid
			function initializeMermaid() {
				if (typeof mermaid === 'undefined') {
					console.error('[Mermaid] Library not loaded from CDN');
					if (mermaidInitAttempts < MAX_INIT_ATTEMPTS) {
						mermaidInitAttempts++;
						console.log('[Mermaid] Retrying initialization, attempt', mermaidInitAttempts);
						setTimeout(initializeMermaid, 1000);
					} else {
						console.error('[Mermaid] Max initialization attempts reached');
						showMermaidLoadError();
					}
					return;
				}
				
				try {
					// Configure mermaid with improved settings
					mermaid.initialize({ 
						startOnLoad: false,
						theme: currentTheme.mermaidTheme,
						securityLevel: 'loose', // Allow more flexibility with diagram content
						logLevel: 'error', // Reduce console noise
						maxTextSize: 50000, // Increase text size limit
						maxEdges: 500, // Increase edge limit
						deterministicIds: true, // Use deterministic IDs for consistency
						fontFamily: 'var(--vscode-font-family), monospace'
					});
					mermaidReady = true;
					console.log('[Mermaid] Initialized successfully with theme:', currentTheme.mermaidTheme);
					renderAllDiagrams();
				} catch (error) {
					console.error('[Mermaid] Initialization error:', error);
					showMermaidLoadError();
				}
			}
			
			// Render all Mermaid diagrams
			async function renderAllDiagrams() {
				if (!mermaidReady) {
					console.warn('[Mermaid] Not ready, skipping render');
					return;
				}
				
				const diagrams = document.querySelectorAll('.mermaid');
				console.log('[Mermaid] Found', diagrams.length, 'diagrams to render');
				
				for (let i = 0; i < diagrams.length; i++) {
					const diagram = diagrams[i];
					await renderDiagram(diagram, i);
				}
			}
			
			// Render a single diagram
			async function renderDiagram(element, index) {
				try {
					// Get code from the data attribute
					const code = element.getAttribute('data-mermaid-code');
					if (!code) {
						throw new Error('No code found in diagram element');
					}
					const id = element.id || \`mermaid-diagram-\${index}\`;
					element.id = id;
					
					console.log('[Mermaid] Rendering diagram', index, 'with id:', id);
					console.log('[Mermaid] Code length:', code.length, 'characters');
					
					// Clear the element before rendering
					element.removeAttribute('data-mermaid-code');
					
					// Render the diagram
					const { svg } = await mermaid.render(id + '-svg', code);
					element.innerHTML = svg;
					element.classList.add('mermaid-rendered');
					console.log('[Mermaid] Successfully rendered diagram', index);
				} catch (error) {
					const errorMessage = \`Mermaid render error for diagram \${index}: \${error.message || error}\`;
					console.error('[Mermaid]', errorMessage);
					
					// Get code for error display (try to get from data attribute if still there)
					const code = element.getAttribute('data-mermaid-code') || 'Code not found';
					
					// Send detailed error info to extension
					sendConsoleMessage(
						JSON.stringify({
							diagramIndex: index,
							error: error.message || String(error),
							stack: error.stack,
							code: code
						}),
						'error',
						'mermaid'
					);
					
					showDiagramError(element, error, index, code);
				}
			}
			
			// Show error when Mermaid library fails to load
			function showMermaidLoadError() {
				const diagrams = document.querySelectorAll('.mermaid');
				diagrams.forEach((diagram, index) => {
					const error = new Error('Failed to load Mermaid library from CDN');
					showDiagramError(diagram, error, index);
				});
			}
			
			// Show error for a specific diagram
			function showDiagramError(element, error, index, code) {
				const errorHtml = \`
					<div class="mermaid-error">
						<div class="error-header">
							<span class="error-icon">⚠️</span>
							<span class="error-title">Diagram Rendering Failed</span>
						</div>
						<div class="error-message">\${error.message || 'Unknown error'}</div>
						<details class="error-details">
							<summary>View diagram code</summary>
							<pre><code>\${escapeHtml(code)}</code></pre>
						</details>
						<div class="error-actions">
							<button onclick="retryDiagram(\${index})">Retry</button>
							<a href="https://mermaid.js.org/intro/" target="_blank">Mermaid Documentation</a>
						</div>
					</div>
				\`;
				element.innerHTML = errorHtml;
				element.classList.add('mermaid-error-container');
			}
			
			// Retry rendering a diagram
			window.retryDiagram = async function(index) {
				const diagrams = document.querySelectorAll('.mermaid');
				if (diagrams[index]) {
					// Get the original code from the error display
					const diagram = diagrams[index];
					const errorDetails = diagram.querySelector('.error-details pre code');
					if (errorDetails) {
						const code = errorDetails.textContent;
						// Restore the code to the data attribute
						diagram.setAttribute('data-mermaid-code', code);
						diagram.innerHTML = '';
					}
					diagram.classList.remove('mermaid-error-container', 'mermaid-rendered');
					
					// Try to render again
					await renderDiagram(diagram, index);
				}
			};
			
			// Escape HTML entities
			function escapeHtml(text) {
				const div = document.createElement('div');
				div.textContent = text;
				return div.innerHTML;
			}
			
			// Handle theme updates
			function updateTheme(newTheme) {
				console.log('[Mermaid] Updating theme from', currentTheme.mermaidTheme, 'to', newTheme.mermaidTheme);
				currentTheme = newTheme;
				if (mermaidReady && typeof mermaid !== 'undefined') {
					try {
						// Re-initialize Mermaid with new theme
						mermaid.initialize({ 
							startOnLoad: false,
							theme: currentTheme.mermaidTheme,
							securityLevel: 'loose',
							logLevel: 'error',
							maxTextSize: 50000,
							maxEdges: 500,
							deterministicIds: true,
							fontFamily: 'var(--vscode-font-family), monospace'
						});
						// Re-render all diagrams
						renderAllDiagrams();
					} catch (error) {
						console.error('[Mermaid] Error updating theme:', error);
					}
				}
			}
			
			// Handle messages from extension
			window.addEventListener('message', event => {
				const message = event.data;
				switch (message.command) {
					case 'scrollToAnchor':
						const element = document.getElementById(message.anchor);
						if (element) {
							element.scrollIntoView({ behavior: 'smooth', block: 'start' });
						}
						break;
					case 'updateTheme':
						updateTheme(message.theme);
						break;
				}
			});
			
			// Handle link clicks
			document.addEventListener('click', function(event) {
				const target = event.target;
				if (target.tagName === 'A' && target.href) {
					event.preventDefault();
					const href = target.getAttribute('href');
					
					// Check if it's a relative link (not starting with http/https)
					if (!href.startsWith('http://') && !href.startsWith('https://')) {
						// Send message to extension to open the linked file
						vscode.postMessage({
							command: 'openWikiLink',
							href: href
						});
					} else {
						// For external links, open in external browser
						vscode.postMessage({
							command: 'openExternalLink',
							href: href
						});
					}
				}
			});
			
			// Initialize when DOM is ready
			if (document.readyState === 'loading') {
				document.addEventListener('DOMContentLoaded', initializeMermaid);
			} else {
				initializeMermaid();
			}
		})();
	</script>
</body>
</html>`;
	}
}
