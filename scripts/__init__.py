"""CLI 入口薄封装。

本目录下的脚本都只是转发到 ``src/inloop/cli.py``，不承载业务逻辑；
好处是同一个功能只有一份实现，不会出现「改了包、忘了脚本」的分叉。

- ``new_article.py``      → ``inloop new``
- ``check_article.py``    → ``inloop check``
- ``build_wechat.py``     → ``inloop build-wechat``
- ``generate_index.py``   → ``inloop index``

``utils/`` 用于存放确实只服务于脚本本身的辅助代码；能被包内复用的逻辑
应当放进 ``src/inloop/``，不要放在这里。
"""
