"""Shell script executor with standard and admin elevation support."""

import subprocess


class CloneError(Exception):
    """Raised when an executor command fails."""

    pass


class Runner:
    """Executes shell scripts directly or with administrator privileges."""

    @staticmethod
    def run(script: str, needs_admin: bool = False) -> str:
        """Execute a shell script directly or via osascript with admin elevation.

        Args:
            script: The shell command or script to execute.
            needs_admin: If True, execute via osascript with administrator privileges.

        Returns:
            The standard output (and standard error) of the execution as a string.

        Raises:
            CloneError: If the script fails or returns a non-zero exit code.
        """
        if needs_admin:
            return Runner._run_as_admin(script)
        else:
            return Runner._run_direct(script)

    @staticmethod
    def _run_direct(script: str, timeout: int = 300) -> str:
        """Run script directly via subprocess in a shell."""
        try:
            return subprocess.check_output(
                script, shell=True, stderr=subprocess.STDOUT, text=True, timeout=timeout
            )
        except subprocess.CalledProcessError as e:
            raise CloneError(f"Command failed (exit {e.returncode}):\n{e.output}") from e
        except subprocess.TimeoutExpired as e:
            raise CloneError(f"Command timed out after {timeout}s") from e

    @staticmethod
    def _run_as_admin(script: str, timeout: int = 300) -> str:
        """Run script using AppleScript osascript with administrator privileges."""
        import os
        import tempfile

        # If script is multiline, write to a secure temporary script file to avoid
        # AppleScript multiline syntax errors and command-line length limits.
        if "\n" in script.strip():
            with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
                f.write(script)
                temp_path = f.name
            try:
                os.chmod(temp_path, 0o700)
                escaped_path = temp_path.replace("\\", "\\\\").replace('"', '\\"')
                applescript = f'do shell script "/bin/bash \\"{escaped_path}\\"" with administrator privileges'
                return subprocess.check_output(
                    ["/usr/bin/osascript", "-e", applescript],
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as e:
                raise CloneError(f"Admin command timed out after {timeout}s") from e
            except subprocess.CalledProcessError as e:
                raise CloneError(f"Admin command failed:\n{e.output}") from e
            finally:
                try:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                except OSError:
                    pass
        else:
            escaped = script.replace("\\", "\\\\").replace('"', '\\"')
            applescript = f'do shell script "{escaped}" with administrator privileges'
            try:
                return subprocess.check_output(
                    ["/usr/bin/osascript", "-e", applescript],
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as e:
                raise CloneError(f"Admin command timed out after {timeout}s") from e
            except subprocess.CalledProcessError as e:
                raise CloneError(f"Admin command failed:\n{e.output}") from e
