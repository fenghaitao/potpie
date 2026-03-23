import * as vscode from 'vscode';
import { HistoryManager } from './historyManager';
import { askQuestion } from './cliManager';

export class SidebarChatProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'potpie.chatView';

  private _view: vscode.WebviewView | undefined;

  /** Buffered to replay once the webview signals 'ready'. */
  private _pendingRepo: { repo: string; branch: string } | undefined;

  /**
   * @param _extensionUri  Extension root URI (for loading webview resources)
   * @param _getRepoDir    Returns the potpie repo dir (where venv lives)
   * @param _getProjectId  Returns the currently selected project ID
   * @param _history       Shared HistoryManager instance
   */
  constructor(
    private readonly _extensionUri: vscode.Uri,
    private readonly _getRepoDir: () => string | undefined,
    private readonly _getProjectId: () => string | undefined,
    private readonly _history: HistoryManager,
  ) {}

  // ── WebviewViewProvider ───────────────────────────────────────────────────

  resolveWebviewView(
    view: vscode.WebviewView,
    _ctx: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ): void {
    this._view = view;

    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this._extensionUri, 'src', 'webview'),
      ],
    };

    view.webview.html = this._buildHtml(view.webview);

    view.webview.onDidReceiveMessage(async (msg) => {
      switch (msg.type) {
        case 'ready':
          // Replay pending repo notification and history after webview reload
          if (this._pendingRepo) {
            const { repo, branch } = this._pendingRepo;
            view.webview.postMessage({ type: 'repoChanged', repo, branch });
            const messages = this._history.getAll(repo, branch);
            view.webview.postMessage({ type: 'restoreHistory', messages });
          }
          break;

        case 'chat': {
          const { question, agent, repo, branch } = msg as {
            question: string;
            agent: string;
            repo: string;
            branch: string;
          };
          const repoDir   = this._getRepoDir();
          const projectId = this._getProjectId();

          if (!repoDir || !projectId) {
            view.webview.postMessage({
              type: 'chatError',
              message: 'No project selected. Please select a project from the Repositories view.',
            });
            break;
          }

          try {
            const prompt = this._history.buildPrompt(repo, branch, question);
            const answer = await askQuestion(repoDir, projectId, prompt, agent);

            // Persist both sides of the turn
            this._history.push(repo, branch, { role: 'user',      content: question });
            this._history.push(repo, branch, { role: 'assistant', content: answer   });

            view.webview.postMessage({ type: 'chatResponse', answer });
          } catch (err) {
            view.webview.postMessage({
              type: 'chatError',
              message: String(err),
            });
          }
          break;
        }

        case 'clearHistory': {
          const { repo, branch } = msg as { repo: string; branch: string };
          if (repo && branch) {
            this._history.clear(repo, branch);
          }
          break;
        }
      }
    });
  }

  // ── Public notify API ─────────────────────────────────────────────────────

  notifyRepoChanged(repo: string, branch: string): void {
    this._pendingRepo = { repo, branch };
    if (this._view) {
      this._view.webview.postMessage({ type: 'repoChanged', repo, branch });
      // Replay history so the chat pane shows previous turns after a project switch
      const messages = this._history.getAll(repo, branch);
      this._view.webview.postMessage({ type: 'restoreHistory', messages });
    }
  }

  clearHistory(repo: string, branch: string): void {
    this._history.clear(repo, branch);
    this._view?.webview.postMessage({ type: 'restoreHistory', messages: [] });
  }

  // ── HTML builder ──────────────────────────────────────────────────────────

  private _buildHtml(webview: vscode.Webview): string {
    const dir    = vscode.Uri.joinPath(this._extensionUri, 'src', 'webview');
    const cssUri = webview.asWebviewUri(vscode.Uri.joinPath(dir, 'style.css'));
    const jsUri  = webview.asWebviewUri(vscode.Uri.joinPath(dir, 'chatSidebar.js'));
    const nonce  = _nonce();
    const csp    = webview.cspSource;

    return /* html */`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none';
             style-src ${csp};
             script-src 'nonce-${nonce}';
             img-src ${csp} data:;
             font-src ${csp};">
  <link rel="stylesheet" href="${cssUri}"/>
  <title>Potpie Chat</title>
</head>
<body class="sidebar-body chat-sidebar-body">

  <!-- Chat history scrollable area -->
  <div id="chat-history" class="chat-history" aria-live="polite" aria-label="Chat history">
    <div class="chat-message assistant">
      <span class="chat-role">Potpie</span>
      <span class="chat-text">Hello! Select a repository above and ask me anything about the codebase.</span>
    </div>
  </div>

  <!-- Typing indicator (hidden by default) -->
  <div id="chat-thinking" class="chat-thinking" style="display:none;" aria-live="polite">
    <span class="chat-role">Potpie</span>
    <span class="chat-dots"><span>.</span><span>.</span><span>.</span></span>
  </div>

  <!-- Agent selector + Clear -->
  <div class="chat-toolbar">
    <label for="agent-select" class="toolbar-label">Agent</label>
    <select id="agent-select" class="toolbar-select">
      <option value="codebase_qna_agent">Codebase Q&amp;A</option>
      <option value="code_generation_agent">Code Generation</option>
      <option value="debugging_agent">Debugging</option>
    </select>
    <button id="chat-clear" class="btn-secondary" title="Clear conversation" aria-label="Clear chat history">Clear</button>
  </div>

  <!-- Input bar -->
  <div class="chat-input-row">
    <textarea
      id="chat-input"
      class="chat-input"
      placeholder="Ask about the codebase… (Ctrl+Enter to send)"
      rows="3"
      aria-label="Chat prompt"
    ></textarea>
    <button id="chat-send" class="btn-primary" aria-label="Send message">Send</button>
  </div>

  <script nonce="${nonce}" src="${jsUri}"></script>
</body>
</html>`;
  }
}

function _nonce(): string {
  const c = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let n = '';
  for (let i = 0; i < 32; i++) { n += c[Math.floor(Math.random() * c.length)]; }
  return n;
}
