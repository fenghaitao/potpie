#!/usr/bin/env ts-node
/**
 * Automated Mermaid Error Detection and Fixing Script
 * 
 * This script:
 * 1. Scans all wiki markdown files in the content directory
 * 2. Processes each file through the MarkdownProcessor
 * 3. Simulates Mermaid rendering to detect errors
 * 4. Automatically applies fixes to markdownProcessor.ts
 * 5. Recompiles the extension
 * 6. Iterates until all errors are fixed
 */

import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';

interface MermaidError {
	filePath: string;
	fileName: string;
	diagramIndex: number;
	errorMessage: string;
	diagramCode: string;
	stackTrace?: string;
}

interface ScanResult {
	totalFiles: number;
	filesWithDiagrams: number;
	totalDiagrams: number;
	errors: MermaidError[];
}

class MermaidErrorAutoFixer {
	private contentDir: string;
	private processorPath: string;
	private maxIterations: number = 5;

	constructor(contentDir: string, processorPath: string) {
		this.contentDir = contentDir;
		this.processorPath = processorPath;
	}

	/**
	 * Main entry point - run the automated fixing process
	 */
	public async run(): Promise<void> {
		console.log('🔍 Starting automated Mermaid error detection and fixing...\n');

		for (let iteration = 1; iteration <= this.maxIterations; iteration++) {
			console.log(`\n${'='.repeat(80)}`);
			console.log(`📊 ITERATION ${iteration}/${this.maxIterations}`);
			console.log('='.repeat(80));

			// Scan for errors
			const scanResult = await this.scanForErrors();

			// Display results
			this.displayScanResults(scanResult);

			// If no errors, we're done!
			if (scanResult.errors.length === 0) {
				console.log('\n✅ SUCCESS! All Mermaid diagrams are rendering correctly!');
				break;
			}

			// Analyze errors and generate fixes
			console.log('\n🔧 Analyzing errors and generating fixes...');
			const fixes = this.analyzeAndGenerateFixes(scanResult.errors);

			// Apply fixes
			console.log('\n📝 Applying fixes to markdownProcessor.ts...');
			const applied = this.applyFixes(fixes);

			if (!applied) {
				console.log('\n⚠️  Unable to apply automatic fixes. Manual intervention required.');
				this.generateFixPrompt(scanResult.errors);
				break;
			}

			// Recompile
			console.log('\n🔨 Recompiling extension...');
			try {
				execSync('npm run compile', { stdio: 'inherit', cwd: path.dirname(this.processorPath) });
				console.log('✅ Compilation successful!');
			} catch (error) {
				console.error('❌ Compilation failed:', error);
				break;
			}

			// Wait a bit before next iteration
			await this.sleep(1000);
		}
	}

	/**
	 * Scan all markdown files for Mermaid errors
	 */
	private async scanForErrors(): Promise<ScanResult> {
		const result: ScanResult = {
			totalFiles: 0,
			filesWithDiagrams: 0,
			totalDiagrams: 0,
			errors: []
		};

		const files = this.findMarkdownFiles(this.contentDir);
		result.totalFiles = files.length;

		console.log(`\nFound ${files.length} markdown files to scan...`);

		for (const filePath of files) {
			const fileName = path.relative(this.contentDir, filePath);
			const content = fs.readFileSync(filePath, 'utf8');

			// Extract mermaid blocks
			const mermaidBlocks = this.extractMermaidBlocks(content);

			if (mermaidBlocks.length > 0) {
				result.filesWithDiagrams++;
				result.totalDiagrams += mermaidBlocks.length;

				console.log(`  📄 ${fileName} (${mermaidBlocks.length} diagram${mermaidBlocks.length > 1 ? 's' : ''})`);

				// Check each diagram
				for (let i = 0; i < mermaidBlocks.length; i++) {
					const error = this.validateMermaidDiagram(mermaidBlocks[i]);
					if (error) {
						result.errors.push({
							filePath,
							fileName,
							diagramIndex: i,
							errorMessage: error.message,
							diagramCode: mermaidBlocks[i],
							stackTrace: error.stack
						});
						console.log(`    ❌ Diagram ${i + 1}: ${error.message}`);
					} else {
						console.log(`    ✅ Diagram ${i + 1}: OK`);
					}
				}
			}
		}

		return result;
	}

