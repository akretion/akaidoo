from pathlib import Path
import pytest
from akaidoo.shrinker import shrink_python_file


@pytest.fixture
def sample_python_file(tmp_path: Path) -> Path:
    """Create a sample Python file for testing."""
    file_path = tmp_path / "sample.py"
    file_path.write_text(
        """
class MyClass:
    field = "value"

    def my_method(self):
        print("Hello")

@decorator
def my_function():
    return 1
"""
    )
    return file_path


def test_shrink_python_file_default(sample_python_file: Path):
    """Test the default shrinking behavior."""
    shrunken_content = shrink_python_file(str(sample_python_file))
    assert "class MyClass:" in shrunken_content
    assert 'field = "value"' in shrunken_content
    assert "def my_method(self):" in shrunken_content
    assert "pass  # shrunk" in shrunken_content
    assert "@decorator" in shrunken_content
    assert "def my_function():" in shrunken_content
    assert 'print("Hello")' not in shrunken_content
    assert "return 1" not in shrunken_content


def test_shrink_python_file_aggressive(sample_python_file: Path):
    """Test the aggressive shrinking behavior."""
    shrunken_content = shrink_python_file(str(sample_python_file), aggressive=True)
    assert "class MyClass:" in shrunken_content
    assert 'field = "value"' in shrunken_content
    assert "def my_method(self):" not in shrunken_content
    assert "pass  # shrunk" not in shrunken_content
    assert "@decorator" not in shrunken_content
    assert "def my_function():" not in shrunken_content
    assert 'print("Hello")' not in shrunken_content
    assert "return 1" not in shrunken_content
