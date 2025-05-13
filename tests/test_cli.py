import subprocess
import sys
from pathlib import Path
import os
import shutil # For managing test files

import pytest
from typer.testing import CliRunner

# Make sure the main cli module is importable
try:
    from akaidoo.cli import app, FRAMEWORK_ADDONS # import FRAMEWORK_ADDONS for testing it
except ImportError:
    pytest.skip("Skipping CLI tests, akaidoo package not found in PYTHONPATH", allow_module_level=True)


runner = CliRunner()

# --- Test Setup ---

@pytest.fixture(scope="module")
def dummy_addons_env(tmp_path_factory):
    """Creates a temporary directory structure mimicking Odoo addons and a dummy odoo.conf."""
    base_path = tmp_path_factory.mktemp("dummy_addons_env")
    addons_path = base_path / "addons"
    addons_path.mkdir()

    # Addon A depends on B and base_addon
    addon_a_path = addons_path / "addon_a"
    addon_a_path.mkdir()
    (addon_a_path / "__init__.py").write_text("# addon_a init\nimport models\n")
    (addon_a_path / "__manifest__.py").write_text(
        "{'name': 'Addon A', 'version': '16.0.1.0.0', 'depends': ['base_addon', 'addon_b'], 'installable': True}"
    )
    (addon_a_path / "models").mkdir()
    (addon_a_path / "models" / "__init__.py").write_text("# addon_a models init\nfrom . import a_model\n")
    (addon_a_path / "models" / "a_model.py").write_text("class AModel:\n    pass # A's model\n")
    (addon_a_path / "views").mkdir()
    (addon_a_path / "views" / "a_view.xml").write_text("<odoo><data name='A_VIEW'/></odoo>")

    # Addon B depends on base_addon
    addon_b_path = addons_path / "addon_b"
    addon_b_path.mkdir()
    (addon_b_path / "__init__.py").write_text("# addon_b init\n") # Trivial init
    (addon_b_path / "__manifest__.py").write_text(
        "{'name': 'Addon B', 'version': '16.0.1.0.0', 'depends': ['base_addon'], 'installable': True}"
    )
    (addon_b_path / "models").mkdir()
    (addon_b_path / "models" / "__init__.py").write_text("from . import b_model") # Trivial for parsing test
    (addon_b_path / "models" / "b_model.py").write_text("class BModel:\n    pass # B's model\n")
    (addon_b_path / "wizard").mkdir()
    (addon_b_path / "wizard" / "b_wizard.xml").write_text("<odoo><data name='B_WIZARD'/></odoo>")

    # Addon C (no deps)
    addon_c_path = addons_path / "addon_c"
    addon_c_path.mkdir()
    (addon_c_path / "__init__.py").touch()
    (addon_c_path / "__manifest__.py").write_text(
        "{'name': 'Addon C', 'version': '16.0.1.0.0', 'depends': [], 'installable': True}"
    )
    (addon_c_path / "security").mkdir()
    (addon_c_path / "security" / "ir.model.access.csv").write_text("id,name\naccess_c,access_c\n")

    # base_addon (simulates 'base' for dependency checks, not necessarily for core filtering)
    base_addon_path = addons_path / "base_addon" # Named differently to avoid manifestoo thinking it's THE odoo 'base'
    base_addon_path.mkdir()
    (base_addon_path / "__init__.py").touch()
    (base_addon_path / "__manifest__.py").write_text(
        "{'name': 'Base Addon', 'version': '16.0.1.0.0', 'depends': [], 'installable': True}"
    )
    (base_addon_path / "models").mkdir()
    (base_addon_path / "models" / "base_model.py").write_text("class BaseCoreModel:\n    pass\n")


    # Framework addon (for testing exclude_framework) - let's use 'mail' from FRAMEWORK_ADDONS
    # Ensure one of the FRAMEWORK_ADDONS is present for the test
    framework_addon_name = "mail" # Must be in FRAMEWORK_ADDONS
    assert framework_addon_name in FRAMEWORK_ADDONS, f"{framework_addon_name} must be in cli.FRAMEWORK_ADDONS"
    framework_addon_path = addons_path / framework_addon_name
    framework_addon_path.mkdir()
    (framework_addon_path / "__init__.py").touch()
    (framework_addon_path / "__manifest__.py").write_text(
         f"{{'name': '{framework_addon_name.capitalize()}', 'version': '16.0.1.0.0', 'depends': ['base_addon'], 'installable': True}}"
    )
    (framework_addon_path / "models").mkdir()
    (framework_addon_path / "models" / f"{framework_addon_name}_model.py").write_text(f"class {framework_addon_name.capitalize()}Model:\n    pass\n")
    # Make addon_a depend on this framework addon to test exclusion
    addon_a_manifest_path = addon_a_path / "__manifest__.py"
    addon_a_manifest_content = addon_a_manifest_path.read_text()
    addon_a_manifest_content = addon_a_manifest_content.replace("'addon_b']", f"'addon_b', '{framework_addon_name}']")
    addon_a_manifest_path.write_text(addon_a_manifest_content)


    # Dummy odoo.conf
    odoo_conf_path = base_path / "dummy_odoo.conf"
    # odoo_conf_path.write_text(f"addons_path = {addons_path}\n")
    odoo_conf_path.write_text(f"[options]\naddons_path = {str(addons_path)}\n")

    return {
        "addons_path": addons_path,
        "odoo_conf": odoo_conf_path,
        "addon_a_path": addon_a_path,
        "addon_b_path": addon_b_path,
        "base_addon_path": base_addon_path,
        "framework_addon_path": framework_addon_path,
    }


