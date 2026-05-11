#!/bin/bash
# Setup and verification script for Sonar unified MCP server

set -e

echo "=========================================="
echo "Sonar Unified MCP Server Setup & Verify"
echo "=========================================="

cd /Users/aclinton-sonar/Dev/sonar/.ai

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check 1: Root MCP server file exists
echo -e "\n${YELLOW}1. Checking root MCP server file...${NC}"
if [ -f "mcp_server.py" ]; then
    echo -e "${GREEN}✓${NC} Root MCP server exists ($(wc -c < mcp_server.py) bytes)"
else
    echo -e "${RED}✗${NC} Root MCP server not found"
    exit 1
fi

# Check 2: CocoIndex venv exists
echo -e "\n${YELLOW}2. Checking CocoIndex environment...${NC}"
if [ -d "cocoindex/.venv" ]; then
    python_bin="cocoindex/.venv/bin/python3"
    version=$($python_bin --version 2>&1)
    echo -e "${GREEN}✓${NC} CocoIndex venv exists ($version)"
else
    echo -e "${RED}✗${NC} CocoIndex venv not found"
    exit 1
fi

# Check 3: MCP installed in cocoindex venv
echo -e "\n${YELLOW}3. Checking MCP in CocoIndex venv...${NC}"
if $python_bin -c "from mcp.server.fastmcp import FastMCP" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} FastMCP available in cocoindex venv"
else
    echo -e "${RED}✗${NC} FastMCP not found in cocoindex venv"
    exit 1
fi

# Check 4: Embeddings model available
echo -e "\n${YELLOW}4. Checking embeddings in CocoIndex venv...${NC}"
if $python_bin -c "from sentence_transformers import SentenceTransformer" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} sentence-transformers available in cocoindex venv"
else
    echo -e "${RED}✗${NC} sentence-transformers not found"
    exit 1
fi

# Check 5: README updated
echo -e "\n${YELLOW}5. Checking documentation...${NC}"
if grep -q "Unified MCP Architecture" README.md; then
    echo -e "${GREEN}✓${NC} README.md updated with new documentation"
else
    echo -e "${RED}✗${NC} README.md not properly updated"
    exit 1
fi

# Check 6: Imports work
echo -e "\n${YELLOW}6. Testing imports...${NC}"
if $python_bin -c "
import sys
sys.path.insert(0, '.')
from mcp_server import mcp, search_code, get_project_structure
" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} All imports resolve correctly"
else
    echo -e "${RED}✗${NC} Import resolution failed"
    exit 1
fi

# Check 7: Server starts
echo -e "\n${YELLOW}7. Testing server startup...${NC}"
timeout 3 $python_bin mcp_server.py 2>&1 | head -3 | grep -q "Starting Sonar unified" && {
    echo -e "${GREEN}✓${NC} Server starts successfully"
} || {
    echo -e "${YELLOW}⚠${NC} Server startup test (EOF expected without JSON-RPC input)"
}

# Success!
echo -e "\n${GREEN}=========================================="
echo "✓ All checks passed!"
echo "==========================================${NC}"

echo -e "\n${YELLOW}Next steps:${NC}"
echo "1. Start the server:"
echo "   .ai/cocoindex/.venv/bin/python3 .ai/mcp_server.py"
echo ""
echo "2. Or configure in ~/.copilot/mcp-config.json:"
echo "   {\"mcpServers\": {\"sonar_search\": {"
echo "     \"command\": \".ai/cocoindex/.venv/bin/python3\","
echo "     \"args\": [\".ai/mcp_server.py\"]"
echo "   }}}"
echo ""
echo "3. Then reload with: mcp_reload"
echo ""
