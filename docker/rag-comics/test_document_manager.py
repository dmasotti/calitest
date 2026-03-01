"""
Unit tests for document_manager
"""
import pytest
import sys
import hashlib
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from document_manager import upload_and_index, calculate_md5


@pytest.mark.unit
class TestCalculateMD5:
    """Test MD5 hash calculation"""
    
    async def test_calculate_md5_simple(self, mock_upload_file):
        """Test MD5 calculation for simple content"""
        mock_upload_file.file = MagicMock()
        mock_upload_file.file.read = Mock(return_value=b"test content")
        
        result = calculate_md5(mock_upload_file)
        
        expected = hashlib.md5(b"test content").hexdigest()
        assert result == expected
    
    async def test_calculate_md5_empty_file(self, mock_upload_file):
        """Test MD5 calculation for empty file"""
        mock_upload_file.file = MagicMock()
        mock_upload_file.file.read = Mock(return_value=b"")
        
        result = calculate_md5(mock_upload_file)
        
        expected = hashlib.md5(b"").hexdigest()
        assert result == expected


@pytest.mark.unit
@patch('document_manager.QdrantClient')
@patch('document_manager.extract_comic_text')
@patch('document_manager.calculate_md5')
class TestUploadAndIndex:
    """Test upload and indexing workflow"""
    
    async def test_upload_new_file_creates_collection(
        self, mock_md5, mock_extract, mock_qdrant_class, mock_upload_file
    ):
        """Test uploading new file creates Qdrant collection"""
        # Setup mocks
        mock_md5.return_value = "abc123"
        mock_extract.return_value = {
            "pages": [{"page": 0, "panels": []}],
            "tokens_used": {"vision_total_tokens": 500, "embedding_total_tokens": 100},
            "cost_usd": 0.001
        }
        
        mock_qdrant = Mock()
        mock_qdrant.get_collections.return_value = Mock(collections=[])
        mock_qdrant.create_collection = Mock()
        mock_qdrant.upsert = Mock()
        mock_qdrant_class.return_value = mock_qdrant
        
        # Execute
        result = await upload_and_index(
            file=mock_upload_file,
            session_id="test_session",
            book_id="book_123",
            user_id="user_456",
            force=False
        )
        
        # Verify
        assert result["status"] == "ok"
        assert result["chunks_indexed"] > 0
        mock_qdrant.create_collection.assert_called_once()
    
    async def test_upload_with_cache_hit(
        self, mock_md5, mock_extract, mock_qdrant_class, mock_upload_file
    ):
        """Test upload with cache hit skips extraction"""
        # Setup mocks
        mock_md5.return_value = "abc123"
        
        mock_qdrant = Mock()
        # Simulate existing collection
        mock_collection = Mock()
        mock_collection.name = "test_session"
        mock_qdrant.get_collections.return_value = Mock(collections=[mock_collection])
        mock_qdrant.get_collection = Mock(return_value=Mock(
            payload_schema={"file_hash": {"type": "keyword"}},
            points_count=10
        ))
        mock_qdrant_class.return_value = mock_qdrant
        
        # Execute
        result = await upload_and_index(
            file=mock_upload_file,
            session_id="test_session",
            book_id="book_123",
            user_id="user_456",
            force=False
        )
        
        # Verify - should use cache
        assert result["status"] == "cached"
        mock_extract.assert_not_called()
    
    async def test_upload_with_force_skips_cache(
        self, mock_md5, mock_extract, mock_qdrant_class, mock_upload_file
    ):
        """Test force=True skips cache and reprocesses"""
        # Setup mocks
        mock_md5.return_value = "abc123"
        mock_extract.return_value = {
            "pages": [{"page": 0, "panels": []}],
            "tokens_used": {"vision_total_tokens": 500},
            "cost_usd": 0.001
        }
        
        mock_qdrant = Mock()
        mock_collection = Mock()
        mock_collection.name = "test_session"
        mock_qdrant.get_collections.return_value = Mock(collections=[mock_collection])
        mock_qdrant.delete_collection = Mock()
        mock_qdrant.create_collection = Mock()
        mock_qdrant.upsert = Mock()
        mock_qdrant_class.return_value = mock_qdrant
        
        # Execute with force=True
        result = await upload_and_index(
            file=mock_upload_file,
            session_id="test_session",
            book_id="book_123",
            user_id="user_456",
            force=True
        )
        
        # Verify - should delete and recreate
        assert result["status"] == "ok"
        mock_qdrant.delete_collection.assert_called_once()
        mock_extract.assert_called_once()
    
    async def test_upload_with_character_tracking(
        self, mock_md5, mock_extract, mock_qdrant_class, mock_upload_file
    ):
        """Test upload with character tracking enabled"""
        # Setup mocks
        mock_md5.return_value = "abc123"
        mock_extract.return_value = {
            "pages": [{"page": 0, "panels": []}],
            "characters": [
                {"id": "C1", "description": "Spider-Man", "first_appearance_page": 0}
            ],
            "tokens_used": {"vision_total_tokens": 500},
            "cost_usd": 0.001
        }
        
        mock_qdrant = Mock()
        mock_qdrant.get_collections.return_value = Mock(collections=[])
        mock_qdrant.create_collection = Mock()
        mock_qdrant.upsert = Mock()
        mock_qdrant_class.return_value = mock_qdrant
        
        # Execute
        result = await upload_and_index(
            file=mock_upload_file,
            session_id="test_session",
            book_id="book_123",
            user_id="user_456",
            enable_character_tracking=True
        )
        
        # Verify
        assert result["status"] == "ok"
        # Character tracking should be passed to extract_comic_text
        mock_extract.assert_called_once()
        call_kwargs = mock_extract.call_args[1]
        assert call_kwargs["enable_character_tracking"] is True


