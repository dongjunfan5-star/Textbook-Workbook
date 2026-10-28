# Textbook-Workbook

将数理教材中的例题与习题整理为便于书写、集中练习的做题本。

**《数学分析讲义》三册合订本已完成：18 章、1762 题、468 页。** [下载做题本](数学分析讲义/main.pdf) · [源码与使用说明](数学分析讲义/README.md)。页数包含说明与目录页，题量按拆分后的最终题号统计。《数学分析教程》仍在制作中。

## 教材与进度

| 教材文件名（不含扩展名） | 排版 | 当前阶段 |
| --- | --- | --- |
| 数学分析讲义（第一册）、数学分析讲义（第二册）、数学分析讲义（第三册） | 通常 4 题/页，三册合一本 | 已完成：1762 题、468 页 |
| 数学分析教程 上册（数分A教材）、数学分析教程 下册（数分A教材） | 通常 3 题/页，上下册合一本 | 制作中，暂未发布整书 |

## 制作规则

- 收录例题、节末习题、章末习题，以及正文中明确留给读者的练习和可独立表述的具体例子。正文与正式习题重复时保留正式习题，并记录覆盖依据。
- 以校对后的文字、LaTeX 公式和必要配图为主要形式，不放入相同题目的重复截图；不收录解答和独立提示，保留题目要求的方法与必要定义、条件。
- 原题超过 3 个小问时，每组最多 3 个小问另编一道题，重复必要的公共题干；每组小问从（1）重新编号。长题允许独页。
- 成品只显示最终题号。每题记录源 PDF 相对路径及首次出现的 PDF 物理页码（从 1 开始）；跨页题仍记第一页。
- 只有说明、没有提问的例子改写为求证或计算题，标注“改写”；实质性数学条件校订标注“校订”，依据保存在校对数据中。
- 原始教材只读。PaddleOCR 结果经逐页核对后才进入排版；编译、题序、目录链接和逐页视觉检查分别验收。
- 仅限非商业性使用，详见 [使用许可](LICENSE.md)。第三方教材内容不因本仓库的许可而获得新的授权。

## 仓库结构

```text
Textbook-Workbook/
├── README.md
├── LICENSE.md
├── 制作要求.txt
├── .gitignore
├── requirements*.txt       # 制作环境依赖
├── config/                 # 参数、源文件清单和校验值
├── scripts/                # OCR、排版、检查与发布包工具
├── templates/              # 共用版式
├── tests/                  # 数据、排版与发布规则检查
├── qa/                     # 发布范围内的校对和验收记录
└── 数学分析讲义/
    ├── README.md
    ├── main.tex
    ├── main.pdf            # 正式交付物
    ├── chapters/           # 18 章 LaTeX 源码
    ├── figures/            # 必要配图
    ├── data/
    │   ├── curated.json    # 合并后的校对数据，重新生成的入口
    │   └── problems.json   # 拆分、编号后的题目与来源
    ├── qa/                # 本书构建及验收记录
    └── input/             # 本地原始教材，不上传
```

原始教材、OCR 原文、整页渲染、模型、虚拟环境、构建中间文件和凭据不提交。制作期间的分章数据保留在本地，发布版本以合并后的 `data/curated.json` 为准。远程已有的教程占位目录暂时保留，待教程整书验收时迁移。

## 重新编译已发布的做题本

安装含 XeLaTeX、ctex、Fandol、amsmath、geometry、fancyhdr、hyperref、graphicx 的 TeX Live。在项目目录执行：

```powershell
cd 数学分析讲义
xelatex -interaction=nonstopmode -halt-on-error main.tex
xelatex -interaction=nonstopmode -halt-on-error main.tex
```

若仍提示交叉引用或目录变化，继续编译至稳定。直接编译发布的 LaTeX 源码不需要原始教材或 OCR 环境。

## 从校对数据重新生成

此步骤会重新生成章节、题目数据和成品，需自行在 `input/` 放入与 `config/production-books.json` 校验值一致的原始教材；脚本会核对来源文件。Python 使用独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 scripts/build_workbook.py 数学分析讲义
```

程序按题目实际高度和每页题数分页，在每题后加入 `\vfill`；至少编译两次，并继续至目录、引用及书签文件稳定（最多五次）。可用 `--xelatex` 指定编译器。重新生成后必须重新验收，旧 PDF 的视觉验收记录不能直接沿用到改变了页面的版本。

## 整书 OCR 制作环境

本项目采用 PaddleOCR 路线。整书使用 PaddleOCR-VL 1.6：版面模型在 CPU 上运行，文字与公式通过本机 llama.cpp CUDA 服务识别。依赖与模型下载校验由下列脚本管理：

```powershell
python -m venv .venv-gpu
.\.venv-gpu\Scripts\python.exe -m pip install -r requirements-gpu-lock.txt
.\.venv-gpu\Scripts\python.exe -X utf8 scripts/download_ocr_runtime.py
.\.venv-gpu\Scripts\python.exe -X utf8 scripts/download_layout_model.py
& scripts/start_ocr_server.ps1 -Parallel 2 -ContextSize 8192
& scripts/start_ocr_job.ps1 -Inventory config/production-pages.json -Concurrency 2
```

服务只监听 `127.0.0.1:8111`。后台任务与日志记录在 `.cache/ocr-job/current.json`，成功页可断点复用。识别结果保存在各项目 `data/ocr_raw/vl1.6/`，始终作为未校对材料使用。Windows 模型目录须避免中文路径；本机使用 `%LOCALAPPDATA%\TextbookWorkbook\models`。

`prepare_sample.py`、`ocr_sample.py`、`audit_sample.py` 和首轮样本报告属于早期 16 页验证流程，不是整书验收入口。整书验收采用逐页来源记录、对应 OCR 证据、正式构建报告与当前 PDF 的逐页视觉记录。

## 发布检查

`scripts/prepare_publication.py` 只生成本地发布包。它核对完成状态、源页覆盖、OCR 证据、校对数据、实际题数与 PDF 视觉记录，再按白名单和 `.gitignore` 检查发布范围。

```powershell
# 仅打包已完成的讲义；教程未完成不影响讲义单独发布
.\.venv\Scripts\python.exe -X utf8 scripts/prepare_publication.py --project 数学分析讲义
# 不指定项目时，要求所有项目都完成
.\.venv\Scripts\python.exe -X utf8 scripts/prepare_publication.py
```

上传前重新核对远程 `main`，以其当前树保留已有内容，创建以当前 HEAD 为父节点的提交，再按预期 HEAD 非强制更新。不得强制覆盖远程历史。

## 后续教材计划

以下保留已有排队书目，尚未开始制作，不计入当前题量。

| 科目 | 教材 | 状态 |
| --- | --- | --- |
| 数学 | 线性代数及其应用 | 排队中 |
| 物理 | 力学（舒幼生） | 排队中 |
| 物理 | 经典力学（高显） | 排队中 |
| 物理 | 力学（朗道） | 排队中 |
