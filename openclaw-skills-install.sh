#!/bin/bash
set -e

# Determine the script's directory (handles being run from any location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SOURCE="$SCRIPT_DIR/skills/notion-rag-query.md"
SKILL_DIR="$HOME/.openclaw/workspace/skills/notion-rag-query"
SKILL_DEST="$SKILL_DIR/SKILL.md"

echo "Installing Notion RAG Query skill..."

# Check if source skill file exists
if [[ ! -f "$SKILL_SOURCE" ]]; then
    echo "Error: Skill file not found at $SKILL_SOURCE"
    exit 1
fi

# Create skill directory and copy file
mkdir -p "$SKILL_DIR"
cp "$SKILL_SOURCE" "$SKILL_DEST"

echo ""
echo "✓ Installation successful!"
echo ""
echo "  Installed to: $SKILL_DEST"
echo ""
echo "Next steps:"
echo "  1. Start the RAG API server: uv run notion-rag serve"
echo "  2. 'Notion에서 찾아줘' 키워드로 질문하면 자동으로 스킬이 트리거됩니다"
echo ""
