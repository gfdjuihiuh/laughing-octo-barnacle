"""数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class WechatArticle:
    """微信公众号文章"""
    title: str
    url: str                # mp.weixin.qq.com 直链
    account: str            # 公众号名称
    date_str: str           # 发布日期字符串
    content: str            # 全文纯文本
    summary: str = ""       # AI 提取的核心要点

    def key(self) -> str:
        """用于去重的唯一标识"""
        return self.url or self.title


@dataclass
class Article:
    """单条新闻"""
    title: str
    url: str
    source_name: str
    source_url: str
    category: str           # 所属领域（科技/金融/文化/民生/军事/政治/全球会议与重大活动）
    lang: str               # zh / en
    published: Optional[datetime] = None
    summary: str = ""       # 原始摘要或正文截断
    content: str = ""       # 完整正文（可能被截断）

    def key(self) -> str:
        """用于去重的唯一标识"""
        return self.url or self.title


@dataclass
class DigestItem:
    """摘要条目"""
    title: str
    summary: str
    source: str
    link: str


@dataclass
class CategoryDigest:
    """单个领域的摘要结果"""
    category: str
    digest: str             # 领域一句话概述
    items: list[DigestItem] = field(default_factory=list)
    error: Optional[str] = None   # API 调用失败时记录错误


@dataclass
class DailyReport:
    """日报"""
    date: str               # YYYY-MM-DD
    generated_at: datetime
    model: str
    lookback_hours: int
    total_sources: int
    total_articles: int
    categories: list[CategoryDigest] = field(default_factory=list)
