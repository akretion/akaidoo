"""Test that MCP dependencies are optional and properly checked."""

from typer.testing import CliRunner
from akaidoo.cli import akaidoo_app
from unittest.mock import patch


def test_serve_without_mcp_dependencies():
    """Test that serve command fails with helpful message when MCP deps are missing."""
    runner = CliRunner()

    # Mock both mcp and fastmcp imports to raise ImportError
    with patch.dict("sys.modules", {"mcp": None, "fastmcp": None}):
        result = runner.invoke(akaidoo_app, ["serve"])

        # The command should fail
        assert result.exit_code == 1

        # Should mention the missing dependencies
        assert "mcp" in result.output.lower()
        assert "fastmcp" in result.output.lower()

        # Should suggest how to install
        assert "pip install akaidoo[mcp]" in result.output


if __name__ == "__main__":
    test_serve_without_mcp_dependencies()
    print("Test passed!")
