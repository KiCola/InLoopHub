# 上手入口

**完整的"怎么用"写在 README 里**，不再在本文重复一份——两份内容必然漂移，
最后没人知道哪份是对的。

- 安装、新建文章、写内容、放图片、检查、预览、发布、提交：
  见 [README 的「怎么用」一节](../README.md#怎么用)
- 写作规范（术语、图片规格、三种引用形态的判定标准）：
  见 [style-guide.md](style-guide.md)
- 排版主题怎么选、怎么调、怎么新建：
  见 [styles/themes/README.md](../styles/themes/README.md)

本文只补 README 里没写的两件事：**首次配置**与**命令的执行位置**。

## 首次配置

`config/site.yaml` 与 `config/wechat.yaml` 是全部可调项的集中位置。
第一次使用时需要改的通常只有两项：

```yaml
# config/site.yaml
site:
  author: "Zero Zhao"        # 改成你的名字，新建文章时会自动填入 front matter
```

```yaml
# config/wechat.yaml
wechat:
  theme: "inloop"            # 排版主题，用 `inloop themes` 看有哪些
  auto_number_headings: false # 是否给二级标题自动编号
```

其余项（正文字号、行高、段间距、图片体积阈值）都有合理默认值，可以先不动。
注意：**正文字号与行高由主题决定**，改 `config/wechat.yaml` 不生效——
想调节奏请改 `styles/themes/<主题>.css`。详见 [styles/README.md](../styles/README.md)。

## 命令的执行位置

所有 `inloop` 命令都要在**仓库根目录**下执行。程序靠向上查找仓库根来定位配置，
所以在子目录里执行也能正常工作，但为了路径清楚，建议始终在根目录执行。

```bash
cd E:\InLoopHub          # 或你的仓库位置
.venv\Scripts\activate
inloop check 002-light-o1
```

文章参数可以直接写 slug（`002-light-o1`），比写完整路径短，所有命令都支持。

## 一条建议的写作节奏

1. **想法先记在 `drafts/ideas.md`**，不要一有想法就建正式文章目录。
2. 决定认真写时再 `inloop new`。此时才需要完整的 front matter。
3. **写完一节就跑一次 `inloop check`**，不要等全文写完——
   图片路径、front matter 这类问题越早发现越省事。
4. 定稿后 `inloop preview-wechat` 在手机上过一遍观感，再构建发布。
5. `status` 推到 `ready` 之后再发布，`published` 表示已经上线。
