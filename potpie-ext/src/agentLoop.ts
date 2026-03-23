/**
 * agentLoop.ts
 *
 * Generic, reusable LLM agent loop.
 *
 * Flow:
 *   1. Send messages to the LLM (VS Code Language Model API).
 *   2. Parse the response for a structured tool request:
 *        { "action": "<tool>", "parameters": { ... } }
 *   3. If a tool request is found → execute tool → append result → repeat.
 *   4. If plain text (no JSON tool request) → return as final answer.
 *
 * Safety guarantees:
 *   - Only tools registered in the supplied ToolRegistry can be called.
 *   - Parameters are validated by the registry before handler invocation.
 *   - A hard `maxIterations` cap prevents infinite loops.
 *   - CancellationToken support for VS Code progress dialogs.
 */
import * as vscode from 'vscode';
import { ToolRegistry } from './toolRegistry';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AgentLoopOptions {
  /** Conversation history to send (modified in-place as the loop progresses). */
  messages: vscode.LanguageModelChatMessage[];
  /** Registry of tools the LLM is allowed to invoke. */
  tools: ToolRegistry;
  /** Output channel for streaming LLM text and tool status messages. */
  outputChannel: vscode.OutputChannel;
  /** Maximum LLM↔tool round-trips before forcing termination. Default: 10. */
  maxIterations?: number;
  /** Optional token; cancels the current LLM request if fired. */
  cancellationToken?: vscode.CancellationToken;
}

interface ToolRequest {
  action: string;
  parameters: Record<string, unknown>;
}

// ── JSON parsing ──────────────────────────────────────────────────────────────

/**
 * Returns true when the LLM response contains a bash/sh/shell fenced block
 * instead of a JSON tool request — indicates the LLM needs correction.
 */
function isBashBlock(text: string): boolean {
  return /```(?:bash|sh|shell)\b/i.test(text);
}

/**
 * Try to extract a tool-request JSON object from an LLM response.
 *
 * Handles three common LLM output formats:
 *   1. Pure JSON:      `{ "action": "...", "parameters": { ... } }`
 *   2. Fenced block:  ` ```json\n{ ... }\n``` `  (or ` ``` ` without a tag)
 *   3. Inline JSON embedded in prose.
 *
 * Returns null when the response is plain text (= final answer).
 * NOTE: bash fenced blocks are intentionally NOT matched here — they are
 * caught by `isBashBlock()` and handled with a corrective feedback message.
 */
function tryParseToolRequest(text: string): ToolRequest | null {
  const candidates: string[] = [];

  // 1. Fenced code block — json-tagged or untagged only (bash handled separately)
  const fenced = text.match(/```(?:json)?\s*\n?([\s\S]*?)\n?```/);
  if (fenced) { candidates.push(fenced[1].trim()); }

  // 2. Whole trimmed text (covers pure-JSON responses)
  candidates.push(text.trim());

  // 3. Largest {...} span containing "action" (covers JSON embedded in prose)
  const embedded = text.match(/\{[\s\S]*"action"[\s\S]*\}/);
  if (embedded) { candidates.push(embedded[0]); }

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate);
      if (typeof parsed?.action === 'string') {
        return {
          action: parsed.action,
          parameters: (parsed.parameters && typeof parsed.parameters === 'object')
            ? parsed.parameters as Record<string, unknown>
            : {},
        };
      }
    } catch { /* try next candidate */ }
  }

  return null;
}

// ── Agent loop ────────────────────────────────────────────────────────────────

/**
 * Run the agent loop until the LLM returns a plain-text final answer or
 * `maxIterations` is reached.
 *
 * @returns The last LLM response text (the final answer).
 */
