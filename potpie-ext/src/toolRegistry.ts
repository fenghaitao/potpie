/**
 * toolRegistry.ts
 *
 * Generic, reusable tool registry for the potpie agent loop.
 *
 * Skills request tools by returning structured JSON; the extension executes
 * the tool and feeds the result back to the LLM.  All implementation details
 * (subprocess spawning, file I/O, etc.) live inside the tool handlers — the
 * skill itself stays declarative.
 *
 * Usage:
 *   const registry = new ToolRegistry();
 *   registry.registerTool('evaluate_wiki', {
 *     description: 'Run the wiki evaluation pipeline',
 *     requiredParams: ['project_id', 'wiki_dir', 'output'],
 *     handler: async (params) => { ... },
 *   });
 *   const result = await registry.executeTool('evaluate_wiki', { ... });
 */

// ── Types ─────────────────────────────────────────────────────────────────────

/** A tool handler receives validated parameters and returns a result string. */
export type ToolHandler = (params: Record<string, unknown>) => Promise<string>;

/** Full definition of a registered tool. */
export interface ToolDefinition {
  /** Human-readable description shown to the LLM as part of the system prompt. */
  description: string;
  /** Parameter names that MUST be present; validated before handler is called. */
  requiredParams: string[];
  handler: ToolHandler;
}

// ── ToolRegistry ──────────────────────────────────────────────────────────────

export class ToolRegistry {
  private readonly _tools = new Map<string, ToolDefinition>();

  /**
   * Register a tool.  Fluent — returns `this` so calls can be chained.
   *
   * @param name    Unique tool name (used in `"action"` JSON field).
   * @param def     Tool definition with description, required params, handler.
   */
  registerTool(name: string, def: ToolDefinition): this {
    this._tools.set(name, def);
    return this;
  }

  /** Returns true if a tool with `name` is registered. */
  hasTool(name: string): boolean {
    return this._tools.has(name);
  }

  /**
   * Execute a registered tool after validating its parameters.
   *
   * @throws if the tool is not registered or a required parameter is missing.
   */
  async executeTool(name: string, params: Record<string, unknown>): Promise<string> {
    const def = this._tools.get(name);
    if (!def) {
      const available = [...this._tools.keys()].join(', ');
      throw new Error(`Unknown tool: "${name}". Available tools: ${available}`);
    }

    const missing = def.requiredParams.filter((p) => !(p in params) || params[p] === undefined);
    if (missing.length > 0) {
      throw new Error(
        `Tool "${name}" is missing required parameter(s): ${missing.join(', ')}`,
      );
    }

    return def.handler(params);
  }

  /**
   * Return a summary of all registered tools for inclusion in a system prompt.
   *
   * Format:
   *   - evaluate_wiki(project_id, wiki_dir, output): Run the wiki evaluation pipeline
   */
  describeTools(): string {
    return [...this._tools.entries()]
      .map(([name, def]) => {
        const sig = `${name}(${def.requiredParams.join(', ')})`;
        return `- ${sig}: ${def.description}`;
      })
      .join('\n');
  }
}
