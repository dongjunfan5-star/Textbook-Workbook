# 《近世代数引论》第四版做题本

[下载全书 PDF](main.pdf)。全书 3 章，共 **461 题、156 页**，页数含封面和目录。常规页排 3 题，长题可独占一页。

| 章节 | 题数 |
| --- | ---: |
| 1 群 | 189 |
| 2 环和域 | 185 |
| 3 域的伽罗瓦理论 | 87 |

原教材文件名为 `近世代数引论_第四版(1)`。收录物理第 10–189 页中的例题、习题和正文明确留给读者的练习，包含各章附录中的题目。说明性例题改写成计算或证明题并标注“改写”，涉及原书数学条件或公式的校订标注“校订”。题目来源采用原 PDF 中第一次出现的物理页码。

- [题目数据和来源](data/problems.json)
- [原书页码与校对记录](qa/full-source-review.json)
- [排版与目录验收](qa/visual-review.json)
- [使用许可](../LICENSE.md)

在本目录中运行 XeLaTeX 编译 `main.tex`，至少运行两次，直到目录稳定。直接编译已生成的 LaTeX 源码即可，配图存放于 `figures/`。

如需从校对数据重新生成章节与配图，在 `input/` 放入与 [教材清单](qa/source-inventory.json) 哈希一致的原始 PDF，然后从仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/build_workbook.py 近世代数引论 --config 近世代数引论/project.json
```
