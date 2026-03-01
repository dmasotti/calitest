"""
Unit tests for comic_extractor
"""
import pytest
import sys
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from comic_extractor import (
    extract_comic_text,
    _extract_images,
    _parse_gemini_response,
    _parse_gemini_response_text
)


@pytest.mark.unit
class TestExtractImages:
    """Test image extraction from comic files"""
    
    def test_extract_images_from_cbz(self, mock_cbz_file):
        """Test extracting images from CBZ file"""
        images = _extract_images(mock_cbz_file)
        
        assert len(images) == 3
        assert all(img.endswith('.png') for img in images)
    
    def test_extract_images_invalid_file(self, tmp_path):
        """Test extracting from invalid file raises error"""
        invalid_file = tmp_path / "invalid.txt"
        invalid_file.write_text("not a comic")
        
        with pytest.raises(Exception):
            _extract_images(str(invalid_file))
    
    def test_extract_images_nonexistent_file(self):
        """Test extracting from nonexistent file raises error"""
        with pytest.raises(Exception):
            _extract_images("/nonexistent/file.cbz")


@pytest.mark.unit
class TestParseGeminiResponse:
    """Test parsing Gemini Vision API responses"""
    
    def test_parse_valid_json_response(self):
        """Test parsing valid JSON response"""
        response_text = json.dumps({
            "pages": [
                {
                    "page": 0,
                    "panels": [
                        {
                            "x": 10,
                            "y": 10,
                            "width": 200,
                            "height": 300,
                            "description": "Test panel",
                            "balloons": [],
                            "sound_effects": []
                        }
                    ]
                }
            ]
        })
        
        result = _parse_gemini_response(response_text, start_page=0, num_pages=1)
        
        assert len(result) == 1
        assert result[0]["page"] == 0
        assert len(result[0]["panels"]) == 1
    
    def test_parse_response_with_characters(self):
        """Test parsing response with character tracking"""
        response_text = json.dumps({
            "pages": [{"page": 0, "panels": []}],
            "characters": [
                {
                    "id": "C1",
                    "description": "Spider-Man",
                    "first_appearance_page": 0
                }
            ]
        })
        
        result = _parse_gemini_response(response_text, start_page=0, num_pages=1)
        
        assert len(result) == 1
    
    def test_parse_invalid_json_returns_error(self):
        """Test parsing invalid JSON returns error page"""
        response_text = "not valid json"
        
        result = _parse_gemini_response(response_text, start_page=0, num_pages=1)
        
        assert len(result) == 1
        assert "[Error" in result[0]["description"]
    
    def test_parse_response_text_fallback(self):
        """Test text-based parsing fallback"""
        response_text = """
        Page 0:
        Panel 1: Spider-Man swinging
        """
        
        result = _parse_gemini_response_text(response_text, start_page=0, num_pages=1)
        
        assert len(result) == 1
        assert result[0]["page"] == 0


@pytest.mark.unit
@patch('comic_extractor._extract_images')
@patch('comic_extractor._extract_with_gemini')
class TestExtractComicText:
    """Test main extract_comic_text function"""
    
    async def test_extract_with_gemini_provider(self, mock_extract_gemini, mock_extract_images):
        """Test extraction with Gemini provider"""
        # Mock image extraction
        mock_extract_images.return_value = ["/tmp/page_000.png", "/tmp/page_001.png"]
        
        # Mock Gemini extraction
        mock_extract_gemini.return_value = {
            "pages": [
                {"page": 0, "panels": []},
                {"page": 1, "panels": []}
            ],
            "tokens_used": {
                "vision_input_images": 2,
                "vision_input_tokens_estimated": 516,
                "vision_output_tokens": 100,
                "vision_total_tokens": 616
            },
            "cost_usd": 0.0004
        }
        
        result = await extract_comic_text(
            file_path="/tmp/test.cbz",
            batch_size=10,
            vision_provider="gemini"
        )
        
        assert result["pages"] == mock_extract_gemini.return_value["pages"]
        assert result["tokens_used"]["vision_total_tokens"] == 616
        assert result["cost_usd"] == 0.0004
        
        # Verify mocks called
        mock_extract_images.assert_called_once_with("/tmp/test.cbz")
        mock_extract_gemini.assert_called_once()


@pytest.mark.unit
@patch('comic_extractor._extract_images')
@patch('comic_extractor._extract_with_openai')
class TestExtractWithOpenAI:
    """Test extraction with OpenAI provider"""
    
    async def test_extract_with_openai_provider(self, mock_extract_openai, mock_extract_images):
        """Test extraction with OpenAI provider"""
        mock_extract_images.return_value = ["/tmp/page_000.png"]
        
        mock_extract_openai.return_value = {
            "pages": [{"page": 0, "panels": []}],
            "tokens_used": {
                "vision_input_images": 1,
                "vision_input_tokens": 1000,
                "vision_output_tokens": 200,
                "vision_total_tokens": 1200
            },
            "cost_usd": 0.01275
        }
        
        result = await extract_comic_text(
            file_path="/tmp/test.cbz",
            batch_size=5,
            vision_provider="openai",
            vision_model="gpt-4o-mini"
        )
        
        assert len(result["pages"]) == 1
        assert result["cost_usd"] == 0.01275
        
        mock_extract_openai.assert_called_once()


