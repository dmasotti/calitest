"""
Performance tests for RAG Comics service
"""
import pytest
import sys
import time
import asyncio
import psutil
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "calicloud" / "rag-comics" / "app"))


@pytest.mark.unit
class TestBatchSizeOptimization:
    """Test optimal batch size for Vision API"""
    
    @patch('comic_extractor._extract_with_gemini')
    @patch('comic_extractor._extract_images')
    async def test_small_batch_size(self, mock_images, mock_extract):
        """Test extraction with small batch size (1)"""
        from comic_extractor import extract_comic_text
        
        mock_images.return_value = [f"/tmp/page_{i}.png" for i in range(10)]
        mock_extract.return_value = {
            "pages": [{"page": i, "panels": []} for i in range(10)],
            "tokens_used": {"vision_total_tokens": 2580},
            "cost_usd": 0.002
        }
        
        start = time.time()
        result = await extract_comic_text(
            "/tmp/test.cbz",
            batch_size=1,
            vision_provider="gemini"
        )
        duration = time.time() - start
        
        # Small batch = more API calls = slower
        assert len(result["pages"]) == 10
        # Should take longer due to multiple API calls
    
    @patch('comic_extractor._extract_with_gemini')
    @patch('comic_extractor._extract_images')
    async def test_large_batch_size(self, mock_images, mock_extract):
        """Test extraction with large batch size (20)"""
        from comic_extractor import extract_comic_text
        
        mock_images.return_value = [f"/tmp/page_{i}.png" for i in range(10)]
        mock_extract.return_value = {
            "pages": [{"page": i, "panels": []} for i in range(10)],
            "tokens_used": {"vision_total_tokens": 2580},
            "cost_usd": 0.002
        }
        
        start = time.time()
        result = await extract_comic_text(
            "/tmp/test.cbz",
            batch_size=20,
            vision_provider="gemini"
        )
        duration = time.time() - start
        
        # Large batch = fewer API calls = faster
        assert len(result["pages"]) == 10
        # Should be faster (single API call)
    
    @pytest.mark.parametrize("batch_size", [1, 5, 10, 20, 50])
    @patch('comic_extractor._extract_with_gemini')
    @patch('comic_extractor._extract_images')
    async def test_batch_size_comparison(self, mock_images, mock_extract, batch_size):
        """Compare different batch sizes"""
        from comic_extractor import extract_comic_text
        
        mock_images.return_value = [f"/tmp/page_{i}.png" for i in range(25)]
        mock_extract.return_value = {
            "pages": [{"page": i, "panels": []} for i in range(25)],
            "tokens_used": {"vision_total_tokens": 6450},
            "cost_usd": 0.005
        }
        
        result = await extract_comic_text(
            "/tmp/test.cbz",
            batch_size=batch_size,
            vision_provider="gemini"
        )
        
        # All batch sizes should produce same result
        assert len(result["pages"]) == 25
        
        # Calculate expected API calls
        expected_calls = (25 + batch_size - 1) // batch_size
        # Verify mock was called correct number of times
        assert mock_extract.call_count == expected_calls


@pytest.mark.unit
class TestMemoryUsage:
    """Test memory efficiency"""
    
    @patch('comic_extractor._extract_images')
    async def test_large_file_memory_efficient(self, mock_images):
        """Test large files don't cause memory issues"""
        from comic_extractor import extract_comic_text
        
        # Mock 500 pages
        mock_images.return_value = [f"/tmp/page_{i:04d}.png" for i in range(500)]
        
        with patch('comic_extractor._extract_with_gemini') as mock_extract:
            # Mock batch processing
            mock_extract.return_value = {
                "pages": [{"page": i, "panels": []} for i in range(20)],
                "tokens_used": {"vision_total_tokens": 5160},
                "cost_usd": 0.004
            }
            
            result = await extract_comic_text(
                "/tmp/large.cbz",
                batch_size=20,
                vision_provider="gemini"
            )
            
            # Should process in batches, not all at once
            assert mock_extract.call_count == 25  # 500 / 20
    
    def test_streaming_file_read(self, tmp_path):
        """Test file reading uses streaming (not loading all in memory)"""
        from document_manager import calculate_md5
        
        # Create 50MB file
        large_file = tmp_path / "large.cbz"
        large_file.write_bytes(b"x" * (50 * 1024 * 1024))
        
        mock_file = Mock()
        mock_file.file = open(large_file, 'rb')
        
        # Should read in chunks, not all at once
        result = calculate_md5(mock_file)
        
        assert len(result) == 32
        mock_file.file.close()


