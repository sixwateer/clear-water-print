"""引擎抽象基类：所有修复引擎实现统一接口，方便扩展与热切换。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from PIL import Image


@dataclass
class EngineResult:
    """修复结果。"""

    image: Image.Image
    engine: str
    elapsed_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


class BaseEngine(ABC):
    """修复引擎基类。

    子类只需实现 ``inpaint`` 与 ``available`` 即可被服务自动注册。
    """

    name: str = "base"
    label: str = "基础引擎"
    requires_model: bool = False

    @abstractmethod
    def inpaint(
        self,
        image: Image.Image,
        rects: list[dict],
        strength: int = 2,
        enhance: bool = True,
        face: bool = False,
        **kwargs,
    ) -> EngineResult:
        """对图片执行修复。

        Args:
            image: 原始 PIL 图片（RGB）。
            rects: 水印框列表，元素为 ``{"x","y","w","h"}``，坐标基于原图像素。
            strength: 修复强度 1/2/3。
            enhance: 是否做画质增强。
            face: 是否启用人脸保真（支持时）。
        """
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """该引擎当前是否可用（依赖是否满足）。"""
        return True
