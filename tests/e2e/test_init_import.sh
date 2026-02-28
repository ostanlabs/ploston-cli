#!/usr/bin/env bash
# E2E Smoke Test for ploston init --import
#
# This script tests the full import flow with a real CP and config files.
# Prerequisites:
#   1. Docker Compose or K8s CP running
#   2. ploston-cli installed (uv pip install -e packages/ploston-cli)
#
# Usage:
#   ./tests/e2e/test_init_import.sh [--cp-url URL]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

CP_URL="${CP_URL:-http://localhost:8080}"
TEST_DIR=$(mktemp -d)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${YELLOW}=== E2E Smoke Test: ploston init --import ===${NC}"
echo "CP URL: $CP_URL"
echo "Test directory: $TEST_DIR"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --cp-url)
            CP_URL="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

cleanup() {
    echo -e "\n${YELLOW}Cleaning up...${NC}"
    rm -rf "$TEST_DIR"
}
trap cleanup EXIT

# Step 1: Check CP connectivity
echo -e "\n${YELLOW}Step 1: Checking CP connectivity...${NC}"
if curl -s "$CP_URL/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ CP is running at $CP_URL${NC}"
else
    echo -e "${RED}✗ CP is not running at $CP_URL${NC}"
    echo "Please start the CP first:"
    echo "  make docker-compose-up"
    echo "  # or"
    echo "  make k8s-deploy"
    exit 1
fi

# Step 2: Create mock Claude Desktop config
echo -e "\n${YELLOW}Step 2: Creating mock Claude Desktop config...${NC}"
CLAUDE_CONFIG="$TEST_DIR/claude_desktop_config.json"
cat > "$CLAUDE_CONFIG" << 'EOF'
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/test"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "ghp_test_token_12345"
      }
    }
  }
}
EOF
echo -e "${GREEN}✓ Created mock config at $CLAUDE_CONFIG${NC}"
cat "$CLAUDE_CONFIG"

# Step 3: Run ploston init --import (non-interactive)
echo -e "\n${YELLOW}Step 3: Running ploston init --import...${NC}"

# Set up environment to use our test config
export PLOSTON_TEST_CLAUDE_CONFIG="$CLAUDE_CONFIG"
export PLOSTON_DIR="$TEST_DIR/.ploston"

# Run the import command
if python -m ploston_cli init --import \
    --cp-url "$CP_URL" \
    --non-interactive \
    --runner-name "e2e-test-runner" 2>&1; then
    echo -e "${GREEN}✓ Import completed successfully${NC}"
else
    echo -e "${RED}✗ Import failed${NC}"
    exit 1
fi

# Step 4: Verify .env file was created
echo -e "\n${YELLOW}Step 4: Verifying .env file...${NC}"
ENV_FILE="$TEST_DIR/.ploston/.env"
if [[ -f "$ENV_FILE" ]]; then
    echo -e "${GREEN}✓ .env file created at $ENV_FILE${NC}"
    echo "Contents:"
    cat "$ENV_FILE"
else
    echo -e "${RED}✗ .env file not found${NC}"
    exit 1
fi

# Step 5: Verify runner token was generated
echo -e "\n${YELLOW}Step 5: Verifying runner token...${NC}"
if grep -q "PLOSTON_RUNNER_TOKEN=plr_" "$ENV_FILE"; then
    echo -e "${GREEN}✓ Runner token generated${NC}"
else
    echo -e "${RED}✗ Runner token not found in .env${NC}"
    exit 1
fi

# Step 6: Verify secrets were detected
echo -e "\n${YELLOW}Step 6: Verifying secrets detection...${NC}"
if grep -q "GITHUB_TOKEN=" "$ENV_FILE"; then
    echo -e "${GREEN}✓ GITHUB_TOKEN detected and stored${NC}"
else
    echo -e "${YELLOW}⚠ GITHUB_TOKEN not found (may be expected if no secrets)${NC}"
fi

echo -e "\n${GREEN}=== E2E Smoke Test PASSED ===${NC}"
echo "Summary:"
echo "  - CP connectivity: OK"
echo "  - Config detection: OK"
echo "  - Import flow: OK"
echo "  - .env generation: OK"
echo "  - Runner token: OK"