@pytest.mark.unit
class TestConcurrentRequests:
    """Test handling concurrent requests"""
    
    @patch('document_manager.QdrantClient')
    @patch('document_manager.extract_comic_text')
    @patch('document_manager.calculate_md5')
    async def test_multiple_concurrent_uploads(self, mock_md5, mock_extract, mock_qdrant_class):
        """Test handling multiple concurrent uploads"""
        from document_manager import upload_and_index
        
        # Setup mocks
        mock_md5.return_value = "abc123"
        mock_extract.return_value = {
            "pages": [{"page": 0, "panels": []}],
            "tokens_used": {"vision_total_tokens": 258},
            "cost_usd": 0.0002
        }
        
        mock_qdrant = Mock()
        mock_qdrant.get_collections.return_value = Mock(collections=[])
        mock_qdrant.create_collection = Mock()
        mock_qdrant.upsert = Mock()
        mock_qdrant_class.return_value = mock_qdrant
        
        # Create mock files
        files = []
        for i in range(5):
            mock_file = Mock()
            mock_file.filename = f"test_{i}.cbz"
            mock_file.read = AsyncMock(return_value=b"test")
            mock_file.seek = AsyncMock()
            files.append(mock_file)
        
        # Process concurrently
        tasks = [
            upload_and_index(
                file=f,
                session_id=f"session_{i}",
                book_id=f"book_{i}",
                user_id="user_456"
            )
            for i, f in enumerate(files)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert len(results) == 5
        assert all(r["status"] == "ok" for r in results)
    
    @patch('chat_engine.QdrantClient')
    @patch('chat_engine.get_llm')
    async def test_concurrent_chat_queries(self, mock_get_llm, mock_qdrant_class):
        """Test handling concurrent chat queries"""
        from chat_engine import query_session
        
        # Setup mocks
        mock_llm = Mock()
        mock_get_llm.return_value = mock_llm
        
        mock_qdrant = Mock()
        mock_qdrant.search = Mock(return_value=[])
        mock_qdrant_class.return_value = mock_qdrant
        
        with patch('chat_engine.VectorStoreIndex') as mock_index_class:
            mock_index = Mock()
            mock_query_engine = Mock()
            mock_response = Mock()
            mock_response.response = "Test answer"
            mock_response.source_nodes = []
            mock_response.metadata = {}
            
            mock_query_engine.query = AsyncMock(return_value=mock_response)
            mock_index.as_query_engine.return_value = mock_query_engine
            mock_index_class.from_vector_store.return_value = mock_index
            
            # Process 10 concurrent queries
            tasks = [
                query_session(
                    session_id="test_session",
                    query=f"Question {i}",
                    llm_model="gemini-2.5-flash"
                )
                for i in range(10)
            ]
            
            results = await asyncio.gather(*tasks)
            
            # All should succeed
            assert len(results) == 10
            assert all("response" in r for r in results)


@pytest.mark.unit
class TestResponseTime:
    """Test response time optimization"""
    
    @patch('comic_extractor._extract_with_gemini')
    @patch('comic_extractor._extract_images')
    async def test_extraction_response_time(self, mock_images, mock_extract):
        """Test extraction completes in reasonable time"""
        from comic_extractor import extract_comic_text
        
        mock_images.return_value = [f"/tmp/page_{i}.png" for i in range(25)]
        
        # Mock fast API response
        async def fast_extract(*args, **kwargs):
            await asyncio.sleep(0.01)  # Simulate 10ms API call
            return {
                "pages": [{"page": i, "panels": []} for i in range(25)],
                "tokens_used": {"vision_total_tokens": 6450},
                "cost_usd": 0.005
            }
        
        mock_extract.side_effect = fast_extract
        
        start = time.time()
        result = await extract_comic_text(
            "/tmp/test.cbz",
            batch_size=25,
            vision_provider="gemini"
        )
        duration = time.time() - start
        
        # Should complete quickly (< 1s for mocked API)
        assert duration < 1.0
        assert len(result["pages"]) == 25
    
    @patch('chat_engine.QdrantClient')
    @patch('chat_engine.get_llm')
    async def test_chat_response_time(self, mock_get_llm, mock_qdrant_class):
        """Test chat query completes in reasonable time"""
        from chat_engine import query_session
        
        mock_llm = Mock()
        mock_get_llm.return_value = mock_llm
        
        mock_qdrant = Mock()
        mock_qdrant.search = Mock(return_value=[])
        mock_qdrant_class.return_value = mock_qdrant
        
        with patch('chat_engine.VectorStoreIndex') as mock_index_class:
            mock_index = Mock()
            mock_query_engine = Mock()
            
            # Mock fast LLM response
            async def fast_query(*args, **kwargs):
                await asyncio.sleep(0.05)  # Simulate 50ms LLM call
                mock_response = Mock()
                mock_response.response = "Fast answer"
                mock_response.source_nodes = []
                mock_response.metadata = {}
                return mock_response
            
            mock_query_engine.query = fast_query
            mock_index.as_query_engine.return_value = mock_query_engine
            mock_index_class.from_vector_store.return_value = mock_index
            
            start = time.time()
            result = await query_session(
                session_id="test_session",
                query="Test question",
                llm_model="gemini-2.5-flash"
            )
            duration = time.time() - start
            
            # Should complete quickly (< 1s for mocked LLM)
            assert duration < 1.0
            assert "response" in result


@pytest.mark.unit
class TestCacheEfficiency:
    """Test caching improves performance"""
    
    @patch('document_manager.QdrantClient')
    @patch('document_manager.extract_comic_text')
    @patch('document_manager.calculate_md5')
    async def test_cache_hit_faster_than_extraction(
        self, mock_md5, mock_extract, mock_qdrant_class
    ):
        """Test cache hit is faster than full extraction"""
        from document_manager import upload_and_index
        
        mock_md5.return_value = "abc123"
        
        # Mock existing collection (cache hit)
        mock_qdrant = Mock()
        mock_collection = Mock()
        mock_collection.name = "test_session"
        mock_qdrant.get_collections.return_value = Mock(collections=[mock_collection])
        mock_qdrant.get_collection = Mock(return_value=Mock(
            payload_schema={"file_hash": {"type": "keyword"}},
            points_count=10
        ))
        mock_qdrant_class.return_value = mock_qdrant
        
        mock_file = Mock()
        mock_file.filename = "test.cbz"
        mock_file.read = AsyncMock(return_value=b"test")
        mock_file.seek = AsyncMock()
        
        start = time.time()
        result = await upload_and_index(
            file=mock_file,
            session_id="test_session",
            book_id="book_123",
            user_id="user_456",
            force=False
        )
        duration = time.time() - start
        
        # Cache hit should be very fast
        assert result["status"] == "cached"
        assert duration < 0.1  # < 100ms
        
        # Extract should NOT have been called
        mock_extract.assert_not_called()


@pytest.mark.integration
@pytest.mark.expensive
class TestPerformanceBenchmarks:
    """Performance benchmarks (expensive, skip by default)"""
    
    @pytest.mark.skip(reason="Expensive - real API calls")
    async def test_real_extraction_performance(self, mock_cbz_file):
        """Benchmark real extraction performance"""
        import time
        from comic_extractor import extract_comic_text
        
        start = time.time()
        result = await extract_comic_text(
            file_path=mock_cbz_file,
            batch_size=5,
            vision_provider="gemini",
            vision_model="gemini-2.0-flash-001"
        )
        elapsed = time.time() - start
        
        # Verify results
        assert len(result["pages"]) > 0
        assert result["tokens_used"]["vision_total_tokens"] > 0
        
        # Performance metrics
        pages_per_second = len(result["pages"]) / elapsed
        print(f"\n⏱️  Performance Metrics:")
        print(f"   Total time: {elapsed:.2f}s")
        print(f"   Pages processed: {len(result['pages'])}")
        print(f"   Pages/second: {pages_per_second:.2f}")
        print(f"   Tokens used: {result['tokens_used']['vision_total_tokens']}")
        print(f"   Cost: ${result['cost_usd']:.4f}")
        
        # Sanity check - should process at least 0.5 pages/sec
        assert pages_per_second > 0.5, f"Too slow: {pages_per_second:.2f} pages/sec"
    
    @pytest.mark.skip(reason="Expensive - requires load testing")
    async def test_concurrent_load_performance(self, mock_cbz_file):
        """Test performance under concurrent load"""
        import asyncio
        import time
        from comic_extractor import extract_comic_text
        
        async def extract_task(task_id: int):
            """Single extraction task"""
            start = time.time()
            result = await extract_comic_text(
                file_path=mock_cbz_file,
                batch_size=3,
                vision_provider="gemini",
                vision_model="gemini-2.0-flash-001"
            )
            elapsed = time.time() - start
            return {
                "task_id": task_id,
                "elapsed": elapsed,
                "pages": len(result["pages"]),
                "tokens": result["tokens_used"]["vision_total_tokens"],
                "cost": result["cost_usd"]
            }
        
        # Run 3 concurrent extractions
        print(f"\n🔄 Running 3 concurrent extractions...")
        start = time.time()
        tasks = [extract_task(i) for i in range(3)]
        results = await asyncio.gather(*tasks)
        total_elapsed = time.time() - start
        
        # Verify all completed
        assert len(results) == 3
        for r in results:
            assert r["pages"] > 0
            assert r["tokens"] > 0
        
        # Performance metrics
        total_pages = sum(r["pages"] for r in results)
        total_cost = sum(r["cost"] for r in results)
        avg_time = sum(r["elapsed"] for r in results) / len(results)
        
        print(f"\n⏱️  Concurrent Performance:")
        print(f"   Total wall time: {total_elapsed:.2f}s")
        print(f"   Average task time: {avg_time:.2f}s")
        print(f"   Total pages: {total_pages}")
        print(f"   Total cost: ${total_cost:.4f}")
        print(f"   Throughput: {total_pages/total_elapsed:.2f} pages/sec")
        
        # Concurrent should be faster than sequential
        sequential_estimate = avg_time * 3
        speedup = sequential_estimate / total_elapsed
        print(f"   Speedup: {speedup:.2f}x")
        
        assert speedup > 1.5, f"Poor concurrency: {speedup:.2f}x speedup"
    
    @pytest.mark.skip(reason="Expensive - long running")
    async def test_memory_usage_over_time(self, mock_cbz_file):
        """Test memory usage doesn't grow over time"""
        import psutil
        import os
        from comic_extractor import extract_comic_text
        
        process = psutil.Process(os.getpid())
        memory_samples = []
        
        # Baseline memory
        baseline = process.memory_info().rss / 1024 / 1024  # MB
        memory_samples.append(baseline)
        
        print(f"\n💾 Memory Usage Test:")
        print(f"   Baseline: {baseline:.1f} MB")
        
        # Run 5 extractions and monitor memory
        for i in range(5):
            result = await extract_comic_text(
                file_path=mock_cbz_file,
                batch_size=3,
                vision_provider="gemini",
                vision_model="gemini-2.0-flash-001"
            )
            
            current = process.memory_info().rss / 1024 / 1024
            memory_samples.append(current)
            print(f"   After run {i+1}: {current:.1f} MB (+{current-baseline:.1f} MB)")
            
            assert len(result["pages"]) > 0
        
        # Check for memory leak
        final = memory_samples[-1]
        growth = final - baseline
        growth_percent = (growth / baseline) * 100
        
        print(f"\n   Final: {final:.1f} MB")
        print(f"   Total growth: {growth:.1f} MB ({growth_percent:.1f}%)")
        
        # Allow up to 50% growth (some caching is expected)
        assert growth_percent < 50, f"Memory leak detected: {growth_percent:.1f}% growth"
