import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# Make sure the main cli module is importable
try:
    from akaidoo.cli import app
except ImportError:
    # This might happen if the package is not installed; adjust path if needed
    # Or ensure your test runner (like pytest) handles the source layout
    pytest.skip("Skipping CLI tests, akaidoo package not found in PYTHONPATH", allow_module_level=True)


runner = CliRunner()

# --- Test Setup ---
# Create a dummy Odoo addon structure for testing
# You might need to make this more sophisticated depending on test complexity

@pytest.fixture(scope="module")
def dummy_addons_path(tmp_path_factory):
    """Creates a temporary directory structure mimicking Odoo addons."""
    base_path = tmp_path_factory.mktemp("dummy_addons")

    # Addon A depends on B and base
    addon_a_path = base_path / "addon_a"
    addon_a_path.mkdir()
    (addon_a_path / "__init__.py").touch()
    (addon_a_path / "__manifest__.py").write_text(
        "{'name': 'Addon A', 'version': '16.0.1.0.0', 'depends': ['base', 'addon_b'], 'installable': True}"
    )
    (addon_a_path / "models").mkdir()
    (addon_a_path / "models" / "__init__.py").touch()
    (addon_a_path / "models" / "a_model.py").write_text("class AModel:\n    pass\n")
    (addon_a_path / "views").mkdir()
    (addon_a_path / "views" / "a_view.xml").write_text("<odoo><data/></odoo>")

    # Addon B depends on base
    addon_b_path = base_path / "addon_b"
    addon_b_path.mkdir()
    (addon_b_path / "__init__.py").touch()
    (addon_b_path / "__manifest__.py").write_text(
        "{'name': 'Addon B', 'version': '16.0.1.0.0', 'depends': ['base'], 'installable': True}"
    )
    (addon_b_path / "models").mkdir()
    (addon_b_path / "models" / "__init__.py").touch()
    (addon_b_path / "models" / "b_model.py").write_text("class BModel:\n    pass\n")
    (addon_b_path / "wizard").mkdir()
    (addon_b_path / "wizard" / "b_wizard.xml").write_text("<odoo><data/></odoo>")


    # Addon C (no deps)
    addon_c_path = base_path / "addon_c"
    addon_c_path.mkdir()
    (addon_c_path / "__init__.py").touch()
    (addon_c_path / "__manifest__.py").write_text(
        "{'name': 'Addon C', 'version': '16.0.1.0.0', 'depends': [], 'installable': True}"
    )
    (addon_c_path / "security").mkdir()
    (addon_c_path / "security" / "ir.model.access.csv").write_text("id,name\naccess_c,access_c\n")


    # Simulate a core addon (if needed for exclude tests)
    # For simplicity, we'll rely on manifestoo's core addon detection if possible,
    # otherwise, more setup is needed here (or mocking).
    # addon_base_path = base_path / "base"
    # addon_base_path.mkdir()
    # (addon_base_path / "__init__.py").touch()
    # (addon_base_path / "__manifest__.py").write_text("{'name': 'Base', 'version': '16.0.1.0.0', 'depends': []}")


    return base_path


# --- Tests ---


def test_list_files_help():
    """Test the help message."""
    result = runner.invoke(app, ["list-files", "--help"])
    assert result.exit_code == 0
    assert "Usage: akaidoo list-files [OPTIONS] ADDON_NAME" in result.stdout
    assert "--include-models/--no-include-models" in result.stdout
    assert "--exclude-core" in result.stdout


def test_list_files_basic(dummy_addons_path):
    """Test basic file listing for addon_a and its dependency addon_b."""
    result = runner.invoke(
        app,
        [
            "list-files",
            "addon_a",
            "--addons-path",
            str(dummy_addons_path),
             # Prevent trying to import odoo if not available in test env
            "--no-addons-path-from-import-odoo",
            "--odoo-series", "16.0", # Specify series for consistency
            "--separator", ",", # Use comma for easier splitting/assertion
        ],
        catch_exceptions=False # Easier debugging
    )
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    assert result.exit_code == 0

    output_files = {Path(p).name for p in result.stdout.strip().split(',') if p}

    # Expected files from addon_a and addon_b
    expected = {
        "__init__.py", # Root of a
        "a_model.py",
        "a_view.xml",
        "__init__.py", # Root of b
        "b_model.py",
        "b_wizard.xml",
    }

    # Check if expected files are a subset of output (ignore __init__ duplicates carefully)
    # A simpler check for now:
    assert "a_model.py" in output_files
    assert "a_view.xml" in output_files
    assert "b_model.py" in output_files
    assert "b_wizard.xml" in output_files
    # __init__.py might appear multiple times, once per addon and model dir
    assert "__init__.py" in output_files

    # Ensure addon_c files are NOT included
    assert "ir.model.access.csv" not in output_files


def test_list_files_only_models(dummy_addons_path):
    """Test listing only model files."""
    result = runner.invoke(
        app,
        [
            "list-files",
            "addon_a",
            "--addons-path", str(dummy_addons_path),
            "--no-addons-path-from-import-odoo",
            "--odoo-series", "16.0",
            "--only-models",
            "--separator", ",",
        ],
         catch_exceptions=False
    )
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    assert result.exit_code == 0
    output_files = {Path(p).name for p in result.stdout.strip().split(',') if p}
    expected = {"__init__.py", "a_model.py", "b_model.py"} # model __init__.py + model files
    assert output_files.issuperset(expected) # Check if expected models are present
    assert "a_view.xml" not in output_files
    assert "b_wizard.xml" not in output_files


def test_list_files_no_wizards(dummy_addons_path):
    """Test excluding wizard files."""
    result = runner.invoke(
        app,
        [
            "list-files",
            "addon_a",
            "--addons-path", str(dummy_addons_path),
            "--no-addons-path-from-import-odoo",
            "--odoo-series", "16.0",
            "--no-include-wizards",
            "--separator", ",",
        ],
         catch_exceptions=False
    )
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    assert result.exit_code == 0
    output_files = {Path(p).name for p in result.stdout.strip().split(',') if p}
    assert "a_model.py" in output_files
    assert "a_view.xml" in output_files
    assert "b_model.py" in output_files
    assert "b_wizard.xml" not in output_files # This should be excluded


def test_list_files_missing_dependency(dummy_addons_path):
    """Test scenario with a missing dependency (addon_b removed)."""
    addon_b_path = dummy_addons_path / "addon_b" / "__manifest__.py"
    original_content = addon_b_path.read_text()
    addon_b_path.unlink() # Temporarily remove addon_b manifest

    result = runner.invoke(
        app,
        [
            "list-files",
            "addon_a",
            "--addons-path", str(dummy_addons_path),
            "--no-addons-path-from-import-odoo",
            "--odoo-series", "16.0",
            "--separator", ",",
        ],
         catch_exceptions=False
    )
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    assert result.exit_code == 0 # Currently warns, does not exit with error
    assert "Missing dependencies found: addon_b" in result.stderr # Check stderr for warning
    output_files = {Path(p).name for p in result.stdout.strip().split(',') if p}
    # Should still list files from addon_a
    assert "a_model.py" in output_files
    assert "a_view.xml" in output_files
    # Files from addon_b should not be listed
    assert "b_model.py" not in output_files

    # Restore addon_b
    addon_b_path.write_text(original_content)