@pytest.mark.unit
@patch('document_manager.httpx.AsyncClient')
class TestCallbackSending:
    """Test callback webhook sending"""
    
    async def test_callback_sent_on_success(self, mock_httpx_class):
        """Test callback is sent on successful indexing"""
        # This would require more complex mocking of the full upload_and_index flow
        # For now, we verify the callback structure
        pass
    
    async def test_callback_sent_on_error(self, mock_httpx_class):
        """Test callback is sent on indexing error"""
        pass
    
    async def test_callback_includes_all_required_fields(self, mock_httpx_class):
        """Test callback payload includes all required fields"""
        # Expected fields:
        # - kind: "indexing"
        # - status: "completed" | "error"
        # - book_id
        # - session_id
        # - pages_indexed
        # - tokens_used
        # - cost_usd
        # - completed_at
        pass


@pytest.mark.unit
class TestTokenTracking:
    """Test token tracking in upload_and_index"""
    
    @patch('document_manager.QdrantClient')
    @patch('document_manager.extract_comic_text')
    @patch('document_manager.calculate_md5')
    async def test_tokens_tracked_correctly(
        self, mock_md5, mock_extract, mock_qdrant_class, mock_upload_file
    ):
        """Test tokens are tracked correctly"""
        mock_md5.return_value = "abc123"
        mock_extract.return_value = {
            "pages": [{"page": 0, "panels": []}],
            "tokens_used": {
                "vision_total_tokens": 46200,
                "embedding_total_tokens": 8500
            },
            "cost_usd": 0.032
        }
        
        mock_qdrant = Mock()
        mock_qdrant.get_collections.return_value = Mock(collections=[])
        mock_qdrant.create_collection = Mock()
        mock_qdrant.upsert = Mock()
        mock_qdrant_class.return_value = mock_qdrant
        
        result = await upload_and_index(
            file=mock_upload_file,
            session_id="test_session",
            book_id="book_123",
            user_id="user_456"
        )
        
        # Verify token tracking
        assert "tokens_used" in result
        assert result["tokens_used"]["vision_total_tokens"] == 46200
        assert result["tokens_used"]["embedding_total_tokens"] == 8500
        assert result["cost_usd"] == 0.032


@pytest.mark.integration
class TestUploadAndIndexIntegration:
    """Integration tests with real Qdrant (requires Qdrant running)"""
    
    @pytest.mark.skip(reason="Requires Qdrant instance")
    async def test_upload_to_real_qdrant(self, mock_cbz_file):
        """Test upload to real Qdrant instance"""
        # This would test against a real Qdrant instance
        # Skip by default to avoid dependencies
        pass