@pytest.mark.unit
class TestCharacterTracking:
    """Test character tracking feature"""
    
    def test_parse_response_with_character_ids(self):
        """Test parsing response with character IDs in balloons"""
        response_text = json.dumps({
            "pages": [
                {
                    "page": 0,
                    "panels": [
                        {
                            "x": 10,
                            "y": 10,
                            "width": 200,
                            "height": 300,
                            "description": "Spider-Man talking",
                            "balloons": [
                                {
                                    "character_id": "C1",
                                    "text": "With great power...",
                                    "x": 50,
                                    "y": 50
                                }
                            ],
                            "sound_effects": []
                        }
                    ]
                }
            ],
            "characters": [
                {
                    "id": "C1",
                    "description": "Spider-Man",
                    "first_appearance_page": 0
                }
            ]
        })
        
        result = _parse_gemini_response(response_text, start_page=0, num_pages=1)
        
        assert len(result) == 1
        balloon = result[0]["panels"][0]["balloons"][0]
        assert balloon["character_id"] == "C1"
        assert balloon["text"] == "With great power..."


@pytest.mark.unit
class TestErrorHandling:
    """Test error handling in extraction"""
    
    @patch('comic_extractor._extract_images')
    async def test_extract_handles_image_extraction_error(self, mock_extract_images):
        """Test extraction handles image extraction errors"""
        mock_extract_images.side_effect = Exception("Failed to extract images")
        
        with pytest.raises(Exception) as exc_info:
            await extract_comic_text("/tmp/test.cbz")
        
        assert "Failed to extract images" in str(exc_info.value)
    
    def test_parse_handles_malformed_json(self):
        """Test parsing handles malformed JSON gracefully"""
        response_text = '{"pages": [{"page": 0, "panels": ['  # Incomplete JSON
        
        result = _parse_gemini_response(response_text, start_page=0, num_pages=1)
        
        assert len(result) == 1
        assert "[Error" in result[0]["description"]


@pytest.mark.expensive
@pytest.mark.integration
class TestRealAPIExtraction:
    """Integration tests with real API calls (expensive, skip by default)"""
    
    @pytest.mark.skip(reason="Expensive API call - run manually")
    async def test_extract_with_real_gemini_api(self, mock_cbz_file):
        """Test extraction with real Gemini API (costs ~$0.0006)"""
        result = await extract_comic_text(
            file_path=mock_cbz_file,
            batch_size=3,
            vision_provider="gemini",
            vision_model="gemini-2.0-flash-001"
        )
        
        assert len(result["pages"]) == 3
        assert result["tokens_used"]["vision_total_tokens"] > 0
        assert result["cost_usd"] > 0
    
    @pytest.mark.skip(reason="Expensive API call - run manually")
    async def test_extract_with_real_openai_api(self, mock_cbz_file):
        """Test extraction with real OpenAI API (costs ~$0.04)"""
        result = await extract_comic_text(
            file_path=mock_cbz_file,
            batch_size=3,
            vision_provider="openai",
            vision_model="gpt-4o-mini"
        )
        
        assert len(result["pages"]) == 3
        assert result["tokens_used"]["vision_total_tokens"] > 0
        assert result["cost_usd"] > 0
    
    @pytest.mark.skip(reason="Expensive API call - run manually")
    
    @pytest.mark.skip(reason="Expensive API call - run manually")
    async def test_extract_with_real_anthropic_api(self, mock_cbz_file):
        """Test extraction with real Anthropic API (costs ~$0.02)"""
        result = await extract_comic_text(
            file_path=mock_cbz_file,
            batch_size=3,
            vision_provider="anthropic",
            vision_model="claude-3-5-sonnet-20241022"
        )
        
        assert len(result["pages"]) == 3
        assert result["tokens_used"]["vision_total_tokens"] > 0
        assert result["cost_usd"] > 0
    
    @pytest.mark.skip(reason="Expensive API call - run manually")
    async def test_extract_with_real_qwen_api(self, mock_cbz_file):
        """Test extraction with real Qwen API (costs ~$0.001)"""
        result = await extract_comic_text(
            file_path=mock_cbz_file,
            batch_size=3,
            vision_provider="qwen",
            vision_model="qwen-vl-max"
        )
        
        assert len(result["pages"]) == 3
        assert result["tokens_used"]["vision_total_tokens"] > 0
        assert result["cost_usd"] > 0
