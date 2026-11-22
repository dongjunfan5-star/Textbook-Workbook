# 朗道《力学》做题本

[下载做题本 PDF](main.pdf)

依据《力学》第五版，源 PDF 文件名为“力学(第五版)-朗道 十分清晰”。全书 7 章，收录 96 道正式习题和 47 道正文改写题，按每道最多三个小问排为 147 道题。PDF 共 76 页，其中 72 页各排两题，第三、四、五章的末页各排一题。

- [校对题库](data/curated.json)记录题目、来源和校订依据。页码采用从 1 开始的 PDF 物理页码，跨页题记录题干首次出现的页码。
- [原书覆盖记录](qa/source-review.json)覆盖 168 个正文源页。[终稿验收记录](qa/visual-review.json)记录目录、题序、配图和逐页版面检查。
- [目录与版式源码](main.tex)引用分章题面和所需配图。直接编译源码使用 XeLaTeX、ctex 和 Fandol 字体，在本目录运行以下命令。

```powershell
xelatex -interaction=nonstopmode -halt-on-error main.tex
xelatex -interaction=nonstopmode -halt-on-error main.tex
```

从校对题库重新生成时，保留原始扫描 PDF 在本目录，并从工作区根目录运行以下命令。脚本会核验原书文件的校验值。

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/build_workbook.py '朗道《力学》' --config '朗道《力学》/project.json'
```
