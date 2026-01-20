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
    result = shrink_python_file(str(sample_python_file))
    shrunken_content = result.content
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
    result = shrink_python_file(str(sample_python_file), aggressive=True)
    shrunken_content = result.content
    assert "class MyClass:" in shrunken_content
    assert 'field = "value"' in shrunken_content
    assert "def my_method(self):" not in shrunken_content
    assert "pass  # shrunk" not in shrunken_content
    assert "@decorator" not in shrunken_content
    assert 'print("Hello")' not in shrunken_content
    assert "return 1" not in shrunken_content


def test_shrink_python_file_max_fields(tmp_path: Path):
    """Test max shrinking with field reconstruction."""
    file_path = tmp_path / "fields.py"
    file_path.write_text(
        """
from odoo import fields, models

class MyModel(models.Model):
    _name = "my.model"

    user_id = fields.Many2one(
        comodel_name='res.users',
        string="User",
        help="The user",
        store=True,
        index=True,
        tracking=True
    )

    lines_ids = fields.One2many(
        'my.line',
        'model_id',
        string="Lines",
        context={'active_test': False}
    )
"""
    )

    # We need to simulate that 'res.users' and 'my.line' are relevant models
    # so fields are kept.
    relevant_models = {"res.users", "my.line"}

    result = shrink_python_file(
        str(file_path), shrink_level="max", relevant_models=relevant_models
    )
    content = result.content

    # Check that UI attributes are gone
    assert 'string="User"' not in content
    assert 'help="The user"' not in content
    assert "index=True" not in content
    assert "tracking=True" not in content
    assert "context={" not in content

    # Check that structural attributes remain
    # Exact formatting depends on whitespace handling
    assert "user_id = fields.Many2one(comodel_name='res.users', store=True)" in content

    # Check One2many
    assert "lines_ids = fields.One2many('my.line', 'model_id')" in content