export async function runAgentLoop(opts: AgentLoopOptions): Promise<string> {
  const {
    messages,
    tools,
    outputChannel: ch,
    maxIterations = 10,
    cancellationToken,
  } = opts;

  // Select the best available Copilot model
  const models = await vscode.lm.selectChatModels({ vendor: 'copilot' });
  if (!models || models.length === 0) {
    throw new Error(
      'No Copilot language model available. ' +
      'Ensure GitHub Copilot Chat is installed and you are signed in.',
    );
  }
  const model = models[0];
  ch.appendLine(`[AgentLoop] Model: ${model.name} (family: ${model.family})`);

  const cts = new vscode.CancellationTokenSource();
  const token = cancellationToken ?? cts.token;

  // ── Inject tool-format instructions upfront ──────────────────────────────
  // Prepending this here (not in the caller) ensures every consumer of
  // runAgentLoop automatically gets the constraint, with no risk of a caller
  // forgetting it.  The bash-block correction below is kept as defence-in-depth.
  const toolFormatInstruction = [
    'IMPORTANT: When you need to use a tool, respond with ONLY a JSON object in',
    'this exact format — no prose, no shell commands, no bash blocks:',
    '',
    '```json',
    '{',
    '  "action": "<tool_name>",',
    '  "parameters": { "<key>": "<value>" }',
    '}',
    '```',
    '',
    'After receiving a tool result, respond with plain text (not JSON).',
    '',
    'Registered tools:',
    tools.describeTools(),
  ].join('\n');
  messages.unshift(vscode.LanguageModelChatMessage.User(toolFormatInstruction));

  let lastText = '';

  try {
    for (let iteration = 1; iteration <= maxIterations; iteration++) {
      ch.appendLine(`[AgentLoop] Iteration ${iteration}/${maxIterations} — calling LLM…`);

      // ── Call LLM ───────────────────────────────────────────────────────────
      let response: vscode.LanguageModelChatResponse;
      try {
        response = await model.sendRequest(messages, {}, token);
      } catch (err) {
        throw new Error(`LLM request failed: ${err}`);
      }

      // Stream to output channel while collecting full text
      let responseText = '';
      for await (const chunk of response.text) {
        responseText += chunk;
        ch.append(chunk);
      }
      ch.appendLine('');

      lastText = responseText;

      // ── Try to parse a tool request ────────────────────────────────────────
      const toolRequest = tryParseToolRequest(responseText);
      if (!toolRequest) {
        // LLM output a bash block instead of a JSON tool request — correct it
        if (isBashBlock(responseText)) {
          ch.appendLine('[AgentLoop] LLM generated a bash block instead of a JSON tool request — sending correction…');
          messages.push(
            vscode.LanguageModelChatMessage.Assistant(responseText),
            vscode.LanguageModelChatMessage.User(
              'Please use the JSON tool-request format to invoke tools — do NOT output bash commands.\n' +
              'The required format is:\n' +
              '```json\n{"action": "<tool_name>", "parameters": {"param1": "value1", ...}}\n```\n' +
              'Available tools:\n' + tools.describeTools(),
            ),
          );
          continue;
        }
        ch.appendLine('[AgentLoop] Plain-text response — treating as final answer.');
        break;
      }

      ch.appendLine(`[AgentLoop] Tool requested: "${toolRequest.action}"`);
      ch.appendLine(`[AgentLoop] Parameters: ${JSON.stringify(toolRequest.parameters, null, 2)}`);

      // ── Execute tool ───────────────────────────────────────────────────────
      let toolResult: string;
      try {
        toolResult = await tools.executeTool(toolRequest.action, toolRequest.parameters);
        ch.appendLine(`[AgentLoop] Tool completed (${toolResult.length} chars of output).`);
      } catch (err) {
        toolResult = `TOOL ERROR: ${err}`;
        ch.appendLine(`[AgentLoop] Tool error: ${err}`);
      }

      // ── Feed result back to LLM ────────────────────────────────────────────
      messages.push(
        vscode.LanguageModelChatMessage.Assistant(responseText),
        vscode.LanguageModelChatMessage.User(
          `Tool result for "${toolRequest.action}":\n\n${toolResult}`,
        ),
      );
    }
  } finally {
    cts.dispose();
  }

  return lastText;
}
