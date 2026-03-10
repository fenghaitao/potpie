import { marked, Renderer, Tokens, Token } from 'marked';

/**
 * Options for markdown processing
 */
export interface MarkdownOptions {
	/** Base path for resolving relative links */
	basePath?: string;
	/** Whether to sanitize HTML output */
	sanitize?: boolean;
}

/**
 * Interface for markdown-to-HTML conversion
 */
export interface IMarkdownProcessor {
	/**
	 * Convert markdown content to HTML
	 * @param markdown Raw markdown content
	 * @param options Processing options
	 * @returns HTML string with Mermaid blocks preserved
	 */
	convertToHtml(markdown: string, options?: MarkdownOptions): string;
}

/**
 * Markdown processor that converts markdown to HTML while preserving Mermaid diagrams
 */
export class MarkdownProcessor implements IMarkdownProcessor {
	private mermaidBlockCounter: number = 0;

	/**
	 * Convert markdown content to HTML
	 */
	public convertToHtml(markdown: string, options?: MarkdownOptions): string {
		// Reset counter for each document
		this.mermaidBlockCounter = 0;

		// Pre-process markdown to handle custom elements
		const { processedMarkdown, citeBlocks } = this.preprocessMarkdown(markdown);

		// Configure marked with custom renderer
		const renderer = this.createCustomRenderer(options);
		marked.setOptions({
			renderer,
			breaks: true,
			gfm: true
		});

		// Convert markdown to HTML
		let html = marked.parse(processedMarkdown) as string;

		// Post-process HTML to handle cite blocks
		html = this.postprocessHtml(html, citeBlocks);

		return html;
	}

	/**
	 * Pre-process markdown to handle custom syntax
	 */
	private preprocessMarkdown(markdown: string): { processedMarkdown: string; citeBlocks: string[] } {
		const citeBlocks: string[] = [];
		
		// Extract cite blocks and replace with HTML comment placeholders
		// HTML comments won't be escaped by marked
		const processedMarkdown = markdown.replace(/<cite>([\s\S]*?)<\/cite>/g, (match, content) => {
			const index = citeBlocks.length;
			citeBlocks.push(content.trim());
			return `

<!-- CITE_BLOCK_${index} -->

`;
		});
		
		return { processedMarkdown, citeBlocks };
	}

	/**
	 * Post-process HTML to handle custom elements
	 */
	private postprocessHtml(html: string, citeBlocks: string[]): string {
		// Process and replace cite placeholders with styled divs
		citeBlocks.forEach((markdownContent, index) => {
			// Process the markdown content of the cite block
			const processedContent = marked.parse(markdownContent) as string;
			
			// Create the replacement div
			const replacement = `<div class="cite">${processedContent}</div>`;
			
			// Replace the HTML comment placeholder
			const commentPattern = `<!-- CITE_BLOCK_${index} -->`;
			const wrappedPattern = `<p>${commentPattern}</p>`;
			
			// Try both patterns
			html = html.replace(wrappedPattern, replacement);
			html = html.replace(commentPattern, replacement);
		});
		
		return html;
	}

	/**
	 * Create a custom renderer for marked that handles Mermaid blocks specially
	 */
	private createCustomRenderer(options?: MarkdownOptions): Renderer {
		const renderer = new Renderer();

		// Override code block rendering to handle Mermaid
		const originalCode = renderer.code.bind(renderer);
		renderer.code = (code: string, infostring: string | undefined, escaped: boolean): string => {
			if (infostring === 'mermaid') {
				return this.renderMermaidBlock(code);
			}
			// For other code blocks, use default rendering
			return originalCode(code, infostring, escaped);
		};

		// Override heading rendering to add anchor IDs
		renderer.heading = (text: string, level: number, raw: string): string => {
			const id = this.createAnchorId(text);
			return `<h${level} id="${id}">${text}</h${level}>`;
		};

		return renderer;
	}

