import * as vscode from 'vscode';

/**
 * Configuration schema and validation for CodeWiki extension
 */
export interface CodeWikiConfig {
	memoryBackend: 'chromadb' | 'dspy';
	autoDetectMermaidErrors: boolean;
	mermaidTheme: 'auto' | 'default' | 'dark' | 'forest' | 'neutral';
	maxFileSize: number;
	enablePerformanceMonitoring: boolean;
	debugMode: boolean;
}

export class ConfigurationManager {
	private static readonly CONFIG_SECTION = 'codewiki';

	/**
	 * Get all CodeWiki configuration
	 */
	static getConfig(): CodeWikiConfig {
		const config = vscode.workspace.getConfiguration(this.CONFIG_SECTION);
		
		return {
			memoryBackend: config.get<CodeWikiConfig['memoryBackend']>('memoryBackend', 'chromadb'),
			autoDetectMermaidErrors: config.get<boolean>('autoDetectMermaidErrors', false),
			mermaidTheme: config.get<CodeWikiConfig['mermaidTheme']>('mermaid.theme', 'auto'),
			maxFileSize: config.get<number>('maxFileSize', 10 * 1024 * 1024), // 10MB default
			enablePerformanceMonitoring: config.get<boolean>(
				'enablePerformanceMonitoring',
				false
			),
			debugMode: config.get<boolean>('debugMode', false),
		};
	}

	/**
	 * Get a specific configuration value
	 */
	static get<T>(key: keyof CodeWikiConfig, defaultValue: T): T {
		const config = vscode.workspace.getConfiguration(this.CONFIG_SECTION);
		return config.get<T>(key, defaultValue);
	}

	/**
	 * Update a configuration value
	 */
	static async update<K extends keyof CodeWikiConfig>(
		key: K,
		value: CodeWikiConfig[K],
		target: vscode.ConfigurationTarget = vscode.ConfigurationTarget.Workspace
	): Promise<void> {
		const config = vscode.workspace.getConfiguration(this.CONFIG_SECTION);
		await config.update(key, value, target);
	}

	/**
	 * Watch for configuration changes
	 */
	static onConfigChange(
		callback: (config: CodeWikiConfig) => void
	): vscode.Disposable {
		return vscode.workspace.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(this.CONFIG_SECTION)) {
				callback(this.getConfig());
			}
		});
	}

	/**
	 * Validate configuration
	 */
	static validate(config: CodeWikiConfig): { valid: boolean; errors: string[] } {
		const errors: string[] = [];

		if (config.maxFileSize < 0) {
			errors.push('maxFileSize must be a positive number');
		}

		if (config.maxFileSize > 100 * 1024 * 1024) {
			errors.push('maxFileSize should not exceed 100MB');
		}

		return {
			valid: errors.length === 0,
			errors,
		};
	}
}
