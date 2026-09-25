"""InLoop 手记内容仓库与微信公众号发布系统。

包顶层只暴露版本号，避免任何副作用（不读文件、不读配置、不 import 重依赖）。
需要配置与路径定位时，显式使用：

    from inloop.config import Config, repo_root

模块划分（与任务书 §19、§29 对应）：

- ``models``       文章数据模型
- ``parser``       Front Matter 与 Markdown 解析
- ``renderer``     各平台渲染，第一阶段为微信公众号
- ``assets``       图片等素材处理流水线
- ``publishers``   平台发布适配层，与内容源解耦
- ``config``       配置读取与仓库根定位
- ``cli``          命令行入口
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
