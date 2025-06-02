import re
import sys
from pathlib import Path
import os

import pytest
from typer.testing import CliRunner
import typer  # Import Typer for creating a test app

# Import the specific command function directly from your cli.py
try:
    from akaidoo.cli import akaidoo_command_entrypoint
    from akaidoo.cli import pyperclip as actual_pyperclip_in_cli_module
except ImportError as e:
    print(f"DEBUG: Test setup ImportError: {e}")
    print(f"DEBUG: sys.path is: {sys.path}")
    pytest.skip(
        "Skipping CLI tests, akaidoo.cli or akaidoo_command_entrypoint not found",
        allow_module_level=True,
    )


def strip_ansi_codes(s: str) -> str:
    return re.sub(
        r"\x1b\[([0-9,A-Z]{1,2}(;[0-9]{1,2})?(;[0-9]{3})?)?[m|K|H|f|J]", "", s
    )


runner = CliRunner()

# This test_app will wrap your command function for CliRunner
# test_app = typer.Typer(add_completion=False, no_args_is_help=False) # Keep it simple for tests
# test_app.command(name="akaidoo_test_cmd", help="Test wrapper")(akaidoo_command_entrypoint)

test_app = typer.Typer(
    help="Akaidoo Test App Wrapper",  # Help for the wrapper app
    add_completion=False,
    no_args_is_help=True,  # If `akaidoo` (test_app) is run with no command, it shows its own help
)
# Register akaidoo_command_entrypoint as a command of test_app.
# This is how CliRunner can properly discover and invoke it as a command.
test_app.command(name="run")(
    akaidoo_command_entrypoint
)  # Use a simple name like "run" or keep "akaidoo_test_cmd"

# The name="akaidoo_test_cmd" is arbitrary for the test wrapper;
# CliRunner will invoke this when given the test_app.
# If you want to test the exact `akaidoo` command name as the entry point,
# the prog_name in runner.invoke handles that.