def _run_cli(args, catch_exceptions=False):
    """Helper to run CLI commands and print output for debugging."""
    result = runner.invoke(app, args, catch_exceptions=catch_exceptions)
    print(f"\nCOMMAND: akaidoo {' '.join(args)}")
    print("STDOUT:", result.stdout)
    if result.stderr: # Only print stderr if it's not empty
      print("STDERR:", result.stderr)
    if result.exception:
      print("EXCEPTION:", result.exception)
    return result

def _get_file_names_from_output(output_str, separator=","):
    """Extracts unique file names from the comma-separated output string."""
    if not output_str.strip():
        return set()
    return {Path(p).name for p in output_str.strip().split(separator) if p}

# --- Tests ---

def test_list_files_help():
    """Test the help message."""
    result = _run_cli(["list-files", "--help"])
    assert result.exit_code == 0
    assert "Usage: akaidoo list-files [OPTIONS] ADDON_NAME" in result.stdout
    assert "--only-target-addon" in result.stdout
    assert "--editor-cmd" in result.stdout


def test_list_files_basic_addons_path(dummy_addons_env):
    """Test basic file listing for addon_a and its dependencies using --addons-path."""
    args = [
        "list-files", "addon_a",
        "--addons-path", str(dummy_addons_env["addons_path"]),
        "--no-addons-path-from-import-odoo", # Isolate test
        "--odoo-series", "16.0",
        "--separator", ",",
        "--no-exclude-framework", # Include framework by default for this test
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    output_files = _get_file_names_from_output(result.stdout)

    expected_present = {
        "a_model.py", "a_view.xml",             # From addon_a
        "b_model.py", "b_wizard.xml",           # From addon_b
        "base_model.py",                        # From base_addon
        f"{dummy_addons_env['framework_addon_path'].name}_model.py", # From framework addon ('mail_model.py')
        "__init__.py", # Will be multiple, check presence generally
    }
    # __init__.py from addon_a root, addon_a/models, addon_b root, addon_b/models, base_addon/models
    # addon_a/__init__.py is NOT trivial
    # addon_a/models/__init__.py is NOT trivial
    # addon_b/__init__.py IS trivial (should be skipped)
    # addon_b/models/__init__.py IS trivial (should be skipped)

    assert output_files.issuperset(expected_present)
    assert "ir.model.access.csv" not in output_files # From addon_c

    # Check for non-trivial __init__.py files by full path
    addon_a_root_init = dummy_addons_env["addon_a_path"] / "__init__.py"
    addon_a_models_init = dummy_addons_env["addon_a_path"] / "models" / "__init__.py"
    # Trivial inits that should be skipped
    addon_b_root_init = dummy_addons_env["addon_b_path"] / "__init__.py"
    addon_b_models_init = dummy_addons_env["addon_b_path"] / "models" / "__init__.py"

    output_full_paths = {p.strip() for p in result.stdout.strip().split(',') if p}
    assert str(addon_a_root_init.resolve()) in output_full_paths
    assert str(addon_a_models_init.resolve()) in output_full_paths
    assert str(addon_b_root_init.resolve()) not in output_full_paths # Trivial
    assert str(addon_b_models_init.resolve()) not in output_full_paths # Trivial


def test_list_files_odoo_conf(dummy_addons_env):
    """Test using --odoo-cfg."""
    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series", "16.0",
        "--separator", ",",
        "--no-exclude-framework",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    output_files = _get_file_names_from_output(result.stdout)
    assert "a_model.py" in output_files
    assert "b_model.py" in output_files


def test_list_files_only_models(dummy_addons_env):
    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--only-models", "--separator", ",",
        "--no-exclude-framework",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    output_files = _get_file_names_from_output(result.stdout)
    expected_models = {
        "a_model.py", "b_model.py", "base_model.py",
        f"{dummy_addons_env['framework_addon_path'].name}_model.py",
        # __init__.py from models dirs (non-trivial one from addon_a/models)
        "__init__.py"
        }
    assert output_files.issuperset(expected_models)
    assert "a_view.xml" not in output_files
    assert "b_wizard.xml" not in output_files


def test_list_files_no_wizards(dummy_addons_env):
    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--no-include-wizards", "--separator", ",",
        "--no-exclude-framework",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    output_files = _get_file_names_from_output(result.stdout)
    assert "a_model.py" in output_files
    assert "a_view.xml" in output_files
    assert "b_model.py" in output_files
    assert "b_wizard.xml" not in output_files


def test_list_files_only_target_addon(dummy_addons_env):
    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--only-target-addon", "--separator", ",",
        "--no-exclude-framework", # Ensure framework exclusion doesn't hide addon_a parts
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    output_files = _get_file_names_from_output(result.stdout)
    expected_addon_a_files = {"__init__.py", "a_model.py", "a_view.xml"}
    assert output_files.issuperset(expected_addon_a_files)
    # Files from dependencies should NOT be present
    assert "b_model.py" not in output_files
    assert "b_wizard.xml" not in output_files
    assert "base_model.py" not in output_files
    assert f"{dummy_addons_env['framework_addon_path'].name}_model.py" not in output_files


def test_list_files_exclude_framework(dummy_addons_env):
    """Test excluding framework addons (e.g., mail)."""
    # Addon A depends on 'mail' (a framework addon in our setup)
    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--exclude-framework", # This is the key flag, default is True
        "--separator", ",",
    ]
    result = _run_cli(args, catch_exceptions=True) # catch exceptions to see if any
    assert result.exit_code == 0
    output_files = _get_file_names_from_output(result.stdout)

    # Files from addon_a and addon_b and base_addon should be present
    assert "a_model.py" in output_files
    assert "b_model.py" in output_files
    assert "base_model.py" in output_files
    # File from the framework addon ('mail') should be EXCLUDED by path check
    assert f"{dummy_addons_env['framework_addon_path'].name}_model.py" not in output_files

