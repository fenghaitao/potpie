import * as vscode from 'vscode';
import { DspyMemoryService } from './dspyMemoryService';
import { ChromadbMemoryService } from './chromadbMemoryService';
import { ConfigurationManager } from './configurationManager';

/**
 * Search result interface shared by all memory services
 */
export interface SearchResult {
	filePath: string;
	snippet: string;
	score?: number;
}

/**
 * Abstract interface for memory services
 */
export interface IMemoryService {
	/**
	 * Setup the memory service environment
	 */
	setup(): Promise<void>;

	/**
	 * Index a documentation directory
	 */
	index(documentationPath: string): Promise<void>;

	/**
	 * Search indexed documentation
	 */
	search(query: string, topK?: number): Promise<SearchResult[]>;

	/**
	 * Check if the memory service is setup and ready to use
	 */
	isReady(): boolean;
}

/**
 * Factory function to create the appropriate memory service based on configuration
 */
export function createMemoryService(
	workspaceFolder: vscode.WorkspaceFolder,
	outputChannel: vscode.OutputChannel
): IMemoryService {
	const config = ConfigurationManager.getConfig();
	const backend = config.memoryBackend;

	switch (backend) {
		case 'chromadb':
			return new ChromadbMemoryService(workspaceFolder, outputChannel);
		case 'dspy':
			return new DspyMemoryService(workspaceFolder, outputChannel);
		default:
			// Default to chromadb
			return new ChromadbMemoryService(workspaceFolder, outputChannel);
	}
}

/**
 * Get the name of the current memory backend from configuration
 */
export function getMemoryBackendName(): string {
	const config = ConfigurationManager.getConfig();
	return config.memoryBackend === 'dspy' ? 'DSPy-Memory' : 'ChromaDB Memory';
}