	/**
	 * Render a Mermaid diagram block
	 * 
	 * Following architectural principle of "Fidelity to Source":
	 * This method performs minimal transformations, preserving diagram source as authored.
	 * Mermaid.js will validate and render diagrams, providing clear error messages if invalid.
	 */
	private renderMermaidBlock(code: string): string {
		const id = `mermaid-diagram-${this.mermaidBlockCounter++}`;
		
		// Minimal cleanup: only normalize line endings and trim whitespace
		// No syntax transformation or "fixing" - render diagrams as authored
		const cleanCode = code
			.replace(/\r\n/g, '\n') // Normalize line endings to \n
			.trim();

		// Store the code in a data attribute instead of in HTML content
		// This preserves special characters without HTML escaping issues
		// The webview JavaScript will extract from the data attribute and render
		return `<div class="mermaid" id="${id}" data-mermaid-code="${this.escapeHtmlAttribute(cleanCode)}"></div>`;
	}

	/**
	 * Legacy method - NO LONGER USED
	 * 
	 * Previously performed aggressive syntax transformations on class diagrams.
	 * This violated architectural principles:
	 * - Loss of source fidelity
	 * - Tight coupling to Mermaid version
	 * - High maintenance burden
	 * 
	 * Current approach: Render diagrams as-is, let Mermaid.js validate.
	 * If syntax errors occur, provide clear error messages for users to fix at authoring time.
	 * 
	 * @deprecated This method is retained for reference but not called
	 */
	private fixMermaidClassDiagramSyntax(code: string): string {
		// Fix nested object structures that Mermaid can't parse
		// Example: { effort? : string; summary? : string } -> ReasoningObject
		
		let fixedCode = code;
		
		// Fix the ChatCompletion class structure with deeply nested Array~{...}~ syntax
		// This is a more robust pattern that handles the specific malformed structure
		// We need to match the entire class including its closing brace
		fixedCode = fixedCode.replace(
			/class\s+ChatCompletion\s*\{[\s\S]*?\+choices\s*:\s*Array~\{[\s\S]*?finish_reason\s*:\s*string[\s\S]*?\}~[\s\S]*?\+usage\?\s*:\s*\{[\s\S]*?\}\s*\}/g,
			`class ChatCompletion {
+id : string
+object : string
+created : number
+model : string
+choices : Array~ChoiceObject~
+usage? : UsageObject
}`
		);
		
		// Fix reasoning object structure
		fixedCode = fixedCode.replace(
			/reasoning\?\s*:\s*\{\s*effort\?\s*:\s*string;\s*summary\?\s*:\s*string\s*\}/g,
			'reasoning? : ReasoningObject'
		);
		
		// Fix timing object structure
		fixedCode = fixedCode.replace(
			/timing\?\s*:\s*\{\s*startTime\s*:\s*number[^}]*\}/g,
			'timing? : TimingObject'
		);
		
		// Fix authorization union type with object - REMOVED
		// This pattern has been moved to the specific patterns section below
		
		// Fix toolCalls parameter structure  
		fixedCode = fixedCode.replace(
			/toolCalls\s*:\s*\{name\s*:\s*string,\s*arguments\s*:\s*string\}\[\]/g,
			'toolCalls : ToolCall[]'
		);
		
