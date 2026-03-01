#!/bin/bash
# Quick test runner for RAG Comics

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Add app to PYTHONPATH
export PYTHONPATH="$SCRIPT_DIR/../../../calicloud/rag-comics/app:$PYTHONPATH"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "🧪 RAG Comics Test Suite"
echo "========================"
echo ""

# Check venv
if [ ! -d "../../../calicloud/rag-comics/venv" ]; then
    echo "❌ Virtual environment not found. Run: ./calicloud/local-dev/setup.sh rag-comics"
    exit 1
fi

# Activate venv
source ../../../calicloud/rag-comics/venv/bin/activate

# Set PYTHONPATH
export PYTHONPATH="../../../calicloud/rag-comics/app:$PYTHONPATH"
export PYTHONPATH="../../../calicloud/rag-comics/app:$PYTHONPATH"
export PYTHONPATH="../../../calicloud/rag-comics/app:$PYTHONPATH"

# Set PYTHONPATH
export PYTHONPATH="../../../calicloud/rag-comics/app:$PYTHONPATH"

# Check pytest installed
if ! command -v pytest &> /dev/null; then
    echo "📦 Installing pytest..."
    pip install pytest pytest-asyncio pytest-cov pytest-mock responses
fi

# Parse arguments
MODE="${1:-unit}"

case "$MODE" in
    unit)
        echo "Running unit tests (fast, no API calls)..."
        pytest -m unit -v
        ;;
    all)
        echo "Running all tests (skip expensive)..."
        pytest -m "not expensive" -v
        ;;
    expensive)
        echo -e "${YELLOW}⚠️  Running expensive tests (real API calls)${NC}"
        read -p "This will cost money. Continue? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            pytest -m expensive -v
        else
            echo "Cancelled."
            exit 0
        fi
        ;;
    coverage)
        echo "Running tests with coverage..."
        pytest -m "not expensive" --cov=app --cov-report=html --cov-report=term
        echo ""
        echo -e "${GREEN}✅ Coverage report: htmlcov/index.html${NC}"
        ;;
    *)
        echo "Usage: ./run_tests.sh [unit|all|expensive|coverage]"
        echo ""
        echo "  unit      - Run only unit tests (default)"
        echo "  all       - Run all tests except expensive"
        echo "  expensive - Run expensive tests (API calls)"
        echo "  coverage  - Run tests with coverage report"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}✅ Tests completed${NC}"
