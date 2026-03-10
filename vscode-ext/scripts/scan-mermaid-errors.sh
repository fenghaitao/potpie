#!/bin/bash
# Quick shell script to scan for Mermaid errors and generate fix prompt

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(dirname "$SCRIPT_DIR")"
CONTENT_DIR="$WORKSPACE_ROOT/content"

echo "🔍 Scanning for Mermaid errors in: $CONTENT_DIR"
echo ""

# Compile TypeScript first
echo "📦 Compiling TypeScript..."
cd "$WORKSPACE_ROOT"
npm run compile 2>&1 | grep -v "^>" || true
echo ""

# Run the scanner
echo "🚀 Running automated error scanner..."
cd "$SCRIPT_DIR"
npx ts-node autofix-mermaid-errors.ts

echo ""
echo "✅ Scan complete!"
