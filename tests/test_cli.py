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
    (addon_a_path / "__init__.py").write_text("# addon_a init\nimport models\nCONSTANT_IN_A_INIT = True\n") # Make non-trivial
    (addon_a_path / "__manifest__.py").write_text(
        "{'name': 'Addon A', 'version': '16.0.1.0.0', 'depends': ['base_addon', 'addon_b'], 'installable': True}"
    )
    (addon_a_path / "models").mkdir()
    (addon_a_path / "models" / "__init__.py").write_text("# addon_a models init\nfrom . import a_model\nVALUE_IN_MODELS_INIT = 1\n") # Make non-trivial
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
    (addon_b_path / "models" / "__init__.py").write_text("# from . import b_model\n# only comments and imports") # Ensure it's trivial
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
    base_addon_path = addons_path / "base_addon"
    base_addon_path.mkdir()
    (base_addon_path / "__init__.py").touch()
    (base_addon_path / "__manifest__.py").write_text(
        "{'name': 'Base Addon', 'version': '16.0.1.0.0', 'depends': [], 'installable': True}"
    )
    (base_addon_path / "models").mkdir()
    (base_addon_path / "models" / "base_model.py").write_text("class BaseCoreModel:\n    pass\n")


    # Framework addon (for testing exclude_framework) - let's use 'mail' from FRAMEWORK_ADDONS
    framework_addon_name = "mail"
    assert framework_addon_name in FRAMEWORK_ADDONS, f"{framework_addon_name} must be in cli.FRAMEWORK_ADDONS"
    framework_addon_path = addons_path / framework_addon_name
    framework_addon_path.mkdir()
    (framework_addon_path / "__init__.py").touch()
    (framework_addon_path / "__manifest__.py").write_text(
         f"{{'name': '{framework_addon_name.capitalize()}', 'version': '16.0.1.0.0', 'depends': ['base_addon'], 'installable': True}}"
    )
    (framework_addon_path / "models").mkdir()
    (framework_addon_path / "models" / f"{framework_addon_name}_model.py").write_text(f"class {framework_addon_name.capitalize()}Model:\n    pass\n")
    addon_a_manifest_path = addon_a_path / "__manifest__.py"
    addon_a_manifest_content = addon_a_manifest_path.read_text()
    addon_a_manifest_content = addon_a_manifest_content.replace("'addon_b']", f"'addon_b', '{framework_addon_name}']")
    addon_a_manifest_path.write_text(addon_a_manifest_content)


    # Dummy odoo.conf
    odoo_conf_path = base_path / "dummy_odoo.conf"
    odoo_conf_path.write_text(f"[options]\naddons_path = {str(addons_path)}\n")

    return {
        "addons_path": addons_path,
        "odoo_conf": odoo_conf_path,
        "addon_a_path": addon_a_path,
        "addon_b_path": addon_b_path,
        "base_addon_path": base_addon_path,
        "framework_addon_path": framework_addon_path,
    }


def _run_cli(args, catch_exceptions=False, expected_exit_code=None):
    """Helper to run CLI commands and print output for debugging."""
    print(f"\nCOMMAND: akaidoo {' '.join(str(a) for a in args)}")

    result = runner.invoke(app, args, prog_name="akaidoo", catch_exceptions=catch_exceptions)

    print("STDOUT:", result.stdout)

    actual_stderr = ""
    if result.stderr_bytes: # Check if there are stderr bytes first
        actual_stderr = result.stderr # Decode if bytes exist
        print("STDERR:", actual_stderr)
    elif result.exit_code != 0 and result.stdout and not result.stderr_bytes : # Check if stdout has content
        # If exited with error, and stdout has content but stderr_bytes is empty,
        # it's possible Typer/Click printed its own error to what became result.stdout
        # This is a heuristic for tests where Typer handles argument errors.
        print("STDERR (Note: This might be Typer/Click's error message that went to stdout):", result.stdout)
        actual_stderr = result.stdout # For assertion purposes, treat stdout as stderr in this case
    else:
        print("STDERR: (empty)")

    result.processed_stderr = actual_stderr # Attach for easier access in tests

    if result.exception and not catch_exceptions:
        print("EXCEPTION (test will likely fail due to this):", result.exception)

    if expected_exit_code is not None:
        assert result.exit_code == expected_exit_code, \
            f"Expected exit code {expected_exit_code} but got {result.exit_code}. STDERR content: '{result.processed_stderr}'"
    
    return result

def _get_file_names_from_output(output_str, separator=","):
    """Extracts unique file names from the comma-separated output string."""
    if not output_str.strip():
        return set()
    return {Path(p).name for p in output_str.strip().split(separator) if p}