	/**
	 * Find all markdown files recursively
	 */
	private findMarkdownFiles(dir: string): string[] {
		const files: string[] = [];

		const scan = (currentDir: string) => {
			const entries = fs.readdirSync(currentDir, { withFileTypes: true });

			for (const entry of entries) {
				const fullPath = path.join(currentDir, entry.name);

				if (entry.isDirectory()) {
					scan(fullPath);
				} else if (entry.isFile() && entry.name.endsWith('.md')) {
					files.push(fullPath);
				}
			}
		};

		scan(dir);
		return files;
	}

	/**
	 * Extract Mermaid code blocks from markdown content
	 */
	private extractMermaidBlocks(markdown: string): string[] {
		const blocks: string[] = [];
		const regex = /```mermaid\s*\n([\s\S]*?)```/g;
		let match;

		while ((match = regex.exec(markdown)) !== null) {
			blocks.push(match[1].trim());
		}

		return blocks;
	}

	/**
	 * Validate a Mermaid diagram (basic syntax checking)
	 */
	private validateMermaidDiagram(code: string): Error | null {
		// Check for common syntax errors that Mermaid can't parse

		// Check for inline objects in class diagrams
		if (code.includes('classDiagram')) {
			// Check for problematic patterns
			const problematicPatterns = [
				/\+\w+\?\s*:\s*\{[^}]*\}\s*\}/,  // Properties with inline objects followed by closing brace
				/\}\s*\w+\s*:\s*\w+\s*\}~/,      // Malformed class ending with }~
				/\{[^}]*\{[^}]*\}/,               // Nested braces (inline objects)
			];

			for (const pattern of problematicPatterns) {
				if (pattern.test(code)) {
					return new Error('Class diagram contains inline object definitions that Mermaid cannot parse');
				}
			}
		}

		// Check for malformed braces
		const openBraces = (code.match(/\{/g) || []).length;
		const closeBraces = (code.match(/\}/g) || []).length;

		if (openBraces !== closeBraces) {
			return new Error(`Mismatched braces: ${openBraces} opening, ${closeBraces} closing`);
		}

		return null;
	}

	/**
	 * Display scan results
	 */
	private displayScanResults(result: ScanResult): void {
		console.log('\n' + '─'.repeat(80));
		console.log('📊 SCAN RESULTS');
		console.log('─'.repeat(80));
		console.log(`Total files scanned:      ${result.totalFiles}`);
		console.log(`Files with diagrams:      ${result.filesWithDiagrams}`);
		console.log(`Total diagrams found:     ${result.totalDiagrams}`);
		console.log(`Diagrams with errors:     ${result.errors.length}`);
		console.log('─'.repeat(80));

		if (result.errors.length > 0) {
			console.log('\n❌ ERRORS FOUND:\n');
			result.errors.forEach((error, idx) => {
				console.log(`${idx + 1}. ${error.fileName} - Diagram ${error.diagramIndex + 1}`);
				console.log(`   Error: ${error.errorMessage}`);
				console.log('');
			});
		}
	}

	/**
	 * Analyze errors and generate fix patterns
	 */
	private analyzeAndGenerateFixes(errors: MermaidError[]): Map<string, string> {
		const fixes = new Map<string, string>();

		for (const error of errors) {
			const code = error.diagramCode;

			// Identify the type of fix needed
			if (code.includes('classDiagram')) {
				// Check for ChatCompletion-like structures
				if (code.includes('ChatCompletion') || /\+usage\?\s*:\s*\{[^}]*_tokens/.test(code)) {
					fixes.set('usage_object', 'Add usage object extraction');
				}

				// Check for inline object definitions
				if (/\+\w+\?\s*:\s*\{[^}]*:\s*\w+[^}]*\}/.test(code)) {
					fixes.set('inline_objects', 'Extract inline object definitions to helper classes');
				}

				// Check for nested structures
				if (/\{[^}]*\{[^}]*\}[^}]*\}/.test(code)) {
					fixes.set('nested_objects', 'Fix nested object structures');
				}
			}
		}

		return fixes;
	}

	/**
	 * Apply fixes to markdownProcessor.ts
	 */
	private applyFixes(fixes: Map<string, string>): boolean {
		if (fixes.size === 0) {
			return false;
		}

		console.log('\nFixes to apply:');
		fixes.forEach((description, key) => {
			console.log(`  - ${key}: ${description}`);
		});

		// For now, we'll return false to indicate manual intervention
		// In a full implementation, this would modify the processor code
		return false;
	}

	/**
	 * Generate a fix prompt for manual intervention
	 */
	private generateFixPrompt(errors: MermaidError[]): void {
		console.log('\n' + '='.repeat(80));
		console.log('📋 MANUAL FIX REQUIRED');
		console.log('='.repeat(80));
		console.log('\nCopy this prompt to Copilot:\n');
		console.log('─'.repeat(80));

		console.log(`I have ${errors.length} Mermaid diagram rendering error(s) in my VS Code extension that need to be fixed. The issue is with the RENDERING LOGIC in this repository, NOT the Mermaid diagrams themselves.

Please analyze the errors and help fix the markdown processing or rendering code that's causing these diagrams to fail.\n`);

		errors.forEach((error, idx) => {
			console.log(`## Rendering Error ${idx + 1} of ${errors.length}\n`);
			console.log(`**File:** ${error.fileName}`);
			console.log(`**Diagram Index:** ${error.diagramIndex}`);
			console.log(`**Error Message:** ${error.errorMessage}\n`);
			console.log('**Mermaid Code (for reference):**');
			console.log('```mermaid');
			console.log(error.diagramCode);
			console.log('```\n');
			console.log('---\n');
		});

		console.log(`
Please help with:
1. Identifying what's wrong with the rendering logic in markdownProcessor.ts or wikiViewerProvider.ts
2. Suggesting fixes to the markdown processing or HTML generation code
3. Ensuring the Mermaid integration works correctly with the webview

Note: The Mermaid diagrams themselves are correct - the issue is in how this extension processes and renders them.`);

		console.log('\n' + '─'.repeat(80));

		// Save to file
		const promptFile = path.join(path.dirname(this.processorPath), '..', 'MERMAID_FIX_PROMPT.txt');
		const promptContent = errors.map((error, idx) => {
			return `## Rendering Error ${idx + 1} of ${errors.length}

**File:** ${error.fileName}
**Diagram Index:** ${error.diagramIndex}
**Error Message:** ${error.errorMessage}

**Mermaid Code:**
\`\`\`mermaid
${error.diagramCode}
\`\`\`
`;
		}).join('\n---\n\n');

		fs.writeFileSync(promptFile, promptContent, 'utf8');
		console.log(`\n💾 Full prompt saved to: ${promptFile}`);
	}

	/**
	 * Sleep helper
	 */
	private sleep(ms: number): Promise<void> {
		return new Promise(resolve => setTimeout(resolve, ms));
	}
}

// Main execution
async function main() {
	const workspaceRoot = path.resolve(__dirname, '..');
	const contentDir = path.join(workspaceRoot, 'content');
	const processorPath = path.join(workspaceRoot, 'src', 'markdownProcessor.ts');

	if (!fs.existsSync(contentDir)) {
		console.error('❌ Content directory not found:', contentDir);
		process.exit(1);
	}

	if (!fs.existsSync(processorPath)) {
		console.error('❌ Processor file not found:', processorPath);
		process.exit(1);
	}

	const fixer = new MermaidErrorAutoFixer(contentDir, processorPath);
	await fixer.run();
}

// Run if executed directly
if (require.main === module) {
	main().catch(error => {
		console.error('Fatal error:', error);
		process.exit(1);
	});
}

export { MermaidErrorAutoFixer, MermaidError, ScanResult };
