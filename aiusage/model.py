"""各平台共用的資料格式。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

# status 的可能值：
#   ok              取得並解析成功
#   login_required  需要（重新）登入
#   parse_error     頁面讀到了，但格式看不懂（不顯示猜的數字）
#   error           其他錯誤（網路、瀏覽器、缺少套件等）


@dataclass
class UsageWindow:
    key: str                      # "session" | "weekly" | "monthly"
    label: str                    # 頁面上的原始標籤，例如「目前用量」
    used_percent: float           # 0~100
    resets_at: Optional[datetime] = None   # 解析成功時為帶時區的時間
    resets_raw: str = ""          # 頁面上的原始文字，例如「上午2:14」

    @property
    def remaining_percent(self) -> float:
        return round(100.0 - self.used_percent, 1)


@dataclass
class ProviderStatus:
    provider: str
    status: str
    message: str = ""
    plan: str = ""
    windows: list[UsageWindow] = field(default_factory=list)
    fetched_at: Optional[datetime] = None
    # 合併顯示多個帳號時：[(帳號名稱, 該帳號的 ProviderStatus), ...]；windows 放最緊那個帳號的資料
    parts: list = field(default_factory=list)

    def window(self, key: str) -> Optional[UsageWindow]:
        return next((w for w in self.windows if w.key == key), None)

    def to_json(self) -> str:
        def default(o):
            if isinstance(o, datetime):
                return o.isoformat()
            raise TypeError(type(o))
        d = asdict(self)
        for w, src in zip(d["windows"], self.windows):
            w["remaining_percent"] = src.remaining_percent
        return json.dumps(d, ensure_ascii=False, indent=2, default=default)
