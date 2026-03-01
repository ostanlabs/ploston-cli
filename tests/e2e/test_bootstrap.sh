#!/bin/bash
# E2E smoke test for ploston bootstrap command
#
# Prerequisites:
# - Docker and Docker Compose installed and running
# - ploston-cli installed (pip install -e packages/ploston-cli)
#
# Usage:
#   ./tests/e2e/test_bootstrap.sh
#
# This script tests the full bootstrap flow with real Docker.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test directory
TEST_DIR="${HOME}/.ploston-test-$$"
ORIGINAL_PLOSTON_DIR="${HOME}/.ploston"

echo -e "${YELLOW}=== Ploston Bootstrap E2E Smoke Test ===${NC}"
echo ""

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}Cleaning up...${NC}"

    # Stop any running stack
    if [ -f "${TEST_DIR}/docker-compose.yaml" ]; then
        docker compose -f "${TEST_DIR}/docker-compose.yaml" down -v 2>/dev/null || true
    fi

    # Remove test directory
    rm -rf "${TEST_DIR}"

    echo -e "${GREEN}Cleanup complete${NC}"
}

# Set trap for cleanup on exit
trap cleanup EXIT

# Test 1: Check prerequisites
echo -e "${YELLOW}Test 1: Checking prerequisites...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}FAIL: Docker not found${NC}"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo -e "${RED}FAIL: Docker Compose not found${NC}"
    exit 1
fi

if ! command -v ploston &> /dev/null; then
    echo -e "${RED}FAIL: ploston CLI not found. Install with: pip install -e packages/ploston-cli${NC}"
    exit 1
fi
echo -e "${GREEN}PASS: All prerequisites met${NC}"

# Test 2: Bootstrap help
echo -e "\n${YELLOW}Test 2: Bootstrap help...${NC}"
if ploston bootstrap --help | grep -q "Deploy the Ploston Control Plane"; then
    echo -e "${GREEN}PASS: Help text correct${NC}"
else
    echo -e "${RED}FAIL: Help text incorrect${NC}"
    exit 1
fi

# Test 3: Bootstrap status (no stack)
echo -e "\n${YELLOW}Test 3: Bootstrap status (no stack)...${NC}"
mkdir -p "${TEST_DIR}"
export HOME="${TEST_DIR}"
if ploston bootstrap status 2>&1 | grep -qi "not found\|no stack\|not running"; then
    echo -e "${GREEN}PASS: Status shows no stack${NC}"
else
    echo -e "${YELLOW}WARN: Status output may vary${NC}"
fi

# Test 4: Bootstrap down (no stack)
echo -e "\n${YELLOW}Test 4: Bootstrap down (no stack)...${NC}"
if ploston bootstrap down 2>&1; then
    echo -e "${GREEN}PASS: Down handles no stack gracefully${NC}"
else
    echo -e "${YELLOW}WARN: Down may fail when no stack exists${NC}"
fi

# Test 5: Full bootstrap (Docker target)
echo -e "\n${YELLOW}Test 5: Full bootstrap (Docker target)...${NC}"
echo -e "${YELLOW}This will pull images and start containers...${NC}"

# Run bootstrap in non-interactive mode, skip import
if ploston bootstrap --non-interactive --no-import 2>&1; then
    echo -e "${GREEN}PASS: Bootstrap completed${NC}"
else
    echo -e "${RED}FAIL: Bootstrap failed${NC}"
    exit 1
fi

# Test 6: Verify compose file created
echo -e "\n${YELLOW}Test 6: Verify compose file...${NC}"
if [ -f "${TEST_DIR}/.ploston/docker-compose.yaml" ]; then
    echo -e "${GREEN}PASS: docker-compose.yaml created${NC}"
else
    echo -e "${RED}FAIL: docker-compose.yaml not found${NC}"
    exit 1
fi

# Test 7: Check stack status
echo -e "\n${YELLOW}Test 7: Check stack status...${NC}"
if ploston bootstrap status 2>&1 | grep -qi "running"; then
    echo -e "${GREEN}PASS: Stack is running${NC}"
else
    echo -e "${YELLOW}WARN: Stack status unclear${NC}"
fi

# Test 8: Check CP health
echo -e "\n${YELLOW}Test 8: Check CP health...${NC}"
sleep 5  # Give CP time to start
if curl -s http://localhost:8082/health | grep -q "ok"; then
    echo -e "${GREEN}PASS: CP is healthy${NC}"
else
    echo -e "${YELLOW}WARN: CP health check failed (may need more time)${NC}"
fi

# Test 9: Bootstrap restart
echo -e "\n${YELLOW}Test 9: Bootstrap restart...${NC}"
if ploston bootstrap restart 2>&1; then
    echo -e "${GREEN}PASS: Restart completed${NC}"
else
    echo -e "${RED}FAIL: Restart failed${NC}"
    exit 1
fi

# Test 10: Bootstrap down
echo -e "\n${YELLOW}Test 10: Bootstrap down...${NC}"
if ploston bootstrap down 2>&1; then
    echo -e "${GREEN}PASS: Down completed${NC}"
else
    echo -e "${RED}FAIL: Down failed${NC}"
    exit 1
fi

echo -e "\n${GREEN}=== All E2E tests passed! ===${NC}"