# --- Test Setup ---
@pytest.fixture(scope="module")
def dummy_addons_env(tmp_path_factory):
    # ... (your existing fixture is fine, no changes needed there) ...
    base_path = tmp_path_factory.mktemp("dummy_addons_env")
    addons_path = base_path / "addons"
    addons_path.mkdir()

    addon_a_path = addons_path / "addon_a"
    addon_a_path.mkdir()
    (addon_a_path / "__init__.py").write_text(
        "# addon_a init\nimport models\nCONSTANT_IN_A_INIT = True\n"
    )
    (addon_a_path / "__manifest__.py").write_text(
        "{'name': 'Addon A', 'version': '16.0.1.0.0', 'depends': ['base_addon', 'addon_b'], 'installable': True}"
    )
    (addon_a_path / "models").mkdir()
    (addon_a_path / "models" / "__init__.py").write_text(
        "# addon_a models init\nfrom . import a_model\nVALUE_IN_MODELS_INIT = 1\n"
    )
    (addon_a_path / "models" / "a_model.py").write_text(
        "class AModel:\n    pass # A's model\n"
    )
    (addon_a_path / "views").mkdir()
    (addon_a_path / "views" / "a_view.xml").write_text(
        "<odoo><data name='A_VIEW'/></odoo>"
    )

    addon_b_path = addons_path / "addon_b"
    addon_b_path.mkdir()
    (addon_b_path / "__init__.py").write_text("# addon_b init\n")
    (addon_b_path / "__manifest__.py").write_text(
        "{'name': 'Addon B', 'version': '16.0.1.0.0', 'depends': ['base_addon'], 'installable': True}"
    )
    (addon_b_path / "models").mkdir()
    (addon_b_path / "models" / "__init__.py").write_text(
        "# from . import b_model\n# only comments and imports"
    )
    (addon_b_path / "models" / "b_model.py").write_text(
        "class BModel:\n    pass # B's model\n"
    )
    (addon_b_path / "wizard").mkdir()
    (addon_b_path / "wizard" / "b_wizard.xml").write_text(
        "<odoo><data name='B_WIZARD'/></odoo>"
    )

    addon_c_path = addons_path / "addon_c"
    addon_c_path.mkdir()
    (addon_c_path / "__init__.py").touch()
    (addon_c_path / "__manifest__.py").write_text(
        "{'name': 'Addon C', 'version': '16.0.1.0.0', 'depends': [], 'installable': True}"
    )
    (addon_c_path / "security").mkdir()
    (addon_c_path / "security" / "ir.model.access.csv").write_text(
        "id,name\naccess_c,access_c\n"
    )

    base_addon_path = addons_path / "base_addon"
    base_addon_path.mkdir()
    (base_addon_path / "__init__.py").touch()
    (base_addon_path / "__manifest__.py").write_text(
        "{'name': 'Base Addon', 'version': '16.0.1.0.0', 'depends': [], 'installable': True}"
    )
    (base_addon_path / "models").mkdir()
    (base_addon_path / "models" / "base_model.py").write_text(
        "class BaseCoreModel:\n    pass\n"
    )

    framework_addon_name = "mail"
    framework_addon_path = addons_path / framework_addon_name
    framework_addon_path.mkdir()
    (framework_addon_path / "__init__.py").touch()
    (framework_addon_path / "__manifest__.py").write_text(
        f"{{'name': '{framework_addon_name.capitalize()}', 'version': '16.0.1.0.0', 'depends': ['base_addon'], 'installable': True}}"
    )
    (framework_addon_path / "models").mkdir()
    (framework_addon_path / "models" / f"{framework_addon_name}_model.py").write_text(
        f"class {framework_addon_name.capitalize()}Model:\n    pass\n"
    )
    (framework_addon_path / "models" / "__init__.py").write_text(
        f"# Trivial models init for {framework_addon_name}\n"
    )

    addon_a_manifest_path = addon_a_path / "__manifest__.py"
    addon_a_manifest_content_str = addon_a_manifest_path.read_text()
    try:
        manifest_dict = eval(addon_a_manifest_content_str)
        if (
            isinstance(manifest_dict, dict)
            and "depends" in manifest_dict
            and isinstance(manifest_dict["depends"], list)
        ):
            if framework_addon_name not in manifest_dict["depends"]:
                manifest_dict["depends"].append(framework_addon_name)
            addon_a_manifest_path.write_text(str(manifest_dict))
        else:  # Fallback for simple string manipulation if eval is not clean
            if "'depends': [" in addon_a_manifest_content_str:
                addon_a_manifest_content_str = addon_a_manifest_content_str.replace(
                    "'depends': ['base_addon', 'addon_b']",
                    f"'depends': ['base_addon', 'addon_b', '{framework_addon_name}']",
                ).replace(
                    "'depends': ['addon_b', 'base_addon']",
                    f"'depends': ['addon_b', 'base_addon', '{framework_addon_name}']",
                )
            else:  # If 'depends' key itself is missing
                addon_a_manifest_content_str = (
                    addon_a_manifest_content_str.rstrip("}")
                    + f", 'depends': ['{framework_addon_name}']}}"
                )

            addon_a_manifest_path.write_text(addon_a_manifest_content_str)

    except Exception as e:
        print(f"Warning: Error processing manifest for addon_a: {e}")

    odoo_conf_path = base_path / "dummy_odoo.conf"
    odoo_conf_path.write_text(f"[options]\naddons_path = {str(addons_path)}\n")

    return {
        "addons_path": addons_path,
        "odoo_conf": odoo_conf_path,
        "addon_a_path": addon_a_path,
        "addon_b_path": addon_b_path,
        "base_addon_path": base_addon_path,
        "framework_addon_path": framework_addon_path,
        "framework_addon_name": framework_addon_name,
    }