		// Fix limits object structure (more flexible pattern)
		fixedCode = fixedCode.replace(
			/limits\?\s*:\s*\{\s*[^}]*max_[^}]*\}/g,
			'limits? : ModelLimits'
		);
		
		// Fix supports object structure (more flexible pattern)
		fixedCode = fixedCode.replace(
			/supports\s*:\s*\{\s*[^}]*tool_calls[^}]*\}/g,
			'supports : ModelSupports'
		);
		
		// Fix complex Array structures with nested objects
		fixedCode = fixedCode.replace(
			/Array~\{\s*index\s*:\s*number[^}]*message\s*:\s*\{[^}]*\}[^}]*\}~/g,
			'Array~ChoiceObject~'
		);
		
		// Fix union types with object literals
		fixedCode = fixedCode.replace(
			/'enabled'\s*\|\s*\{\s*terms\s*:\s*string\s*\}/g,
			'PolicyType'
		);
		
		// Fix method return types with object literals
		fixedCode = fixedCode.replace(
			/\)\s*\{toolName\s*:\s*string[^}]*\}/g,
			') ToolResponseType'
		);
		
		// Fix complex union types with object structures  
		fixedCode = fixedCode.replace(
			/OptionalChatRequestParams\['tool_choice'\]\s*\|\s*\{\s*type\s*:\s*'function'[^}]*\}/g,
			'ToolChoiceType'
		);
		
		// Fix method parameters with object literals
		fixedCode = fixedCode.replace(
			/\(\s*[^)]*\s*:\s*\{[^}]*type\s*:\s*'function'[^}]*\}\s*\)/g,
			'(options : FunctionCallOptions)'
		);
		
		// Fix return types with nested objects (arrays)
		fixedCode = fixedCode.replace(
			/\)\s*\{[^}]*:\s*string[^}]*\}\[\]/g,
			') ToolResponse[]'
		);
		
		// Fix specific problematic patterns first (more specific patterns need to run before general ones)
		fixedCode = fixedCode.replace(
			/\+warning_messages\?\s*:\s*\{\s*code\s*:\s*string[^}]*\}\[\]/g,
			'+warning_messages? : MessageObject[]'
		);
		
		fixedCode = fixedCode.replace(
			/\+info_messages\?\s*:\s*\{\s*code\s*:\s*string[^}]*\}\[\]/g,
			'+info_messages? : MessageObject[]'
		);
		
		fixedCode = fixedCode.replace(
			/\+billing\?\s*:\s*\{\s*is_premium\s*:\s*boolean[^}]*\}/g,
			'+billing? : BillingInfo'
		);
		
		fixedCode = fixedCode.replace(
			/\+custom_model\?\s*:\s*\{\s*key_name\s*:\s*string[^}]*\}/g,
			'+custom_model? : CustomModelInfo'
		);
		
		// IMPORTANT: Most specific patterns must run first to avoid being caught by general patterns
		
		// Fix union types with boolean and object literals (MOST SPECIFIC - run first)
		fixedCode = fixedCode.replace(
			/\+authorization\?\s*:\s*true\s*\|\s*\{\s*label\s*:\s*string[^}]*\}/g,
			'+authorization? : BooleanOrLabelType'
		);
		
		// Fix any remaining true | { object } patterns
		fixedCode = fixedCode.replace(
			/\+([a-zA-Z_$][a-zA-Z0-9_$]*)\?\s*:\s*true\s*\|\s*\{\s*[^}]*\}/g,
			'+$1? : BooleanOrLabelType'
		);
		
		// Fix timing object structure
		fixedCode = fixedCode.replace(
			/\+timing\?\s*:\s*\{\s*startTime\s*:\s*number[^}]*\}/g,
			'+timing? : TimingObject'
		);
		
		// Fix other union types that might have objects (GENERAL - run after specific ones)
		fixedCode = fixedCode.replace(
			/\+([a-zA-Z_$][a-zA-Z0-9_$]*)\?\s*:\s*\w+\s*\|\s*\{\s*[^}]*:\s*string[^}]*\}/g,
			'+$1? : UnionWithObjectType'
		);
		
		fixedCode = fixedCode.replace(
			/\+snippy\?\s*:\s*\{\s*enabled\s*:\s*boolean\s*\}/g,
			'+snippy? : SnippyConfig'
		);
		
		fixedCode = fixedCode.replace(
			/\+stream_options\?\s*:\s*\{\s*include_usage\?\s*:\s*boolean\s*\}/g,
			'+stream_options? : StreamOptions'
		);
		
		// Fix usage object with nested structure (generic pattern)
		fixedCode = fixedCode.replace(
			/\+usage\?\s*:\s*\{\s*[^}]*_tokens\s*:\s*number[^}]*\}/g,
			'+usage? : UsageObject'
		);
		
		// Fix single object return types
		fixedCode = fixedCode.replace(
			/\)\s*\{[^}]*:\s*string[^}]*\}(?!\[)/g,
			') ToolResponseType'
		);
		
		// Fix general object properties with inline object types (after specific ones)
		fixedCode = fixedCode.replace(
			/\+([a-zA-Z_$][a-zA-Z0-9_$]*)\?\s*:\s*\{\s*[^}]*:\s*string[^}]*\}(?!\[)/g,
			'+$1? : ObjectProperty'
		);
		
		// Fix general array properties with object element types (after specific ones)
		fixedCode = fixedCode.replace(
			/\+([a-zA-Z_$][a-zA-Z0-9_$]*)\?\s*:\s*\{\s*[^}]*:\s*string[^}]*\}\[\]/g,
			'+$1? : ObjectProperty[]'
		);
		
		// Add helper class definitions at the end if we made replacements
		if (fixedCode !== code) {
			const helperClasses = `

%% Helper classes for complex types
class ReasoningObject {
+effort? : string
+summary? : string
}
class TimingObject {
+startTime : number
+endTime : number
+duration? : number
}
class AuthorizationType {
<<union>>
TRUE
LABEL_OBJECT
}
class ToolCall {
+name : string
+arguments : string
}
class ModelLimits {
+max_prompt_tokens? : number
+max_output_tokens? : number
+max_context_window_tokens? : number
}
class ModelSupports {
+parallel_tool_calls? : boolean
+tool_calls? : boolean
+streaming : boolean
+vision? : boolean
+prediction? : boolean
+thinking? : boolean
}
class ChoiceObject {
+index : number
+message : MessageObject
+finish_reason : string
}
class MessageObject {
+role : string
+content : string
+tool_calls? : ToolCall[]
}
class UsageObject {
+prompt_tokens : number
+completion_tokens : number
+total_tokens : number
}
class PolicyType {
<<enumeration>>
ENABLED
TERMS_OBJECT
}
class ToolResponseType {
+toolName : string
+result : string
}
class ToolChoiceType {
<<union>>
OPTIONAL_PARAMS
FUNCTION_OBJECT
}
class FunctionCallOptions {
+type : string
+name : string
}
class ToolResponse {
+toolName : string
+result : string
}
class ObjectProperty {
+key : string
+value : any
}
class MessageObject {
+code : string
+message : string
}
class SnippyConfig {
+enabled : boolean
}
class StreamOptions {
+include_usage? : boolean
}
class BillingInfo {
+is_premium : boolean
+multiplier : number
+restricted_to? : string[]
}
class CustomModelInfo {
+key_name : string
+owner_name : string
}
class TimingObject {
+startTime : number
+endTime? : number
}
class BooleanOrLabelType {
<<union>>
BOOLEAN_VALUE
LABEL_OBJECT
}
class UnionWithObjectType {
<<union>>
PRIMITIVE_VALUE
OBJECT_VALUE
}`;

			fixedCode = fixedCode + helperClasses;
		}
		
		return fixedCode;
	}

	/**
	 * Legacy method - NO LONGER USED
	 * 
	 * @deprecated This method is retained for reference but not called
	 */
	private fixClassDiagramSyntax(code: string): string {
		let fixedCode = code;

		// Replace ALL inline object types with "object" (handles nested braces)
		let depth = 0;
		let result = '';
		let inObject = false;

		for (let i = 0; i < fixedCode.length; i++) {
			const char = fixedCode[i];
			if (char === '{') {
				if (depth === 0) {
					inObject = true;
				}
				depth++;
			} else if (char === '}') {
				depth--;
				if (depth === 0 && inObject) {
					result += 'object';
					inObject = false;
					continue;
				}
			}

			if (!inObject) {
				result += char;
			}
		}
		fixedCode = result;

		// Normalize line breaks for single-line diagrams
		if (fixedCode.split('\n').length === 1) {
			fixedCode = fixedCode
				.replace(/classDiagram/g, 'classDiagram\n')
				.replace(/\}class /g, '}\nclass ')
				.replace(/([+\-#~])(\S)/g, '\n$1$2')
				.replace(/\n+/g, '\n')
				.trim();
		}

		// Add newlines after relationship labels
		fixedCode = fixedCode
			.replace(/(:\s*"[^"]*")(\w)/g, '$1\n$2')
			.replace(/(\})(class\s)/gi, '$1\n$2')
			.replace(/(\})([A-Z])/g, '$1\n$2');

		// Wrap complex types in backticks
		fixedCode = fixedCode.split('\n').map((line: string) => {
			const memberMatch = line.match(/^(\s*[+\-#~])(.+)$/);
			if (memberMatch) {
				const visibility = memberMatch[1];
				const rest = memberMatch[2].trim();

				const colonIndex = rest.indexOf(':');
				if (colonIndex > 0) {
					const memberName = rest.substring(0, colonIndex).trim();
					let typeAndRest = rest.substring(colonIndex + 1).trim();

					// Simplify union types with quotes
					if (typeAndRest.includes("'") && typeAndRest.includes('|')) {
						typeAndRest = typeAndRest.replace(/'[^']*'\s*\|\s*\w+/g, 'string');
					}

					// Wrap types with special characters in backticks
					const spaceIndex = typeAndRest.indexOf(' ');
					const type = spaceIndex > 0 ? typeAndRest.substring(0, spaceIndex) : typeAndRest;
					if (type.match(/[?\[\].'<>~|]/) && !type.startsWith('`')) {
						const afterType = spaceIndex > 0 ? typeAndRest.substring(spaceIndex) : '';
						return `${visibility}${memberName} : \`${type}\`${afterType}`;
					}
					return `${visibility}${memberName} : ${typeAndRest}`;
				} else {
					// Old format: +type name
					const spaceIndex = rest.indexOf(' ');
					if (spaceIndex > 0) {
						const type = rest.substring(0, spaceIndex);
						const memberName = rest.substring(spaceIndex);
						if (type.match(/[?\[\].'<>~|]/) && !type.startsWith('`')) {
							return `${visibility}\`${type}\`${memberName}`;
						}
					}
				}
			}
			return line;
		}).join('\n');

		return fixedCode;
	}

	/**
	 * Legacy method - NO LONGER USED
	 * 
	 * @deprecated This method is retained for reference but not called
	 */
	private fixGraphSyntax(code: string): string {
		// Normalize line breaks for graph diagrams
		const fixedCode = code
			.replace(/^(graph\s+\w+)/, '$1\n')
			.replace(/^(flowchart\s+\w+)/, '$1\n')
			.replace(/subgraph\s+/g, '\nsubgraph ')
			.replace(/end(\w)/g, 'end\n$1')
			.replace(/\](\w)/g, ']\n$1')
			.replace(/(\w)(-->|---)/g, '$1\n$2')
			.replace(/(-->|---)(\w)/g, '$1\n$2')
			.replace(/:\s*"([^"]*)"(\w)/g, ': "$1"\n$2')
			.replace(/\n+/g, '\n')
			.trim();

		return fixedCode;
	}

	/**
	 * Create an anchor-friendly ID from header text
	 */
	private createAnchorId(text: string): string {
		return text
			.toLowerCase()
			.replace(/<[^>]*>/g, '') // Remove HTML tags
			.replace(/[^\w\s-]/g, '') // Remove special characters
			.replace(/\s+/g, '-') // Replace spaces with hyphens
			.replace(/-+/g, '-') // Replace multiple hyphens with single
			.trim();
	}

	/**
	 * Escape HTML entities
	 */
	private escapeHtml(text: string): string {
		const htmlEscapes: Record<string, string> = {
			'&': '&amp;',
			'<': '&lt;',
			'>': '&gt;',
			'"': '&quot;',
			"'": '&#39;'
		};
		return text.replace(/[&<>"']/g, (char) => htmlEscapes[char]);
	}

	/**
	 * Escape HTML attribute values
	 * For data attributes, we need to escape quotes and ampersands
	 */
	private escapeHtmlAttribute(text: string): string {
		return text
			.replace(/&/g, '&amp;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#39;');
	}
}
