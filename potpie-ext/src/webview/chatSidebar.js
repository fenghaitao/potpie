// @ts-check
// Chat sidebar script — runs inside the VS Code webview (browser context).
(function () {
  'use strict';

  // @ts-ignore
  const vscode = acquireVsCodeApi();

  // Persist repo/branch across webview reloads
  const state = vscode.getState() || { currentRepo: null, currentBranch: null };

  // ── Element refs ──────────────────────────────────────────────────────────
  const chatHistory  = /** @type {HTMLElement} */         (document.getElementById('chat-history'));
  const chatInput    = /** @type {HTMLTextAreaElement} */ (document.getElementById('chat-input'));
  const chatSendBtn  = /** @type {HTMLButtonElement} */   (document.getElementById('chat-send'));
  const clearChatBtn = /** @type {HTMLButtonElement} */   (document.getElementById('chat-clear'));
  const agentSelect  = /** @type {HTMLSelectElement} */   (document.getElementById('agent-select'));
  const thinkingEl   = /** @type {HTMLElement} */         (document.getElementById('chat-thinking'));

  // ── State ─────────────────────────────────────────────────────────────────
  let _thinking = false;

  // ── Minimal markdown → HTML renderer ─────────────────────────────────────
  // Handles: fenced code blocks, inline code, headers, bold, italic,
  // unordered lists, ordered lists, horizontal rules, links, paragraphs.

  /** @param {string} text */
  function renderMarkdown(text) {
    // 1. Fenced code blocks ```lang\n...\n```
    text = text.replace(/```([^\n]*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const cls = lang ? ` class="language-${escapeHtml(lang.trim())}"` : '';
      return `<pre><code${cls}>${escapeHtml(code)}</code></pre>`;
    });

    // 2. Split into block-level pieces (preserve <pre> blocks)
    const blocks = [];
    let rest = text;
    const preRe = /(<pre>[\s\S]*?<\/pre>)/g;
    let last = 0, m;
    while ((m = preRe.exec(rest)) !== null) {
      if (m.index > last) { blocks.push({ type: 'text', src: rest.slice(last, m.index) }); }
      blocks.push({ type: 'pre', html: m[1] });
      last = preRe.lastIndex;
    }
    if (last < rest.length) { blocks.push({ type: 'text', src: rest.slice(last) }); }

    const html = blocks.map(b => {
      if (b.type === 'pre') { return b.html; }
      return processTextBlock(b.src);
    }).join('');

    return html;
  }

  /** @param {string} text */
  function processTextBlock(text) {
    const lines = text.split('\n');
    let out = '';
    let inUl = false, inOl = false;

    const closeList = () => {
      if (inUl) { out += '</ul>'; inUl = false; }
      if (inOl) { out += '</ol>'; inOl = false; }
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Horizontal rule
      if (/^[-*_]{3,}\s*$/.test(line)) { closeList(); out += '<hr/>'; continue; }

      // ATX headers
      const hMatch = line.match(/^(#{1,6})\s+(.*)/);
      if (hMatch) {
        closeList();
        const level = hMatch[1].length;
        out += `<h${level}>${inlineMarkdown(hMatch[2])}</h${level}>`;
        continue;
      }

      // Unordered list item
      const ulMatch = line.match(/^[ \t]*[-*+]\s+(.*)/);
      if (ulMatch) {
        if (inOl) { out += '</ol>'; inOl = false; }
        if (!inUl) { out += '<ul>'; inUl = true; }
        out += `<li>${inlineMarkdown(ulMatch[1])}</li>`;
        continue;
      }

      // Ordered list item
      const olMatch = line.match(/^[ \t]*\d+\.\s+(.*)/);
      if (olMatch) {
        if (inUl) { out += '</ul>'; inUl = false; }
        if (!inOl) { out += '<ol>'; inOl = true; }
        out += `<li>${inlineMarkdown(olMatch[1])}</li>`;
        continue;
      }

      closeList();

      // Blank line → paragraph break
      if (line.trim() === '') { out += '<p></p>'; continue; }

      out += `<span class="md-line">${inlineMarkdown(line)}</span><br/>`;
    }

    closeList();
    return out;
  }

  /** @param {string} text */
  function inlineMarkdown(text) {
    // First, escape all HTML so arbitrary tags cannot be injected.
    text = escapeHtml(text);

    // Inline code (must come before bold/italic to avoid false positives)
    // At this point, the content is already escaped, so we do not escape again.
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold+italic ***text***
    text = text.replace(/\*{3}(.+?)\*{3}/g, '<strong><em>$1</em></strong>');
    // Bold **text** or __text__
    text = text.replace(/\*{2}(.+?)\*{2}/g, '<strong>$1</strong>');
    text = text.replace(/_{2}(.+?)_{2}/g, '<strong>$1</strong>');
    // Italic *text* or _text_
    text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
    text = text.replace(/_(.+?)_/g, '<em>$1</em>');

    // Links [text](url)
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
      // Only allow http/https URLs in rendered links
      const safeUrl = /^https?:\/\//.test(url) ? url : '#';
      const href = escapeHtml(safeUrl);
      return `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    });

    return text;
  }

  /** @param {string} str */
  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * @param {'user'|'assistant'|'error'} role
   * @param {string} text
   */
  function appendMessage(role, text) {
    const div = document.createElement('div');
    div.className = 'chat-message ' + (role === 'error' ? 'error' : role);

    const roleLabel = role === 'user' ? 'You' : role === 'error' ? 'Error' : 'Potpie';

    let inner;
    if (role === 'assistant') {
      // Render markdown for assistant responses
      const mdDiv = document.createElement('div');
      mdDiv.className = 'chat-text md';
      mdDiv.innerHTML = renderMarkdown(text);
      const roleEl = document.createElement('span');
      roleEl.className = 'chat-role';
      roleEl.textContent = roleLabel;
      div.appendChild(roleEl);
      div.appendChild(mdDiv);
    } else {
      div.innerHTML =
        '<span class="chat-role">' + roleLabel + '</span>' +
        '<span class="chat-text">' + escapeHtml(text) + '</span>';
    }

    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
  }

  function setThinking(on) {
    _thinking = on;
    chatSendBtn.disabled = on;
    chatInput.disabled = on;
    thinkingEl.style.display = on ? 'flex' : 'none';
    if (on) { chatHistory.scrollTop = chatHistory.scrollHeight; }
  }

  function repoLabel() {
    if (state.currentRepo && state.currentBranch) {
      return state.currentRepo + ' @ ' + state.currentBranch;
    }
    return null;
  }

  // ── Send ──────────────────────────────────────────────────────────────────

  function handleSend() {
    if (_thinking) { return; }
    const question = chatInput.value.trim();
    if (!question) { return; }

    if (!state.currentRepo || !state.currentBranch) {
      appendMessage('error', 'No project selected. Click a project in the Repositories view first.');
      return;
    }

    const agent = agentSelect.value;

    appendMessage('user', question);
    chatInput.value = '';
    setThinking(true);

    vscode.postMessage({
      type: 'chat',
      question,
      agent,
      repo: state.currentRepo,
      branch: state.currentBranch,
    });
  }

  chatSendBtn.addEventListener('click', handleSend);

  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
  });

  // ── Clear ─────────────────────────────────────────────────────────────────

  clearChatBtn.addEventListener('click', () => {
    chatHistory.innerHTML = '';
    const greeting = document.createElement('div');
    greeting.className = 'chat-message assistant';
    greeting.innerHTML =
      '<span class="chat-role">Potpie</span>' +
      '<span class="chat-text">Chat cleared. Ask me anything about the codebase.</span>';
    chatHistory.appendChild(greeting);

    vscode.postMessage({
      type: 'clearHistory',
      repo: state.currentRepo,
      branch: state.currentBranch,
    });
  });

  // ── Extension → Webview messages ─────────────────────────────────────────

  window.addEventListener('message', (event) => {
    const msg = event.data;

    switch (msg.type) {
      case 'repoChanged': {
        state.currentRepo   = msg.repo;
        state.currentBranch = msg.branch;
        vscode.setState(state);

        // Announce new project in chat without clearing history
        const label = repoLabel();
        if (label) {
          const note = document.createElement('div');
          note.className = 'chat-divider';
          note.textContent = '\u2500 ' + label + ' \u2500';
          chatHistory.appendChild(note);
          chatHistory.scrollTop = chatHistory.scrollHeight;
        }
        break;
      }

      case 'chatResponse': {
        setThinking(false);
        appendMessage('assistant', msg.answer);
        break;
      }

      case 'chatError': {
        setThinking(false);
        appendMessage('error', msg.message);
        break;
      }

      case 'restoreHistory': {
        // Replay persisted history after webview reload
        chatHistory.innerHTML = '';
        const welcome = document.createElement('div');
        welcome.className = 'chat-message assistant';
        welcome.innerHTML =
          '<span class="chat-role">Potpie</span>' +
          '<span class="chat-text">Hello! Select a repository above and ask me anything about the codebase.</span>';
        chatHistory.appendChild(welcome);

        /** @type {Array<{role:string, content:string}>} */
        const messages = msg.messages || [];
        for (const m of messages) {
          appendMessage(m.role === 'user' ? 'user' : 'assistant', m.content);
        }
        break;
      }
    }
  });

  // ── Init ──────────────────────────────────────────────────────────────────

  vscode.postMessage({ type: 'ready' });
})();
