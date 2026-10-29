from twinspace.core.logger import (
    add_log_listener,
    clear_logs,
    get_logger,
    read_logs,
    remove_log_listener,
    setup_logging,
)


def test_logger_file_writing_and_reading(tmp_path):
    log_file = tmp_path / "test.log"
    setup_logging(log_file=log_file)

    logger = get_logger("test_module")
    logger.info("Hello TwinSpace Test")
    logger.error("Something went wrong")

    content = read_logs(log_file=log_file)
    assert "Hello TwinSpace Test" in content
    assert "[INFO] [twinspace.test_module]" in content or "[INFO] [test_module]" in content
    assert "Something went wrong" in content
    assert "[ERROR]" in content


def test_clear_logs(tmp_path):
    log_file = tmp_path / "test_clear.log"
    setup_logging(log_file=log_file)
    logger = get_logger("test_clear")
    logger.info("Record 1")
    assert "Record 1" in read_logs(log_file=log_file)

    clear_logs(log_file=log_file)
    content = read_logs(log_file=log_file)
    assert "Record 1" not in content
    assert "Log file cleared by user" in content


def test_broadcast_listener():
    messages = []

    def _listener(msg: str):
        messages.append(msg)

    add_log_listener(_listener)
    try:
        logger = get_logger("broadcast_test")
        logger.info("Live broadcast message")
        assert any("Live broadcast message" in m for m in messages)
    finally:
        remove_log_listener(_listener)


def test_log_disable_flag_only_mutes_the_default_log(tmp_path, monkeypatch):
    """pytest must not append to ~/TwinSpace/twinspace.log, but explicit paths work."""
    from twinspace.core import logger as logger_module

    monkeypatch.setenv("TWINSPACE_LOG_DISABLE", "1")

    # The default (production) path is skipped entirely.
    default_log = tmp_path / "prod" / "twinspace.log"
    monkeypatch.setattr(logger_module, "DEFAULT_LOG_FILE", default_log, raising=False)
    logger_module.setup_logging(log_file=default_log)
    logger_module.get_logger("test_disable").info("should not be written")
    assert not default_log.exists()

    # An explicit path still receives records.
    custom_log = tmp_path / "custom.log"
    logger_module.setup_logging(log_file=custom_log)
    logger_module.get_logger("test_disable_custom").info("written")
    assert "written" in custom_log.read_text(encoding="utf-8")