def test_list_files_no_exclude_framework(dummy_addons_env):
    """Test including framework addons when --no-exclude-framework is passed."""
    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--no-exclude-framework", # Explicitly include framework addons
        "--separator", ",",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    output_files = _get_file_names_from_output(result.stdout)
    assert f"{dummy_addons_env['framework_addon_path'].name}_model.py" in output_files


@pytest.mark.skipif(sys.platform == "win32", reason="Clipboard tests are tricky on Windows CI")
def test_list_files_clipboard(dummy_addons_env, mocker):
    """Test copying to clipboard."""
    mock_pyperclip_copy = mocker.patch("akaidoo.cli.pyperclip.copy")
    # Ensure pyperclip is not None for this test
    mocker.patch("akaidoo.cli.pyperclip", create=True) # Mocks the module itself if it was None

    args = [
        "list-files", "addon_c", # A small addon
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--clipboard",
        "--no-exclude-framework",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    mock_pyperclip_copy.assert_called_once()
    clipboard_content = mock_pyperclip_copy.call_args[0][0]
    assert "# FILEPATH:" in clipboard_content
    assert "ir.model.access.csv" in clipboard_content # Check for a file from addon_c


def test_list_files_output_file(dummy_addons_env, tmp_path):
    """Test writing to an output file."""
    output_file = tmp_path / "output.txt"
    args = [
        "list-files", "addon_c",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--output-file", str(output_file),
        "--no-exclude-framework",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    assert output_file.exists()
    content = output_file.read_text()
    assert "# FILEPATH:" in content
    assert "ir.model.access.csv" in content


def test_list_files_edit_mode(dummy_addons_env, mocker):
    """Test launching editor."""
    mock_subprocess_run = mocker.patch("akaidoo.cli.subprocess.run")
    # Mock environment variables for editor
    mocker.patch.dict(os.environ, {"VISUAL": "myeditor", "EDITOR": "fallbackeditor"})

    args = [
        "list-files", "addon_c",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--edit",
        "--no-exclude-framework",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0 # Should exit after trying to launch editor
    mock_subprocess_run.assert_called_once()
    called_cmd = mock_subprocess_run.call_args[0][0]
    assert called_cmd[0] == "myeditor" # Should pick VISUAL
    assert any("ir.model.access.csv" in arg for arg in called_cmd)

def test_list_files_edit_mode_custom_cmd(dummy_addons_env, mocker):
    """Test launching editor with --editor-cmd."""
    mock_subprocess_run = mocker.patch("akaidoo.cli.subprocess.run")
    args = [
        "list-files", "addon_c",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--edit", "--editor-cmd", "customvim -p",
        "--no-exclude-framework",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    mock_subprocess_run.assert_called_once()
    called_cmd = mock_subprocess_run.call_args[0][0]
    assert called_cmd[0] == "customvim"
    assert called_cmd[1] == "-p"


def test_mutually_exclusive_outputs(dummy_addons_env):
    """Test that output modes are mutually exclusive."""
    args_clipboard_output = [
        "list-files", "addon_c", "-c", str(dummy_addons_env["odoo_conf"]),
        "--clipboard", "--output-file", "out.txt"
    ]
    result1 = _run_cli(args_clipboard_output)
    assert result1.exit_code == 1
    assert "Please choose only one primary output action" in result1.stderr

    args_edit_output = [
        "list-files", "addon_c", "-c", str(dummy_addons_env["odoo_conf"]),
        "--edit", "--output-file", "out.txt"
    ]
    result2 = _run_cli(args_edit_output)
    assert result2.exit_code == 1
    assert "Please choose only one primary output action" in result2.stderr

    args_edit_clipboard = [
        "list-files", "addon_c", "-c", str(dummy_addons_env["odoo_conf"]),
        "--edit", "--clipboard"
    ]
    result3 = _run_cli(args_edit_clipboard)
    assert result3.exit_code == 1
    assert "Please choose only one primary output action" in result3.stderr


def test_list_files_missing_addon(dummy_addons_env):
    args = [
        "list-files", "non_existent_addon",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
    ]
    result = _run_cli(args)
    assert result.exit_code == 1
    assert "Addon 'non_existent_addon' not found" in result.stderr


def test_trivial_init_skipping(dummy_addons_env):
    """Explicitly test that trivial __init__.py files are skipped."""
    # addon_b/__init__.py is trivial
    # addon_b/models/__init__.py is trivial
    # addon_a/__init__.py is NOT trivial
    # addon_a/models/__init__.py is NOT trivial

    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--separator", ",",
        "--no-exclude-framework",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0

    output_full_paths = {p.strip() for p in result.stdout.strip().split(',') if p}

    addon_a_root_init = dummy_addons_env["addon_a_path"] / "__init__.py"
    addon_a_models_init = dummy_addons_env["addon_a_path"] / "models" / "__init__.py"
    addon_b_root_init = dummy_addons_env["addon_b_path"] / "__init__.py"
    addon_b_models_init = dummy_addons_env["addon_b_path"] / "models" / "__init__.py"

    assert str(addon_a_root_init.resolve()) in output_full_paths    # Non-trivial
    assert str(addon_a_models_init.resolve()) in output_full_paths # Non-trivial
    assert str(addon_b_root_init.resolve()) not in output_full_paths    # Trivial
    assert str(addon_b_models_init.resolve()) not in output_full_paths # Trivial

# Potential improvements for cli.py based on writing these tests:
# 1.  Verbosity: Ensure all echo.debug/info/warning calls correctly respect the verbosity level set globally.
#     The `common` callback correctly sets `manifestoo.echo.verbosity`. The internal `echo.X` calls should then
#     honor this.
# 2.  `--exclude-framework`: This logic currently happens during file path checking.
#     If you wanted to exclude *all* files from a framework addon (even if it wasn't a direct dependency but
#     a transitive one whose files might otherwise be scanned), the filtering of `target_addons` (Step 3)
#     would be a more robust place to remove framework addon names entirely.
#     However, the current path-based check for `/addons/framework_name/` is also a valid approach, especially
#     if framework modules can live outside the main `/addons` dir (e.g. in Odoo's own structure).
# 3.  Short option for `--only-target-addon`: You gave it `-s`, but `-s` is already used by `--separator`.
#     This will cause a conflict. Typer usually detects this. You'll need to choose a different short option
#     (e.g., `-T`) or remove it. I've removed `-s` from `--only-target-addon` in my head for these tests.
# 4.  Conflicting `elif clipboard and output_file:` check:
#     The check `elif clipboard and output_file:` in the output section will never be true because of the
#     `output_actions_count` check earlier that would exit if both are true. This can be simplified.
#     The primary `if edit_in_editor:` then `elif clipboard:` then `elif output_file:` else `print_list`
#     structure is correct due to the `output_actions_count` check at the top of that block.
