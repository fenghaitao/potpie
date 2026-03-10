import * as vscode from 'vscode';
import { IDebugOutputService } from './debugOutputService';

/**
 * Parsed Mermaid error information
 */
export interface MermaidErrorInfo {
	diagramIndex: number;
	error: string;
	stack?: string;
	code: string;
	filePath?: string;
}

/**
 * Service to automatically detect Mermaid rendering errors and help fix the rendering logic using Copilot.
 * This tool is designed to help fix issues in the extension's markdown processing and rendering code,
 * not to fix the Mermaid diagrams themselves.
 */
export class MermaidErrorFixer {
	constructor(
		private readonly debugOutputService: IDebugOutputService
	) {}

	/**
	 * Parse Mermaid errors from debug output
	 */
	public parseMermaidErrors(): MermaidErrorInfo[] {
		const errors = this.debugOutputService.getMermaidErrors();
		const parsedErrors: MermaidErrorInfo[] = [];

		for (const error of errors) {
			try {
				// Extract JSON from the error line
				const match = error.match(/\[.*?\] \[ERROR\] \[mermaid\] (.*)/);
				if (match) {
					const errorData = JSON.parse(match[1]);
					parsedErrors.push({
						diagramIndex: errorData.diagramIndex,
						error: errorData.error,
						stack: errorData.stack,
						code: errorData.code
					});
				}
			} catch (e) {
				console.error('[MermaidErrorFixer] Failed to parse error:', e);
			}
		}

		return parsedErrors;
	}

	/**
	 * Send rendering errors to Copilot Chat for analysis and fixing
	 */
	public async sendErrorsToCopilot(): Promise<void> {
		const errors = this.parseMermaidErrors();

		if (errors.length === 0) {
			vscode.window.showInformationMessage('No Mermaid rendering errors to fix!');
			return;
		}

		// Build a comprehensive prompt for Copilot
		const prompt = this.buildCopilotPrompt(errors);

		try {
			// Send to Copilot Chat
			await vscode.commands.executeCommand('workbench.action.chat.open', {
				query: prompt
			});
			
			vscode.window.showInformationMessage(`Sent ${errors.length} Mermaid rendering error(s) to Copilot for analysis.`);
		} catch (error) {
			console.error('[MermaidErrorFixer] Failed to open Copilot Chat:', error);
			
			// Fallback: Copy to clipboard
			await vscode.env.clipboard.writeText(prompt);
			vscode.window.showWarningMessage(
				'Could not open Copilot Chat. Prompt copied to clipboard - paste it in the chat window.',
				'Open Chat'
			).then(selection => {
				if (selection === 'Open Chat') {
					vscode.commands.executeCommand('workbench.panel.chat.view.copilot.focus');
				}
			});
		}
	}

	/**
	 * Build a detailed prompt for Copilot to fix the rendering logic errors
	 */
	private buildCopilotPrompt(errors: MermaidErrorInfo[]): string {
		let prompt = `I have ${errors.length} Mermaid diagram rendering error(s) in my VS Code extension that need to be fixed. The issue is with the RENDERING LOGIC in this repository, NOT the Mermaid diagrams themselves.\n\n`;
		prompt += `Please analyze the errors and help fix the markdown processing or rendering code that's causing these diagrams to fail.\n\n`;

		errors.forEach((error, index) => {
			prompt += `## Rendering Error ${index + 1} of ${errors.length}\n\n`;
			prompt += `**Diagram Index:** ${error.diagramIndex}\n`;
			prompt += `**Error Message:** ${error.error}\n\n`;
			
			if (error.stack) {
				prompt += `**Stack Trace:**\n\`\`\`\n${error.stack}\n\`\`\`\n\n`;
			}
			
			prompt += `**Mermaid Code (for reference):**\n\`\`\`mermaid\n${error.code}\n\`\`\`\n\n`;
			prompt += `---\n\n`;
		});

		prompt += `\nPlease help with:\n`;
		prompt += `1. Identifying what's wrong with the rendering logic in markdownProcessor.ts or wikiViewerProvider.ts\n`;
		prompt += `2. Suggesting fixes to the markdown processing or HTML generation code\n`;
		prompt += `3. Ensuring the Mermaid integration works correctly with the webview\n`;
		prompt += `\nNote: The Mermaid diagrams themselves are correct - the issue is in how this extension processes and renders them.\n`;

		return prompt;
	}

	/**
	 * Create a summary report of all errors for the chat
	 */
	public createErrorReport(): string {
		const errors = this.parseMermaidErrors();

		if (errors.length === 0) {
			return 'No Mermaid errors detected.';
		}

		let report = `# Mermaid Error Report\n\n`;
		report += `Found ${errors.length} error(s):\n\n`;

		errors.forEach((error, index) => {
			report += `## Error ${index + 1}\n`;
			report += `- **Diagram:** #${error.diagramIndex}\n`;
			report += `- **Error:** ${error.error}\n`;
			report += `- **Code Length:** ${error.code.length} characters\n\n`;
			report += `\`\`\`mermaid\n${error.code.substring(0, 200)}${error.code.length > 200 ? '...' : ''}\n\`\`\`\n\n`;
		});

		return report;
	}

	/**
	 * Get the full Copilot prompt as text (for cross-workspace usage)
	 * Useful when developing the extension and want to paste in another VS Code window
	 */
	public getCopilotPromptText(): string {
		const errors = this.parseMermaidErrors();
		
		if (errors.length === 0) {
			return 'No Mermaid rendering errors to fix.';
		}

		return this.buildCopilotPrompt(errors);
	}

	/**
	 * Automatically monitor for rendering errors and prompt to fix them
	 */
	public startAutoMonitoring(intervalMs: number = 5000): vscode.Disposable {
		let lastErrorCount = 0;

		const intervalId = setInterval(() => {
			const errors = this.parseMermaidErrors();
			
			if (errors.length > lastErrorCount) {
				const newErrors = errors.length - lastErrorCount;
				
				vscode.window.showWarningMessage(
					`Detected ${newErrors} new Mermaid rendering error(s). Analyze them now?`,
					'Analyze with Copilot',
					'Show Errors',
					'Ignore'
				).then(selection => {
					if (selection === 'Analyze with Copilot') {
						this.sendErrorsToCopilot();
					} else if (selection === 'Show Errors') {
						vscode.commands.executeCommand('codewiki.showMermaidErrors');
					}
				});
			}
			
			lastErrorCount = errors.length;
		}, intervalMs);

		return new vscode.Disposable(() => clearInterval(intervalId));
	}
}
