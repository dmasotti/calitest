"""
Unit tests for chat_engine
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from chat_engine import query_session, get_llm


@pytest.mark.unit
class TestGetLLM:
    """Test LLM initialization"""
    
    @patch('chat_engine.Gemini')
    def test_get_llm_gemini_default(self, mock_gemini_class):
        """Test getting Gemini LLM with default model"""
        mock_llm = Mock()
        mock_gemini_class.return_value = mock_llm
        
        with patch.dict('os.environ', {'LLM_PROVIDER': 'google', 'GOOGLE_API_KEY': 'test_key'}):
            llm = get_llm()
        
        assert llm == mock_llm
        mock_gemini_class.assert_called_once()
    
    @patch('chat_engine.Gemini')
    def test_get_llm_with_model_override(self, mock_gemini_class):
        """Test getting LLM with model override"""
        mock_llm = Mock()
        mock_gemini_class.return_value = mock_llm
        
        with patch.dict('os.environ', {'LLM_PROVIDER': 'google', 'GOOGLE_API_KEY': 'test_key'}):
            llm = get_llm(model_override="gemini-2.5-pro")
        
        mock_gemini_class.assert_called_once()
        call_kwargs = mock_gemini_class.call_args[1]
        assert call_kwargs["model"] == "models/gemini-2.5-pro"
    
    @patch('chat_engine.OpenAI')
    def test_get_llm_openai(self, mock_openai_class):
        """Test getting OpenAI LLM"""
        mock_llm = Mock()
        mock_openai_class.return_value = mock_llm
        
        with patch.dict('os.environ', {'LLM_PROVIDER': 'openai', 'OPENAI_API_KEY': 'test_key'}):
            llm = get_llm()
        
        assert llm == mock_llm
        mock_openai_class.assert_called_once()


@pytest.mark.unit
@patch('chat_engine.QdrantClient')
@patch('chat_engine.get_llm')
class TestQuerySession:
    """Test RAG query functionality"""
    
    async def test_query_with_results(self, mock_get_llm, mock_qdrant_class):
        """Test query returns results from RAG"""
        # Setup mocks
        mock_llm = Mock()
        mock_get_llm.return_value = mock_llm
        
        mock_qdrant = Mock()
        mock_qdrant.search = Mock(return_value=[
            Mock(
                payload={"text": "Spider-Man swings through the city"},
                score=0.95
            )
        ])
        mock_qdrant_class.return_value = mock_qdrant
        
        # Mock LLM response
        with patch('chat_engine.VectorStoreIndex') as mock_index_class:
            mock_index = Mock()
            mock_query_engine = Mock()
            mock_response = Mock()
            mock_response.response = "Spider-Man is a superhero"
            mock_response.source_nodes = []
            mock_response.metadata = {"llm_model": "gemini-2.5-flash"}
            
            mock_query_engine.query = AsyncMock(return_value=mock_response)
            mock_index.as_query_engine.return_value = mock_query_engine
            mock_index_class.from_vector_store.return_value = mock_index
            
            # Execute
            result = await query_session(
                session_id="test_session",
                query="Who is Spider-Man?",
                llm_model="gemini-2.5-flash"
            )
        
        # Verify
        assert result["response"] == "Spider-Man is a superhero"
        assert "tokens_used" in result
    
    async def test_query_no_results(self, mock_get_llm, mock_qdrant_class):
        """Test query with no matching results"""
        mock_llm = Mock()
        mock_get_llm.return_value = mock_llm
        
        mock_qdrant = Mock()
        mock_qdrant.search = Mock(return_value=[])
        mock_qdrant_class.return_value = mock_qdrant
        
        with patch('chat_engine.VectorStoreIndex') as mock_index_class:
            mock_index = Mock()
            mock_query_engine = Mock()
            mock_response = Mock()
            mock_response.response = "I don't have information about that."
            mock_response.source_nodes = []
            mock_response.metadata = {}
            
            mock_query_engine.query = AsyncMock(return_value=mock_response)
            mock_index.as_query_engine.return_value = mock_query_engine
            mock_index_class.from_vector_store.return_value = mock_index
            
            result = await query_session(
                session_id="test_session",
                query="Unknown character",
                llm_model="gemini-2.5-flash"
            )
        
        assert "response" in result


@pytest.mark.unit
class TestTokenTracking:
    """Test token tracking in chat responses"""
    
    @patch('chat_engine.QdrantClient')
    @patch('chat_engine.get_llm')
    async def test_query_returns_token_count(self, mock_get_llm, mock_qdrant_class):
        """Test query response includes token count"""
        mock_llm = Mock()
        mock_get_llm.return_value = mock_llm
        
        mock_qdrant = Mock()
        mock_qdrant.search = Mock(return_value=[])
        mock_qdrant_class.return_value = mock_qdrant
        
        with patch('chat_engine.VectorStoreIndex') as mock_index_class:
            mock_index = Mock()
            mock_query_engine = Mock()
            mock_response = Mock()
            mock_response.response = "Test response"
            mock_response.source_nodes = []
            mock_response.metadata = {
                "llm_model": "gemini-2.5-flash",
                "tokens_input": 100,
                "tokens_output": 50
            }
            
            mock_query_engine.query = AsyncMock(return_value=mock_response)
            mock_index.as_query_engine.return_value = mock_query_engine
            mock_index_class.from_vector_store.return_value = mock_index
            
            result = await query_session(
                session_id="test_session",
                query="Test query",
                llm_model="gemini-2.5-flash"
            )
        
        # Verify token tracking
        assert "tokens_used" in result
        # Note: actual token tracking depends on LLM response format


@pytest.mark.integration
class TestQuerySessionIntegration:
    """Integration tests with real services"""
    
    @pytest.mark.skip(reason="Requires Qdrant and LLM API")
    async def test_query_with_real_services(self):
        """Test query with real Qdrant and LLM"""
        # This would test against real services
        # Skip by default to avoid dependencies and costs
        pass
