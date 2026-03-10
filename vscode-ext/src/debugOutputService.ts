/**
 * Interface for debug output service
 * Captures console output from webviews and debug sessions
 */
export interface IDebugOutputService {
	/**
	 * Get all captured console output
	 */
	readonly consoleOutput: string[];

	/**
	 * Add a console output entry
	 * @param message The console message
	 * @param level The log level (error, warn, info, log)
	 * @param source The source of the message (e.g., 'mermaid', 'webview')
	 */
	addOutput(message: string, level: string, source: string): void;

	/**
	 * Clear all captured output
	 */
	clearOutput(): void;

	/**
	 * Get output filtered by source
	 * @param source The source to filter by
	 */
	getOutputBySource(source: string): string[];

	/**
	 * Get output filtered by level
	 * @param level The log level to filter by
	 */
	getOutputByLevel(level: string): string[];

	/**
	 * Get all Mermaid parsing errors
	 */
	getMermaidErrors(): string[];
}

/**
 * Entry representing a console output message
 */
interface ConsoleOutputEntry {
	timestamp: Date;
	message: string;
	level: string;
	source: string;
}

/**
 * Implementation of debug output service
 * Stores console output from webviews for debugging purposes
 */
export class DebugOutputService implements IDebugOutputService {
	private _output: ConsoleOutputEntry[] = [];
	private readonly _maxEntries: number = 1000; // Limit to prevent memory issues

	/**
	 * Get all captured console output as formatted strings
	 */
	public get consoleOutput(): string[] {
		return this._output.map(entry => this.formatEntry(entry));
	}

	/**
	 * Add a console output entry
	 */
	public addOutput(message: string, level: string, source: string): void {
		const entry: ConsoleOutputEntry = {
			timestamp: new Date(),
			message,
			level,
			source
		};

		this._output.push(entry);

		// Trim old entries if we exceed the max
		if (this._output.length > this._maxEntries) {
			this._output = this._output.slice(-this._maxEntries);
		}

		// Log to VS Code debug console for immediate visibility
		this.logToDebugConsole(entry);
	}

	/**
	 * Clear all captured output
	 */
	public clearOutput(): void {
		this._output = [];
	}

	/**
	 * Get output filtered by source
	 */
	public getOutputBySource(source: string): string[] {
		return this._output
			.filter(entry => entry.source === source)
			.map(entry => this.formatEntry(entry));
	}

	/**
	 * Get output filtered by level
	 */
	public getOutputByLevel(level: string): string[] {
		return this._output
			.filter(entry => entry.level === level)
			.map(entry => this.formatEntry(entry));
	}

	/**
	 * Get all Mermaid parsing errors
	 */
	public getMermaidErrors(): string[] {
		return this._output
			.filter(entry => entry.source === 'mermaid' && entry.level === 'error')
			.map(entry => this.formatEntry(entry));
	}

	/**
	 * Format a console entry as a string
	 */
	private formatEntry(entry: ConsoleOutputEntry): string {
		const timestamp = entry.timestamp.toISOString();
		return `[${timestamp}] [${entry.level.toUpperCase()}] [${entry.source}] ${entry.message}`;
	}

	/**
	 * Log entry to VS Code debug console
	 */
	private logToDebugConsole(entry: ConsoleOutputEntry): void {
		const formatted = this.formatEntry(entry);
		
		switch (entry.level) {
			case 'error':
				console.error(formatted);
				break;
			case 'warn':
				console.warn(formatted);
				break;
			case 'info':
			case 'log':
			default:
				console.log(formatted);
				break;
		}
	}
}
