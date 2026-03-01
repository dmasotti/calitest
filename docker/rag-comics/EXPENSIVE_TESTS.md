# Running Expensive Tests

These tests make real API calls and cost money. Run them manually only when needed.

## Prerequisites

1. Set API keys in environment:
```bash
export GEMINI_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

2. Have a test CBZ file ready (3-5 pages recommended)

## Performance Benchmarks

### 1. Real Extraction Performance
Tests extraction speed with real API calls.

**Cost**: ~$0.001 per run (5 pages with Gemini)

```bash
cd /Users/macbookpro/Coding/calibre-plg/tests/docker/rag-comics
export PYTHONPATH="../../../calicloud/rag-comics/app:$PYTHONPATH"

../../../calicloud/rag-comics/venv/bin/python -m pytest \
  test_performance.py::TestPerformanceBenchmarks::test_real_extraction_performance \
  -v -s --no-skip
```

**Expected output**:
```
⏱️  Performance Metrics:
   Total time: 12.5s
   Pages processed: 5
   Pages/second: 0.40
   Tokens used: 15000
   Cost: $0.0012
```

### 2. Concurrent Load Performance
Tests performance under concurrent load (3 parallel extractions).

**Cost**: ~$0.003 per run (3x3 pages with Gemini)

```bash
../../../calicloud/rag-comics/venv/bin/python -m pytest \
  test_performance.py::TestPerformanceBenchmarks::test_concurrent_load_performance \
  -v -s --no-skip
```

**Expected output**:
```
🔄 Running 3 concurrent extractions...
⏱️  Concurrent Performance:
   Total wall time: 15.2s
   Average task time: 12.1s
   Total pages: 9
   Total cost: $0.0027
   Throughput: 0.59 pages/sec
   Speedup: 2.39x
```

### 3. Memory Usage Over Time
Tests for memory leaks (5 consecutive extractions).

**Cost**: ~$0.005 per run (5x3 pages with Gemini)

```bash
../../../calicloud/rag-comics/venv/bin/python -m pytest \
  test_performance.py::TestPerformanceBenchmarks::test_memory_usage_over_time \
  -v -s --no-skip
```

**Expected output**:
```
💾 Memory Usage Test:
   Baseline: 245.3 MB
   After run 1: 267.8 MB (+22.5 MB)
   After run 2: 268.1 MB (+22.8 MB)
   After run 3: 268.3 MB (+23.0 MB)
   After run 4: 268.5 MB (+23.2 MB)
   After run 5: 268.7 MB (+23.4 MB)
   
   Final: 268.7 MB
   Total growth: 23.4 MB (9.5%)
```

## Real API Extraction Tests

### Gemini Vision API
**Cost**: ~$0.0006 per run (3 pages)

```bash
../../../calicloud/rag-comics/venv/bin/python -m pytest \
  test_comic_extractor.py::TestRealAPIExtraction::test_extract_with_real_gemini_api \
  -v -s --no-skip
```

### OpenAI Vision API
**Cost**: ~$0.04 per run (3 pages)

```bash
../../../calicloud/rag-comics/venv/bin/python -m pytest \
  test_comic_extractor.py::TestRealAPIExtraction::test_extract_with_real_openai_api \
  -v -s --no-skip
```

```bash
export DEEPSEEK_API_KEY="your-key"

../../../calicloud/rag-comics/venv/bin/python -m pytest \
  test_comic_extractor.py::TestRealAPIExtraction::test_extract_with_real_deepseek_api \
  -v -s --no-skip
```

### Anthropic Vision API
**Cost**: ~$0.02 per run (3 pages)

```bash
export ANTHROPIC_API_KEY="your-key"

../../../calicloud/rag-comics/venv/bin/python -m pytest \
  test_comic_extractor.py::TestRealAPIExtraction::test_extract_with_real_anthropic_api \
  -v -s --no-skip
```

### Qwen Vision API
**Cost**: ~$0.001 per run (3 pages)

```bash
export QWEN_API_KEY="your-key"

../../../calicloud/rag-comics/venv/bin/python -m pytest \
  test_comic_extractor.py::TestRealAPIExtraction::test_extract_with_real_qwen_api \
  -v -s --no-skip
```

## Running All Expensive Tests

**Total cost**: ~$0.11 (all providers)

```bash
../../../calicloud/rag-comics/venv/bin/python -m pytest \
  -m expensive \
  -v -s --no-skip
```

## Notes

- Use `--no-skip` flag to override `@pytest.mark.skip` decorators
- Tests are skipped by default to prevent accidental API charges
- Use small CBZ files (3-5 pages) to minimize costs
- Monitor costs in your API dashboards
- Set required API keys before running tests:
  - `GEMINI_API_KEY` - For Gemini tests
  - `OPENAI_API_KEY` - For OpenAI tests
  - `ANTHROPIC_API_KEY` - For Anthropic tests
  - `QWEN_API_KEY` - For Qwen tests
- **DeepSeek does not support Vision API** (text-only)