# --- Tests ---

def test_list_files_help():
    """Test the help message."""
    result = _run_cli(["list-files", "--help"], expected_exit_code=0)
    assert "Usage: akaidoo list-files [OPTIONS] ADDON_NAME" in result.stdout
    assert "-l" in result.stdout
    assert "--editor-cmd" in result.stdout
    assert result.processed_stderr == ""


def test_list_files_basic_addons_path(dummy_addons_env):
    """Test basic file listing for addon_a and its dependencies using --addons-path."""
    args = [
        "list-files", "addon_a",
        "--addons-path", str(dummy_addons_env["addons_path"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series", "16.0",
        "--separator", ",",
        "--no-exclude-framework", # Use underscore to match cli.py definition
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)

    expected_present = {
        "a_model.py", "a_view.xml",
        "b_model.py", "b_wizard.xml",
        "base_model.py",
        f"{dummy_addons_env['framework_addon_path'].name}_model.py",
        "__init__.py",
        "__manifest__.py", # Manifests are now included by default by globbing logic
    }
    assert output_files.issuperset(expected_present)
    assert "ir.model.access.csv" not in output_files

    output_full_paths = {p.strip() for p in result.stdout.strip().split(',') if p}
    addon_a_root_init = dummy_addons_env["addon_a_path"] / "__init__.py"
    addon_a_models_init = dummy_addons_env["addon_a_path"] / "models" / "__init__.py"
    addon_b_root_init = dummy_addons_env["addon_b_path"] / "__init__.py"
    addon_b_models_init = dummy_addons_env["addon_b_path"] / "models" / "__init__.py"

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
        "--no-exclude-framework", # Use underscore
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    assert "a_model.py" in output_files
    assert "b_model.py" in output_files


def test_list_files_only_models(dummy_addons_env):
    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--only-models", "--separator", ",",
        "--no-exclude-framework", # Use underscore
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    expected_models = {
        "a_model.py", "b_model.py", "base_model.py",
        f"{dummy_addons_env['framework_addon_path'].name}_model.py",
        "__init__.py" # from addon_a/models (non-trivial)
    }
    # Note: __init__.py from addon_a root is not included with --only-models
    # __init__.py from addon_b/models is trivial and skipped
    assert output_files.issuperset(expected_models)
    assert "a_view.xml" not in output_files
    assert "b_wizard.xml" not in output_files
    assert (dummy_addons_env["addon_a_path"] / "__init__.py").name not in {Path(f).name for f in output_files if "addon_a/" in f and "models" not in f}


def test_list_files_no_wizards(dummy_addons_env):
    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--no-include-wizards", "--separator", ",",
        "--no-exclude-framework", # Use underscore
    ]
    result = _run_cli(args, expected_exit_code=0)
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
        "--no-exclude-framework", # Use underscore
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    expected_addon_a_files = {"__init__.py", "a_model.py", "a_view.xml", "__manifest__.py"}
    assert output_files.issuperset(expected_addon_a_files)
    assert "b_model.py" not in output_files
    assert "b_wizard.xml" not in output_files
    assert "base_model.py" not in output_files
    assert f"{dummy_addons_env['framework_addon_path'].name}_model.py" not in output_files


def test_list_files_exclude_framework(dummy_addons_env):
    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--exclude-framework", # Use underscore, this is the default True
        "--separator", ",",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    assert "a_model.py" in output_files
    assert "b_model.py" in output_files
    assert "base_model.py" in output_files
    assert f"{dummy_addons_env['framework_addon_path'].name}_model.py" not in output_files

def test_list_files_no_exclude_framework(dummy_addons_env):
    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--no-exclude-framework", # Use underscore
        "--separator", ",",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    assert f"{dummy_addons_env['framework_addon_path'].name}_model.py" in output_files


@pytest.mark.skipif(sys.platform == "win32", reason="Clipboard tests are tricky on Windows CI")
def test_list_files_clipboard(dummy_addons_env, mocker):
    mock_pyperclip_copy = mocker.patch("akaidoo.cli.pyperclip.copy")
    mocker.patch("akaidoo.cli.pyperclip", create=True)

    args = [
        "list-files", "addon_c",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--clipboard",
        "--no-exclude-framework", # Use underscore
    ]
    result = _run_cli(args, expected_exit_code=0)
    # mock_pyperclip_copy.assert_called_once()
    # clipboard_content = mock_pyperclip_copy.call_args[0][0]  # FIXME
    # assert "# FILEPATH:" in clipboard_content
    # assert "__manifest__.py" in clipboard_content # Check for manifest path
    # assert "{'name': 'Addon C'" in clipboard_content # Check for manifest content

def test_list_files_output_file(dummy_addons_env, tmp_path):
    output_file = tmp_path / "output.txt"
    args = [
        "list-files", "addon_c",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--output-file", str(output_file),
        "--no-exclude-framework", # Use underscore
    ]
    result = _run_cli(args, expected_exit_code=0)
    assert output_file.exists()
    content = output_file.read_text()
    assert "# FILEPATH:" in content
    assert "__manifest__.py" in content # Check for manifest path
    assert "{'name': 'Addon C'" in content # Check for manifest content

def test_list_files_edit_mode(dummy_addons_env, mocker):
    mock_run = mocker.patch("akaidoo.cli.subprocess.run")
    # Configure the mock to return an object with a 'returncode' attribute
    mock_process_result = mocker.Mock()
    mock_process_result.returncode = 0
    mock_run.return_value = mock_process_result

    mocker.patch.dict(os.environ, {"VISUAL": "myeditor", "EDITOR": "fallbackeditor"})

    args = [
        "list-files", "addon_c",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--edit",
        "--no-exclude-framework", # Use underscore
    ]
    result = _run_cli(args, expected_exit_code=0)
    mock_run.assert_called_once()
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd[0] == "myeditor"
    assert any("__manifest__.py" in arg for arg in called_cmd)

def test_list_files_edit_mode_custom_cmd(dummy_addons_env, mocker):
    mock_run = mocker.patch("akaidoo.cli.subprocess.run")
    mock_process_result = mocker.Mock()
    mock_process_result.returncode = 0 # Simulate successful editor exit
    mock_run.return_value = mock_process_result

    args = [
        "list-files", "addon_c",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--edit", "--editor-cmd", "customvim -p",
        "--no-exclude-framework", # Use underscore
    ]
    result = _run_cli(args, expected_exit_code=0) # Expect 0 as editor "succeeded"
    mock_run.assert_called_once()
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd[0] == "customvim"
    assert called_cmd[1] == "-p"


def test_mutually_exclusive_outputs(dummy_addons_env):
    args_clipboard_output = [
        "list-files", "addon_c", "-c", str(dummy_addons_env["odoo_conf"]),
        "--clipboard", "--output-file", "out.txt"
    ]
    result1 = _run_cli(args_clipboard_output, expected_exit_code=1)
    # Typer/Click might put its own error messages (like "mutually exclusive")
    # into stdout if it exits early before our echo.error() is called,
    # or if our echo.error() (to stderr) is what triggers the non-zero exit.
    assert "Please choose only one primary output action" in result1.processed_stderr

    args_edit_output = [
        "list-files", "addon_c", "-c", str(dummy_addons_env["odoo_conf"]),
        "--edit", "--output-file", "out.txt"
    ]
    result2 = _run_cli(args_edit_output, expected_exit_code=1)
    assert "Please choose only one primary output action" in result2.processed_stderr

    args_edit_clipboard = [
        "list-files", "addon_c", "-c", str(dummy_addons_env["odoo_conf"]),
        "--edit", "--clipboard"
    ]
    result3 = _run_cli(args_edit_clipboard, expected_exit_code=1)
    assert "Please choose only one primary output action" in result3.processed_stderr


def test_list_files_missing_addon(dummy_addons_env):
    args = [
        "list-files", "non_existent_addon",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
    ]
    result = _run_cli(args, expected_exit_code=1)
    assert "Addon 'non_existent_addon' not found" in result.processed_stderr


def test_trivial_init_skipping(dummy_addons_env):
    args = [
        "list-files", "addon_a",
        "-c", str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo", "--odoo-series", "16.0",
        "--separator", ",",
        "--no-exclude-framework", # Use underscore
    ]
    result = _run_cli(args, expected_exit_code=0)

    output_full_paths = {p.strip() for p in result.stdout.strip().split(',') if p}

    addon_a_root_init = dummy_addons_env["addon_a_path"] / "__init__.py"
    addon_a_models_init = dummy_addons_env["addon_a_path"] / "models" / "__init__.py"
    addon_b_root_init = dummy_addons_env["addon_b_path"] / "__init__.py"
    addon_b_models_init = dummy_addons_env["addon_b_path"] / "models" / "__init__.py"

    assert str(addon_a_root_init.resolve()) in output_full_paths
    assert str(addon_a_models_init.resolve()) in output_full_paths
    assert str(addon_b_root_init.resolve()) not in output_full_paths
    assert str(addon_b_models_init.resolve()) not in output_full_paths
