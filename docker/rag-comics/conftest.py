"""
Shared fixtures for RAG Comics tests
"""
import pytest
import io
import zipfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock
from PIL import Image


@pytest.fixture
def mock_cbz_file(tmp_path):
    """Create a mock CBZ file with test images"""
    cbz_path = tmp_path / "test.cbz"
    
    # Create a simple test image
    img = Image.new('RGB', (100, 100), color='red')
    
    # Create CBZ (ZIP with images)
    with zipfile.ZipFile(cbz_path, 'w') as zf:
        for i in range(3):
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='PNG')
            zf.writestr(f"page_{i:03d}.png", img_bytes.getvalue())
    
    return str(cbz_path)


@pytest.fixture
def mock_upload_file():
    """Mock FastAPI UploadFile"""
    mock = Mock()
    mock.filename = "test.cbz"
    mock.content_type = "application/zip"
    mock.file = io.BytesIO(b"test content")
    mock.read = AsyncMock(return_value=b"test content")
    mock.seek = AsyncMock()
    return mock


@pytest.fixture
def mock_qdrant_client():
    """Mock Qdrant client"""
    mock = Mock()
    mock.get_collections = Mock(return_value=Mock(collections=[]))
    mock.create_collection = Mock()
    mock.delete_collection = Mock()
    mock.upsert = Mock()
    return mock


@pytest.fixture
def sample_comic_pages():
    """Sample comic pages data structure"""
    return [
        {
            "page": 0,
            "panels": [
                {
                    "x": 10,
                    "y": 10,
                    "width": 200,
                    "height": 300,
                    "description": "Spider-Man swinging through the city",
                    "balloons": [
                        {
                            "character_id": "C1",
                            "text": "With great power comes great responsibility",
                            "x": 50,
                            "y": 50
                        }
                    ],
                    "sound_effects": []
                }
            ]
        }
    ]


@pytest.fixture
def sample_characters():
    """Sample character data"""
    return [
        {
            "id": "C1",
            "description": "Spider-Man - red and blue costume, web shooters",
            "first_appearance_page": 0
        }
    ]


@pytest.fixture
def mock_gemini_response():
    """Mock Gemini Vision API response"""
    return {
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
        ],
        "characters": []
    }


@pytest.fixture
def mock_openai_response():
    """Mock OpenAI Vision API response"""
    mock = Mock()
    mock.choices = [
        Mock(message=Mock(content='{"pages": [{"page": 0, "panels": []}]}'))
    ]
    mock.usage = Mock(
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150
    )
    return mock
