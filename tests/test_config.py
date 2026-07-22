import pytest
from project.config import Config


def test_config_load_missing_file():
    """测试加载不存在的配置文件"""
    with pytest.raises(FileNotFoundError):
        Config.load("non_existent.json")


def test_config_default_values():
    """测试默认配置值"""
    config = Config()
    assert config.port == 8765
    assert config.host == "0.0.0.0"
    assert config.debug is False
