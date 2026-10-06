"""全局配置（本地优先、可配置切换 MySQL）。"""
from __future__ import annotations
import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
DATA_DIR = BASE_DIR.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    # 数据库：默认本地 SQLite（零配置）。若要接 MySQL，设置
    # DATABASE_URL="mysql+pymysql://user:pass@127.0.0.1:3306/shortdrama?charset=utf8mb4"
    DATABASE_URL: str = f"sqlite:///{DATA_DIR / 'app.db'}"

    JWT_SECRET: str = os.getenv("JWT_SECRET", "change_me_before_deploy")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天

    CAPTCHA_TTL: int = 300           # 验证码有效期（秒）
    CAPTCHA_LEN: int = 4             # 验证码字符数
    CAPTCHA_CHARS: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去易混字符

    # 后台超管种子账号（首启自动创建，首登请改密）
    ADMIN_SEED_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_SEED_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "change_me_before_deploy")

    # 演示「会员Pro」账号（prodemo）初始口令（首启自动创建，上线请改）
    DEMO_PRO_PASSWORD: str = os.getenv("DEMO_PRO_PASSWORD", "change_me_before_deploy")

    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "change_me_before_deploy")

    # ---------------- 方舟（火山引擎）接入配置 ----------------
    ARK_API_KEY: str = os.getenv("ARK_API_KEY", "")
    ARK_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    # 模型 endpoint（已实测可用，不升级）
    ARK_MODEL_CHAT: str = os.getenv("ARK_MODEL_CHAT", "doubao-seed-2-0-mini-260428")  # 默认快速模型；追求更高质量可设 ARK_MODEL_CHAT=doubao-seed-2-1-pro-260628
    ARK_MODEL_CHARACTER: str = os.getenv("ARK_MODEL_CHARACTER", "doubao-seed-character-260628")
    ARK_MODEL_MINI: str = os.getenv("ARK_MODEL_MINI", "doubao-seed-2-0-mini-260428")
    ARK_MODEL_VISION: str = os.getenv("ARK_MODEL_VISION", "doubao-seed-2-1-turbo-260628")
    ARK_MODEL_IMAGE: str = os.getenv("ARK_MODEL_IMAGE", "doubao-seedream-4-0-250828")
    ARK_MODEL_VIDEO: str = os.getenv("ARK_MODEL_VIDEO", "doubao-seedance-1-0-pro-fast-251015")
    # 文本嵌入模型（RAG 语义检索用）。doubao-embedding-text-240715 中文 SOTA，2048 维
    ARK_MODEL_EMBEDDING: str = os.getenv("ARK_MODEL_EMBEDDING", "doubao-embedding-vision-251215")  # 已验证可直调（多模态接口嵌文本）；若建有纯文本 ep 接入点可改为 ep-xxx

    # ---------------- 豆包语音（配音）配置 ----------------
    VOLC_TTS_API_KEY: str = os.getenv("VOLC_TTS_API_KEY", "")
    VOLC_TTS_APP_ID: str = os.getenv("VOLC_TTS_APP_ID", "")
    VOLC_TTS_CLUSTER: str = os.getenv("VOLC_TTS_CLUSTER", "volcano_tts")

    # ---------------- 产物存储 ----------------
    # 注意：须与 main.py 中 /static/assets 挂载目录保持一致（均为 backend/static/assets）
    ASSET_DIR: Path = BASE_DIR / "static" / "assets"

    @property
    def ark_enabled(self) -> bool:
        return bool(self.ARK_API_KEY)

    @property
    def tts_enabled(self) -> bool:
        return bool(self.VOLC_TTS_API_KEY)

    class Config:
        env_file = str(BASE_DIR / ".env")
        extra = "ignore"

    @property
    def db_url(self) -> str:
        # 让 SQLite 允许跨线程（FastAPI 线程池 + SSE）
        url = self.DATABASE_URL
        if url.startswith("sqlite"):
            return url + ("?check_same_thread=False" if "?" not in url else "&check_same_thread=False")
        return url


settings = Settings()
