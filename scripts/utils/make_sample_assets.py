"""生成示例文章所需的配图（一次性工具脚本，不参与运行时）。

放在 scripts/utils/ 下而不是包内：它只服务仓库初始化，`inloop` 本身不需要它。
删除本文件不会影响任何功能，但示例文章的配图会缺失，需要重新生成。

用法：python scripts/utils/make_sample_assets.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 品牌色，与 config/site.yaml 的 brand 保持一致
KLEIN_BLUE = (0, 47, 167)
LIGHT_BLUE = (235, 240, 251)
TEXT_DARK = (34, 37, 43)
TEXT_GREY = (107, 114, 128)
BORDER = (229, 231, 235)
WHITE = (255, 255, 255)


def _font(size: int):
    """取一个可用的中文字体。找不到时返回默认字体（英文可读，中文会变方块）。"""
    from PIL import ImageFont

    for candidate in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyh.ttf",
        r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ):
        path = Path(candidate)
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def box(draw, xy, text, *, font, fill, text_fill, pad=10) -> None:
    """画一个圆角矩形并居中写字。"""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=8, fill=fill, outline=KLEIN_BLUE, width=2)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((x0 + x1 - (right - left)) / 2, (y0 + y1 - (bottom - top)) / 2 - top),
        text,
        font=font,
        fill=text_fill,
    )


def arrow(draw, start, end) -> None:
    """画一条带箭头的连线。"""
    draw.line([start, end], fill=KLEIN_BLUE, width=2)
    x, y = end
    draw.polygon([(x, y), (x - 9, y - 5), (x - 9, y + 5)], fill=KLEIN_BLUE)


def make_hello_overview(path: Path) -> None:
    """001 用图：知识库首页与文章仓库的关系示意。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1000, 460), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = _font(22)
    small = _font(18)

    box(draw, (60, 60, 320, 140), "本知识库", font=font, fill=LIGHT_BLUE, text_fill=TEXT_DARK)
    box(draw, (60, 200, 320, 280), "微信公众号", font=font, fill=WHITE, text_fill=TEXT_DARK)
    box(draw, (60, 340, 320, 420), "技术博客", font=font, fill=WHITE, text_fill=TEXT_DARK)

    box(
        draw,
        (420, 180, 700, 300),
        "inloop-notes\nMarkdown 仓库",
        font=small,
        fill=LIGHT_BLUE,
        text_fill=TEXT_DARK,
    )

    arrow(draw, (320, 250), (420, 240))
    arrow(draw, (700, 220), (830, 130))
    arrow(draw, (700, 260), (830, 260))
    arrow(draw, (830, 130), (830, 260))

    box(draw, (700, 90, 950, 170), "问答 / 检索", font=small, fill=WHITE, text_fill=TEXT_GREY)
    draw.text((430, 330), "唯一事实源：Git 中的 Markdown", font=small, fill=TEXT_GREY)

    image.save(path)


def make_light_o1_architecture(path: Path) -> None:
    """002 用图：分层架构示意。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1000, 520), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = _font(20)

    layers = [
        ("感知输入（视觉 / 本体感觉）", LIGHT_BLUE),
        ("多模态表征", (255, 255, 255)),
        ("基础模型（预训练权重）", LIGHT_BLUE),
        ("动作解码 / 控制接口", (255, 255, 255)),
        ("关节执行（20Hz 控制回路）", LIGHT_BLUE),
    ]
    y = 40
    for text, fill in layers:
        box(draw, (120, y, 880, y + 70), text, font=font, fill=fill, text_fill=TEXT_DARK)
        y += 90
    # 左侧的连接线画在方框之外，避免穿过文字
    draw.line([(96, 75), (96, 455)], fill=BORDER, width=3)
    draw.text(
        (140, 480),
        "注：示意图，用于说明分层关系，不代表论文原始架构",
        font=_font(16),
        fill=TEXT_GREY,
    )

    image.save(path)


def make_robodojo_pipeline(path: Path) -> None:
    """003 用图：数据采集到策略训练的处理链。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1000, 300), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = _font(18)

    stages = ["采集", "清洗", "对齐", "重放", "训练"]
    x = 60
    for index, stage in enumerate(stages):
        box(draw, (x, 110, x + 150, 190), stage, font=font, fill=LIGHT_BLUE, text_fill=TEXT_DARK)
        if index < len(stages) - 1:
            arrow(draw, (x + 150, 150), (x + 185, 150))
        x += 185

    draw.text(
        (60, 230),
        "每一步都留下可复现的记录：输入、参数、输出校验值",
        font=_font(16),
        fill=TEXT_GREY,
    )
    image.save(path)


def make_g1_control_loop_gif(path: Path) -> None:
    """004 用图：控制回路 GIF（任务书 §28 要求验证 GIF）。

    用动画表达"感知 → 决策 → 执行"的循环，验证 GIF 能被正确复制与展示。
    """
    from PIL import Image, ImageDraw

    frames = []
    labels = ["感知", "决策", "执行"]
    for active in range(len(labels)):
        image = Image.new("RGB", (720, 260), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        font = _font(20)
        x = 60
        for index, label in enumerate(labels):
            fill = KLEIN_BLUE if index == active else LIGHT_BLUE
            text_fill = (255, 255, 255) if index == active else TEXT_DARK
            box(draw, (x, 100, x + 180, 180), label, font=font, fill=fill, text_fill=text_fill)
            if index < len(labels) - 1:
                arrow(draw, (x + 180, 140), (x + 220, 140))
            x += 220
        # 回路：从最后一个回到第一个
        draw.line([(640, 190), (640, 230), (150, 230), (150, 182)], fill=KLEIN_BLUE, width=2)
        draw.polygon([(150, 180), (145, 190), (155, 190)], fill=KLEIN_BLUE)
        frames.append(image)

    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=700,
        loop=0,
        optimize=True,
    )


def make_covers(root: Path) -> None:
    """为 4 篇示例文章生成封面占位图。"""
    from PIL import Image, ImageDraw

    covers = {
        "001-hello-inloop": "本知识库手记",
        "002-light-o1": "Light-O1 拆解",
        "003-robodojo": "RoboDojo 实验",
        "004-g1-reaching": "G1 抓取复盘",
    }
    for slug, title in covers.items():
        image = Image.new("RGB", (1175, 500), KLEIN_BLUE)
        draw = ImageDraw.Draw(image)
        font = _font(56)
        left, top, right, bottom = draw.textbbox((0, 0), title, font=font)
        draw.text(
            ((1175 - (right - left)) / 2, (500 - (bottom - top)) / 2 - top),
            title,
            font=font,
            fill=(255, 255, 255),
        )
        target = root / "articles" / "2026" / slug / "cover.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        print(f"  封面 -> {target.relative_to(root).as_posix()}")


def main() -> int:
    assets = {
        "001-hello-inloop/assets/overview.png": make_hello_overview,
        "002-light-o1/assets/architecture.png": make_light_o1_architecture,
        "003-robodojo/assets/pipeline.png": make_robodojo_pipeline,
        "004-g1-reaching/assets/control-loop.gif": make_g1_control_loop_gif,
    }
    for relative, maker in assets.items():
        target = REPO_ROOT / "articles" / "2026" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        maker(target)
        print(f"  配图 -> {target.relative_to(REPO_ROOT).as_posix()}")

    print("生成封面：")
    make_covers(REPO_ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