def _run_cli(args, catch_exceptions=False, expected_exit_code=None):
    str_args = [str(a) for a in args]
    print(f"\nCOMMAND: akaidoo {' '.join(str_args)}")

    # Invoke the test_app which wraps akaidoo_command_entrypoint
    result = runner.invoke(
        test_app, str_args, prog_name="akaidoo", catch_exceptions=catch_exceptions
    )

    print("STDOUT:", result.stdout)
    actual_stderr = ""
    if result.stderr_bytes:
        actual_stderr = result.stderr
        print("STDERR:", actual_stderr)
    elif result.exit_code != 0 and result.stdout and not result.stderr_bytes:
        print("STDERR (Note: Typer/Click error to stdout):", result.stdout)
        actual_stderr = result.stdout
    else:
        print("STDERR: (empty)")

    result.processed_stderr = actual_stderr

    if result.exception and not catch_exceptions:
        print("EXCEPTION:", result.exception)
        if not isinstance(result.exception, SystemExit):
            raise result.exception

    if expected_exit_code is not None:
        assert (
            result.exit_code == expected_exit_code
        ), f"Expected exit code {expected_exit_code} but got {result.exit_code}. STDERR: '{result.processed_stderr}' STDOUT: '{result.stdout}'"

    return result


def _get_file_names_from_output(output_str, separator=","):
    if not output_str.strip():
        return set()
    return {
        Path(p.strip()).name for p in output_str.strip().split(separator) if p.strip()
    }


# --- Tests ---


def test_main_help():
    # Invoke help on the test_app
    result = runner.invoke(test_app, ["--help"], prog_name="akaidoo")
    assert result.exit_code == 0
    stdout_clean = strip_ansi_codes(result.stdout)
    print(
        f"DEBUG: Cleaned STDOUT for help test:\n{stdout_clean}"
    )  # For debugging in CI
    # The Usage string comes from how Typer wraps akaidoo_command_entrypoint
    # Because akaidoo_command_entrypoint is now a command *of* test_app,
    # the help might show "Usage: akaidoo akaidoo_test_cmd [OPTIONS] ADDON_NAME"
    # or similar. Or, if test_app has no other commands, it might be simpler.
    # Let's check for the core parts.
    assert "Usage: akaidoo" in stdout_clean  # It will use prog_name
    assert "[OPTIONS] ADDON_NAME" in stdout_clean  # Key part
    # The main help might come from test_app's help or the command's docstring.
    # Let's check for options of akaidoo_command_entrypoint:
    # assert "--only-target-addon" in result.stdout
    assert "-l" in stdout_clean
    if result.stderr_bytes:
        print("STDERR from test_main_help:", result.stderr)
    assert not result.stderr_bytes


# ... (The rest of your tests should remain unchanged as their `args` list
#      correctly starts with `addon_name` which will be passed to `akaidoo_command_entrypoint`)


