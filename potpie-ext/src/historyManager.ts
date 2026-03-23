/**
 * historyManager.ts
 *
 * Per-project conversation history for the chat sidebar.
 *
 * History is keyed by  "<repoName>:<branchName>"  so switching projects
 * gives each repo/branch its own independent conversation.
 *
 * The number of turns kept is controlled by the VS Code setting
 * `potpie.chat.historyLength` (default: 5).  Only the latest N complete
 * turns (one user message + one assistant message = one turn) are sent to
 * the CLI; older turns are retained internally so a "clear" action can
 * start fresh while keeping the ring-buffer behaviour.
 */
import * as vscode from 'vscode';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

const HISTORY_SETTING = 'potpie.chat.historyLength';
const DEFAULT_HISTORY_LENGTH = 5;

function historyLength(): number {
  const cfg = vscode.workspace.getConfiguration();
  const v = cfg.get<number>(HISTORY_SETTING, DEFAULT_HISTORY_LENGTH);
  return Math.max(1, v);
}

export class HistoryManager {
  /** Full (un-truncated) history per project key. */
  private readonly _store = new Map<string, ChatMessage[]>();

  private static _key(repo: string, branch: string): string {
    return `${repo}:${branch}`;
  }

  // ── Public API ────────────────────────────────────────────────────────────

  /** Append a single message to the project's history. */
  push(repo: string, branch: string, msg: ChatMessage): void {
    const key = HistoryManager._key(repo, branch);
    if (!this._store.has(key)) {
      this._store.set(key, []);
    }
    this._store.get(key)!.push(msg);
  }

  /**
   * Return the last N turns (N = `potpie.chat.historyLength`) for a project.
   *
   * A "turn" is one user message + one assistant message (2 entries).
   * Messages are always returned in chronological order.
   */
  getWindow(repo: string, branch: string): ChatMessage[] {
    const all = this._store.get(HistoryManager._key(repo, branch)) ?? [];
    const n = historyLength() * 2; // each turn = 2 messages
    return all.slice(-n);
  }

  /** Return the full (untruncated) history for a project. */
  getAll(repo: string, branch: string): ChatMessage[] {
    return this._store.get(HistoryManager._key(repo, branch)) ?? [];
  }

  /** Wipe the conversation for one project. */
  clear(repo: string, branch: string): void {
    this._store.delete(HistoryManager._key(repo, branch));
  }

  // ── Prompt construction ───────────────────────────────────────────────────

  /**
   * Build the final prompt string to pass to `potpie_cli.py ask`.
   *
   * If there is history to include the prompt is prefixed with a
   * conversation block:
   *
   *   Conversation History (last N turns):
   *   User: ...
   *   Assistant: ...
   *
   *   Current Question:
   *   <question>
   *
   * If there is no prior history, just the bare question is returned so the
   * CLI output stays clean.
   */
  buildPrompt(repo: string, branch: string, question: string): string {
    const window = this.getWindow(repo, branch);

    // No history yet — plain question
    if (window.length === 0) {
      return question;
    }

    const lines: string[] = [
      `Conversation History (last ${historyLength()} turns):`,
    ];
    for (const msg of window) {
      lines.push(
        `${msg.role === 'user' ? 'User' : 'Assistant'}: ${msg.content}`,
      );
    }
    lines.push('', 'Current Question:', question);
    return lines.join('\n');
  }
}
