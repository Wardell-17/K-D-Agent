---
name: docx
description: 读取、修改、审阅 Word 文档（.docx）。当用户要求修改 Word 文件、提取 docx 内容、审阅文档格式时使用。docx 是 ZIP+XML 二进制包，不可直接文本读写，必须用 python-docx 操作。
---

# docx 处理纪律

## 核心事实

- `.docx` = ZIP 压缩包（内部是 XML）。**禁止**用文本读写工具直接打开，会得到乱码
- 唯一操作方式：通过 bash/pwsh 工具调用 Python 的 `python-docx` 库

## 环境自检（每次任务先做）

```bash
python -c "import docx; print('ok')" || pip install python-docx
```

失败则报告用户环境缺 Python 或网络不可装包，不要硬编二进制。

## 标准工作流

1. **先体检再动手**：用只读脚本提取全文段落与表格，向用户确认理解了文档结构
2. **永不覆盖原文件**：输出一律写 `原名-修订.docx`，原文件保持不动
3. **修改用脚本，不用手**：把修改逻辑写成 `.py` 脚本再执行，保证可复现、可验收
4. **验收**：改完后重新提取新文件全文，逐条核对修改点是否生效

## 常用操作速查

```python
from docx import Document

doc = Document("input.docx")
for p in doc.paragraphs:      # 全部段落
    print(p.text, p.style.name)
for t in doc.tables:          # 全部表格
    for row in t.rows:
        print([c.text for c in row.cells])

# 改文字（保留格式的最小改法：改 run 而不是重建段落）
for p in doc.paragraphs:
    for r in p.runs:
        if "旧词" in r.text:
            r.text = r.text.replace("旧词", "新词")

doc.save("input-修订.docx")   # 另存，不覆盖
```

## 边界（如实告知用户）

- 复杂排版（文本框、嵌套表格、页眉页脚图片）python-docx 支持有限，先做体检确认范围
- 修订模式（tracked changes）与批注可读写但 API 较弱，需求复杂时建议用户用 Word 审阅
- `.doc`（旧格式）不支持，需用户先在 Word 里另存为 `.docx`