def test_list_files_basic_addons_path(dummy_addons_env):
    args = [
        "addon_a",
        "--addons-path",
        str(dummy_addons_env["addons_path"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--separator",
        ",",
        "--no-exclude-framework",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files_basenames = _get_file_names_from_output(result.stdout)

    expected_present_basenames = {
        "a_model.py",
        "a_view.xml",
        "b_model.py",
        "b_wizard.xml",
        "base_model.py",
        f"{dummy_addons_env['framework_addon_name']}_model.py",
        "__init__.py",
        "__manifest__.py",
    }
    assert output_files_basenames.issuperset(expected_present_basenames)
    assert "ir.model.access.csv" not in output_files_basenames

    output_full_paths = {p.strip() for p in result.stdout.strip().split(",") if p}
    addon_a_root_init = dummy_addons_env["addon_a_path"] / "__init__.py"
    addon_a_models_init = dummy_addons_env["addon_a_path"] / "models" / "__init__.py"
    addon_b_root_init = dummy_addons_env["addon_b_path"] / "__init__.py"
    addon_b_models_init = dummy_addons_env["addon_b_path"] / "models" / "__init__.py"
    framework_addon_root_init = dummy_addons_env["framework_addon_path"] / "__init__.py"
    framework_addon_models_init = (
        dummy_addons_env["framework_addon_path"] / "models" / "__init__.py"
    )

    assert str(addon_a_root_init.resolve()) in output_full_paths
    assert str(addon_a_models_init.resolve()) in output_full_paths
    assert str(addon_b_root_init.resolve()) not in output_full_paths
    assert str(addon_b_models_init.resolve()) not in output_full_paths
    assert str(framework_addon_root_init.resolve()) not in output_full_paths
    assert str(framework_addon_models_init.resolve()) not in output_full_paths


def test_list_files_odoo_conf(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--separator",
        ",",
        "--no-exclude-framework",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    assert "a_model.py" in output_files
    assert "b_model.py" in output_files


def test_list_files_only_models(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--only-models",
        "--separator",
        ",",
        "--no-exclude-framework",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    expected_models = {
        "a_model.py",
        "b_model.py",
        "base_model.py",
        f"{dummy_addons_env['framework_addon_name']}_model.py",
        "__init__.py",
    }
    assert output_files.issuperset(expected_models)
    assert "a_view.xml" not in output_files
    assert "b_wizard.xml" not in output_files

    output_full_paths_set = {
        Path(p.strip()).resolve() for p in result.stdout.strip().split(",") if p
    }
    addon_a_root_init_path = (
        dummy_addons_env["addon_a_path"] / "__init__.py"
    ).resolve()

    assert addon_a_root_init_path not in output_full_paths_set


def test_list_files_no_wizards(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--no-include-wizards",
        "--separator",
        ",",
        "--no-exclude-framework",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    assert "a_model.py" in output_files
    assert "a_view.xml" in output_files
    assert "b_model.py" in output_files
    assert "b_wizard.xml" not in output_files


def test_list_files_only_target_addon(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--only-target-addon",
        "--separator",
        ",",
        "--no-exclude-framework",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    expected_addon_a_files = {
        "__init__.py",
        "a_model.py",
        "a_view.xml",
        "__manifest__.py",
    }
    assert output_files.issuperset(expected_addon_a_files)
    addon_a_root_init_path = str(
        (dummy_addons_env["addon_a_path"] / "__init__.py").resolve()
    )
    addon_a_models_init_path = str(
        (dummy_addons_env["addon_a_path"] / "models" / "__init__.py").resolve()
    )
    stdout_paths = {p.strip() for p in result.stdout.strip().split(",") if p}
    assert addon_a_root_init_path in stdout_paths
    assert addon_a_models_init_path in stdout_paths
    assert "b_model.py" not in output_files
    assert "b_wizard.xml" not in output_files
    assert "base_model.py" not in output_files
    assert f"{dummy_addons_env['framework_addon_name']}_model.py" not in output_files


def test_list_files_exclude_framework(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--exclude-framework",
        "--separator",
        ",",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    assert "a_model.py" in output_files
    assert "b_model.py" in output_files
    assert "base_model.py" in output_files
    assert f"{dummy_addons_env['framework_addon_name']}_model.py" not in output_files


def test_list_files_no_exclude_framework(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--no-exclude-framework",
        "--separator",
        ",",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    assert f"{dummy_addons_env['framework_addon_name']}_model.py" in output_files


@pytest.mark.skipif(
    sys.platform == "win32", reason="Clipboard tests are tricky on Windows CI"
)
def test_list_files_clipboard(dummy_addons_env, mocker):
    mock_pyperclip_module_patch = mocker.patch("akaidoo.cli.pyperclip", create=True)

    if not hasattr(mock_pyperclip_module_patch, "copy"):
        mock_pyperclip_module_patch.copy = mocker.Mock()

    args = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--clipboard",
        "--no-exclude-framework",
    ]
    result = _run_cli(args, expected_exit_code=0)

    if actual_pyperclip_in_cli_module is not None:
        mock_pyperclip_module_patch.copy.assert_called_once()
        clipboard_content = mock_pyperclip_module_patch.copy.call_args[0][0]
        assert "# FILEPATH:" in clipboard_content
        assert "__manifest__.py" in clipboard_content
        assert "{'name': 'Addon C'" in clipboard_content
    elif actual_pyperclip_in_cli_module is None:
        assert "requires the 'pyperclip' library" in result.processed_stderr


def test_list_files_output_file(dummy_addons_env, tmp_path):
    output_file = tmp_path / "output.txt"
    args = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--output-file",
        str(output_file),
        "--no-exclude-framework",
    ]
    _run_cli(args, expected_exit_code=0)
    assert output_file.exists()
    content = output_file.read_text()
    assert "# FILEPATH:" in content
    assert "__manifest__.py" in content
    assert "{'name': 'Addon C'" in content


def test_list_files_edit_mode(dummy_addons_env, mocker):
    mock_run = mocker.patch("akaidoo.cli.subprocess.run")
    mock_process_result = mocker.Mock()
    mock_process_result.returncode = 0
    mock_run.return_value = mock_process_result

    mocker.patch.dict(os.environ, {"VISUAL": "myeditor", "EDITOR": "fallbackeditor"})

    args = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--edit",
        "--no-exclude-framework",
    ]
    _run_cli(args, expected_exit_code=0)
    mock_run.assert_called_once()
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd[0] == "myeditor"
    assert any(
        "__manifest__.py" in Path(arg).name
        for arg in called_cmd
        if isinstance(arg, str) and os.path.sep in arg
    )


def test_list_files_edit_mode_custom_cmd(dummy_addons_env, mocker):
    mock_run = mocker.patch("akaidoo.cli.subprocess.run")
    mock_process_result = mocker.Mock()
    mock_process_result.returncode = 0
    mock_run.return_value = mock_process_result

    args = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--edit",
        "--editor-cmd",
        "customvim -p",
        "--no-exclude-framework",
    ]
    _run_cli(args, expected_exit_code=0)
    mock_run.assert_called_once()
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd[0] == "customvim"
    assert called_cmd[1] == "-p"


def test_mutually_exclusive_outputs(dummy_addons_env):
    args_clipboard_output = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--clipboard",
        "--output-file",
        "out.txt",
    ]
    result1 = _run_cli(args_clipboard_output, expected_exit_code=1)
    assert "Please choose only one primary output action" in result1.processed_stderr

    args_edit_output = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--edit",
        "--output-file",
        "out.txt",
    ]
    result2 = _run_cli(args_edit_output, expected_exit_code=1)
    assert "Please choose only one primary output action" in result2.processed_stderr

    args_edit_clipboard = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--edit",
        "--clipboard",
    ]
    result3 = _run_cli(args_edit_clipboard, expected_exit_code=1)
    assert "Please choose only one primary output action" in result3.processed_stderr


def test_list_files_missing_addon(dummy_addons_env):
    args = [
        "non_existent_addon",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
    ]
    result = _run_cli(args, expected_exit_code=1)
    assert "Addon 'non_existent_addon' not found" in result.processed_stderr


def test_trivial_init_skipping(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--separator",
        ",",
        "--no-exclude-framework",
    ]
    result = _run_cli(args, expected_exit_code=0)

    output_full_paths = {p.strip() for p in result.stdout.strip().split(",") if p}

    addon_a_root_init = dummy_addons_env["addon_a_path"] / "__init__.py"
    addon_a_models_init = dummy_addons_env["addon_a_path"] / "models" / "__init__.py"
    addon_b_root_init = dummy_addons_env["addon_b_path"] / "__init__.py"
    addon_b_models_init = dummy_addons_env["addon_b_path"] / "models" / "__init__.py"
    framework_addon_root_init = dummy_addons_env["framework_addon_path"] / "__init__.py"
    framework_addon_models_init = (
        dummy_addons_env["framework_addon_path"] / "models" / "__init__.py"
    )

    assert str(addon_a_root_init.resolve()) in output_full_paths
    assert str(addon_a_models_init.resolve()) in output_full_paths
    assert str(addon_b_root_init.resolve()) not in output_full_paths
    assert str(addon_b_models_init.resolve()) not in output_full_paths
    assert str(framework_addon_root_init.resolve()) not in output_full_paths
    assert str(framework_addon_models_init.resolve()) not in output_full_paths
