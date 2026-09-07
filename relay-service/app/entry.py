"""uvicorn 入口：app.entry:app（生产配置来自环境变量，见 relay.env）。"""
from .config import Settings
from .main import create_app

app = create_app(Settings.from_env())
