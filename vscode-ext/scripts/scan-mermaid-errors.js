#!/usr/bin/env node
/**
 * Automated Mermaid Error Scanner
 * 
 * Scans all wiki markdown files and validates Mermaid diagrams
 * by parsing them with the Mermaid library
 */

const fs = require('fs');
const path = require('path');

class MermaidErrorScanner {
	constructor(contentDir) {
		this.contentDir = contentDir;
		this.mermaid = null;
	}

	/**
	 * Initialize Mermaid for parsing
	 */
	async initMermaid() {
		console.log('🔧 Initializing Mermaid parser...\n');
		
		try {
			// Set up DOMPurify globally
			const createDOMPurify = require('dompurify');
			const { JSDOM } = require('jsdom');
			const window = new JSDOM('').window;
			global.DOMPurify = createDOMPurify(window);
			
			// Import Mermaid dynamically
			const mermaidModule = await import('mermaid');
			this.mermaid = mermaidModule.default;
			
			// Initialize Mermaid
			this.mermaid.initialize({
				startOnLoad: false,
				theme: 'default',
				securityLevel: 'loose',
				logLevel: 'fatal', // Suppress console output
				maxTextSize: 50000,
				maxEdges: 500
			});
			
			console.log('✅ Mermaid initialized successfully\n');
		} catch (error) {
			console.error('❌ Failed to initialize Mermaid:', error.message);
			process.exit(1);
		}
	}

	/**
	 * Main scanning entry point
	 */
	async scan() {
		console.log('🔍 Starting Mermaid syntax validation...\n');
		
		await this.initMermaid();

		const files = this.findMarkdownFiles(this.contentDir);
		const result = {
			totalFiles: files.length,
			filesWithDiagrams: 0,
			totalDiagrams: 0,
			errors: []
		};

		console.log(`Found ${files.length} markdown files to scan...\n`);

		for (const filePath of files) {
			const fileName = path.relative(this.contentDir, filePath);
			const content = fs.readFileSync(filePath, 'utf8');

			// Extract mermaid blocks
			const mermaidBlocks = this.extractMermaidBlocks(content);

			if (mermaidBlocks.length > 0) {
				result.filesWithDiagrams++;
				result.totalDiagrams += mermaidBlocks.length;

				console.log(`  📄 ${fileName} (${mermaidBlocks.length} diagram${mermaidBlocks.length > 1 ? 's' : ''})`);

				// Validate each diagram
				for (let i = 0; i < mermaidBlocks.length; i++) {
					const error = await this.validateMermaidDiagram(mermaidBlocks[i], i);
					if (error) {
						result.errors.push({
							filePath,
							fileName,
							diagramIndex: i,
							errorMessage: error,
							diagramCode: mermaidBlocks[i]
						});
						console.log(`    ❌ Diagram ${i + 1}: ${error}`);
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
	findMarkdownFiles(dir) {
		const files = [];

		const scan = (currentDir) => {
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
	extractMermaidBlocks(markdown) {
		const blocks = [];
		const regex = /```mermaid\s*\n([\s\S]*?)```/g;
		let match;

		while ((match = regex.exec(markdown)) !== null) {
			blocks.push(match[1].trim());
		}

		return blocks;
	}

	/**
	 * Validate a Mermaid diagram by parsing it
	 */
	async validateMermaidDiagram(code, index) {
		try {
			// Clean the code
			const cleanCode = code.trim();
			
			// Use Mermaid's parse function to validate syntax
			await this.mermaid.parse(cleanCode);
			
			// If parse succeeds without throwing, it's valid
			return null; // No error
		} catch (error) {
			// Extract meaningful error message
			let errorMessage = error.message || String(error);
			
			// Clean up error message for better readability
			errorMessage = errorMessage
				.replace(/^Error: /, '')
				.replace(/Parse error on line \d+:\s*/, 'Parse error: ')
				.replace(/\n.*$/s, '') // Remove stack trace
				.split('\n')[0] // Take first line only
				.trim();
			
			// Make error message more readable
			if (errorMessage.length > 100) {
				errorMessage = errorMessage.substring(0, 100) + '...';
			}
			
			return errorMessage;
		}
	}

	/**
	 * Display scan results
	 */
	displayResults(result) {
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
		} else {
			console.log('\n✅ No errors found! All diagrams are valid.\n');
		}

		return result;
	}

	/**
	 * Generate a fix prompt for Copilot
	 */
	generateFixPrompt(errors) {
		if (errors.length === 0) {
			return '';
		}

		let prompt = `I have ${errors.length} Mermaid diagram rendering error(s) in my VS Code extension that need to be fixed. The issue is with the RENDERING LOGIC in this repository, NOT the Mermaid diagrams themselves.

Please analyze the errors and help fix the markdown processing or rendering code that's causing these diagrams to fail.

`;

		errors.forEach((error, idx) => {
			prompt += `## Rendering Error ${idx + 1} of ${errors.length}

**File:** ${error.fileName}
**Diagram Index:** ${error.diagramIndex}
**Error Message:** ${error.errorMessage}

**Mermaid Code (for reference):**
\`\`\`mermaid
${error.diagramCode}
\`\`\`

---

`;
		});

		prompt += `
Please help with:
1. Identifying what's wrong with the rendering logic in markdownProcessor.ts or wikiViewerProvider.ts
2. Suggesting fixes to the markdown processing or HTML generation code
3. Ensuring the Mermaid integration works correctly with the webview

Note: The Mermaid diagrams themselves are correct - the issue is in how this extension processes and renders them.
`;

		return prompt;
	}
}

// Main execution
async function main() {
	const workspaceRoot = path.resolve(__dirname, '..');
	const contentDir = path.join(workspaceRoot, 'content');

	if (!fs.existsSync(contentDir)) {
		console.error('❌ Content directory not found:', contentDir);
		process.exit(1);
	}

	const scanner = new MermaidErrorScanner(contentDir);
	const result = await scanner.scan();
	scanner.displayResults(result);

	// Generate fix prompt
	if (result.errors.length > 0) {
		const prompt = scanner.generateFixPrompt(result.errors);
		
		// Save to file
		const promptFile = path.join(workspaceRoot, 'MERMAID_FIX_PROMPT.txt');
		fs.writeFileSync(promptFile, prompt, 'utf8');
		
		console.log('\n' + '='.repeat(80));
		console.log('📋 FIX PROMPT GENERATED');
		console.log('='.repeat(80));
		console.log(`\n💾 Full prompt saved to: ${promptFile}`);
		console.log('\n📋 You can now copy this prompt to Copilot to fix the errors.\n');
	}
}

// Run if executed directly
if (require.main === module) {
	main().catch(err => {
		console.error('❌ Fatal error:', err);
		process.exit(1);
	});
}

module.exports = { MermaidErrorScanner };
