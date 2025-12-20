# CaliWeb Test Suite

Comprehensive test suite for CaliWeb OPDS and Sync API functionality.

## 📋 Test Suites

### 1. OPDS Comprehensive Test (`tests/opds/opds_comprehensive_test.sh`)

Tests all OPDS catalog functionality:

**Coverage:**
- ✅ Root navigation feed
- ✅ All books listing
- ✅ Search functionality
- ✅ Recent additions
- ✅ Browse by Author/Series/Tags
- ✅ Authentication & Security
- ✅ Pagination
- ✅ OPDS metadata validation
- ✅ XML structure validation

**Tests:** ~25 test cases

### 2. Sync API Comprehensive Test (`tests/server/sync_comprehensive_test.sh`)

Tests complete Sync API lifecycle:

**Coverage:**
- ✅ Discovery & Authentication
- ✅ Library management
- ✅ Pull sync (server → client)
- ✅ Push sync (client → server)
- ✅ Create/Update/Delete operations
- ✅ Search & filtering
- ✅ Metadata operations
- ✅ Protocol compliance (triplet matching)
- ✅ Idempotency

**Tests:** ~13 test cases

### 3. Legacy Book Creation Test (`tests/server/test_legacy_book.sh`)

Tests backward compatibility:

**Coverage:**
- ✅ Legacy sync endpoint
- ✅ Book creation without 'id' field
- ✅ Compatibility with old clients

**Tests:** ~3 test cases

### 4. Plugin Tests (`tests/plugin/`)

Tests Calibre plugin sync_calimob:

**Coverage:**
- ✅ Integration tests (with calibre-debug)
- ✅ Scenario tests (standalone)
- ✅ Protocol compliance
- ✅ Payload validation
- ✅ Hash calculation
- ✅ Client ID handling

**Tests:** 11 test cases

## 🚀 Usage

### Quick Start - Run All Tests

```bash
# Set environment variables
export DISCOVERY_URL="https://your-server.com"
export TEST_USER_EMAIL="user@example.com"
export TEST_USER_PASSWORD="your-password"

# Run all test suites
./tests/run_all_tests.sh
```

### Run Individual Test Suites

**OPDS Tests:**
```bash
HOST="https://your-server.com" \
USER="user@example.com" \
PASS="your-password" \
./tests/opds/opds_comprehensive_test.sh
```

**Sync API Tests:**
```bash
DISCOVERY_URL="https://your-server.com" \
TEST_USER_EMAIL="user@example.com" \
TEST_USER_PASSWORD="your-password" \
./tests/server/sync_comprehensive_test.sh
```

**Legacy Tests:**
```bash
DISCOVERY_URL="https://your-server.com" \
TEST_USER_EMAIL="user@example.com" \
TEST_USER_PASSWORD="your-password" \
./tests/server/test_legacy_book.sh
```

**Plugin Tests:**
```bash
# Integration tests (requires Calibre)
/Applications/calibre.app/Contents/MacOS/calibre-debug -e tests/plugin/test_plugin_integration.py

# Scenario tests (no Calibre required)
python tests/plugin/test_sync_scenarios.py
```

## ⚙️ Configuration

### Using Environment File

Create `tests/server/.env`:

```bash
DISCOVERY_URL="https://your-server.com"
TEST_USER_EMAIL="user@example.com"
TEST_USER_PASSWORD="your-password"
```

Then run:
```bash
./tests/run_all_tests.sh
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DISCOVERY_URL` | Server base URL | Yes |
| `TEST_USER_EMAIL` | Test user email | Yes |
| `TEST_USER_PASSWORD` | Test user password | Yes |
| `VERBOSE` | Enable verbose output (0/1) | No |

## 📊 Test Output

### Success Output
```
╔════════════════════════════════════════╗
║   All Test Suites Passed! ✓            ║
╚════════════════════════════════════════╝
```

### Individual Test Format
```
✓ Root navigation feed (HTTP 200)
✓ All books listing (HTTP 200)
✓ Search endpoint (HTTP 200)
✗ Some test failed (Expected 200, got 500)
```

### Summary
```
Test Execution Summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total test suites: 3
Passed: 3
```

## 🔍 Debugging Failed Tests

### Enable Verbose Mode
```bash
VERBOSE=1 ./tests/opds/opds_comprehensive_test.sh
```

### Check Individual Test Output
Each test creates temporary files in `/tmp/` with response bodies.

### Common Issues

**401 Unauthorized:**
- Check credentials
- Verify user exists in database
- Check authentication middleware

**404 Not Found:**
- Verify endpoint exists
- Check route configuration
- Ensure migrations are run

**500 Server Error:**
- Check server logs
- Verify database schema
- Check relationship definitions in models

## 🧪 Adding New Tests

### Test Helper Functions

```bash
# Test HTTP endpoint
test_endpoint "Test name" "/endpoint" 200

# Test XML content
test_xml_contains "Test name" "$file" "<pattern>"

# API calls
api_get "/endpoint"
api_post "/endpoint" '{"data":"value"}'
```

### Test Structure

```bash
echo "=== Test Category ==="

log_test "Test description"
TOTAL_TESTS=$((TOTAL_TESTS + 1))

# Test logic here

if [[ success ]]; then
    log_pass "Test passed"
else
    log_fail "Test failed: reason"
fi
```

## 📦 Dependencies

- `bash` (v4.0+)
- `curl`
- `jq` (for JSON parsing)
- `grep`, `sed`, `awk` (standard Unix tools)

### Install Dependencies

**macOS:**
```bash
brew install jq
```

**Ubuntu/Debian:**
```bash
sudo apt-get install jq curl
```

## 🔐 Security Notes

- Never commit `.env` files with real credentials
- Use test accounts, not production accounts
- Test user should have isolated test data
- Clean up test data after runs (tests do this automatically)

## 📝 Test Coverage

| Feature | Coverage | Test Suite |
|---------|----------|------------|
| OPDS Root Feed | ✅ | OPDS Comprehensive |
| OPDS Search | ✅ | OPDS Comprehensive |
| OPDS Navigation | ✅ | OPDS Comprehensive |
| OPDS Authentication | ✅ | OPDS Comprehensive |
| Sync Discovery | ✅ | Sync Comprehensive |
| Sync Authentication | ✅ | Sync Comprehensive |
| Sync Pull | ✅ | Sync Comprehensive |
| Sync Push (Create) | ✅ | Sync Comprehensive |
| Sync Push (Update) | ✅ | Sync Comprehensive |
| Sync Push (Delete) | ✅ | Sync Comprehensive |
| Search & Filter | ✅ | Sync Comprehensive |
| Legacy Compatibility | ✅ | Legacy Tests |
| Protocol Compliance | ✅ | Sync Comprehensive |

## 🚦 CI/CD Integration

### GitHub Actions Example

```yaml
name: Run Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run Test Suite
        env:
          DISCOVERY_URL: ${{ secrets.TEST_SERVER_URL }}
          TEST_USER_EMAIL: ${{ secrets.TEST_USER_EMAIL }}
          TEST_USER_PASSWORD: ${{ secrets.TEST_USER_PASSWORD }}
        run: |
          ./tests/run_all_tests.sh
```

## 📄 License

Same as parent project.
