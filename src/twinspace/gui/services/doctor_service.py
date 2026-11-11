import asyncio
import subprocess

from twinspace.core.doctor import DoctorCheckItem, is_xcode_select_installed, run_all_checks
from twinspace.core.logger import get_logger

logger = get_logger("gui.doctor_service")

__all__ = ["DoctorCheckItem", "DoctorService"]


class DoctorService:
    async def check_xcode_select_installed(self) -> bool:
        """Non-blocking defensive check for active Xcode Command Line Tools."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, is_xcode_select_installed)

    async def trigger_xcode_install(self) -> tuple[bool, str]:
        """Trigger macOS native Xcode Command Line Tools installer dialog."""
        loop = asyncio.get_running_loop()

        def _install() -> tuple[bool, str]:
            logger.info("Triggering macOS native 'xcode-select --install' command")
            try:
                res = subprocess.run(
                    ["xcode-select", "--install"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                stdout = (res.stdout or "").strip()
                stderr = (res.stderr or "").strip()
                combined = f"{stdout}\n{stderr}".lower()

                if res.returncode == 0 or "install requested" in combined:
                    logger.info("xcode-select --install successfully requested")
                    return True, "launched"
                if "already installed" in combined:
                    logger.info("xcode-select tools are already installed or in progress")
                    return True, "already_installed"
                err_msg = stderr or stdout or f"Return code {res.returncode}"
                logger.warning(f"xcode-select --install failed: {err_msg}")
                return False, err_msg
            except Exception as e:
                logger.error(f"Exception invoking xcode-select --install: {e}")
                return False, str(e)

        return await loop.run_in_executor(None, _install)

    async def check_environment(self) -> list[DoctorCheckItem]:
        """Run the shared doctor check registry off the UI thread."""
        loop = asyncio.get_running_loop()
        logger.info("Running GUI environment diagnostic checks")
        return await loop.run_in_executor(None, run_all_checks)
