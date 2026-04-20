# 知识图谱数据汇总 v12.0 交接说明

本文档用于交接当前工作区的数据生产流程、脚本用途、数据血缘和复跑注意事项。

## 1. 工作区总览

工作区根目录：`D:\moyo\proj\KG\数据汇总v12.0`

主要目录：

- `1_deepspark数据爬虫`：第 1 阶段，爬取 DeepSparkHub 模型仓库，生成基础知识图谱节点和关系。
- `2_提取天数文档_添加节点和关系`：第 2 阶段，在第 1 阶段结果基础上，补充天数智芯文档中的节点和关系。
- `3_提取dtk文档_添加节点和关系`：第 3 阶段，批量解析 DTK 兼容性手册，补充 API、Runtime、Runtime-API 和 API-API 映射关系，并合并最终版。
- `数据汇总v12.0.zip`：当前工作区压缩包。
- `__pycache__`：Python 运行产生的缓存，可忽略。
- `.git`：本地 Git 仓库元数据。

统一 CSV 结构：

- 节点文件列：`id,label,name,source_url,extra/Type,extra/area,extra/Main-Task,software_id,framework_id,extra/Vendor,extra/release,hardware_id,runtime_id,extra/library`
- 关系文件列：`source_id,relation,target_id`

最终交付文件：

- `3_提取dtk文档_添加节点和关系/最终版本/nodes.csv`
- `3_提取dtk文档_添加节点和关系/最终版本/edges.csv`
- `3_提取dtk文档_添加节点和关系/最终版本/知识图谱数据说明.md`

当前最终版规模：

- `nodes.csv`：6686 行数据
- `edges.csv`：67235 行数据

## 2. 整体数据生产流程

整体流程分三步：

1. 运行 `1_deepspark数据爬虫/crawl_deepsparkhub_new.py`，从 DeepSparkHub 生成基础模型、框架、硬件、运行时、部署配置、数据集、作者、教程等节点和关系。
2. 在第 1 步 CSV 基础上，人工借助 AI Studio Gemini 分块解析天数智芯文档，得到第 2 阶段的 `nodes_origin.csv` 和 `edges_origin.csv`。
3. 运行第 3 阶段 DTK 脚本，批量解析 14 份 DTK PDF，生成补充 API 图谱 CSV，并与第 2 阶段csv数据合并；之后人工补充 DTK Runtime 与硬件的 `SUPPORTS_RUNTIME` 关系，得到最终版。

数据血缘可以理解为：

```text
1_deepspark数据爬虫/data/nodes_v1.3.csv
1_deepspark数据爬虫/data/edges_v1.3.csv
        ↓
2_提取天数文档_添加节点和关系/nodes_origin.csv
2_提取天数文档_添加节点和关系/edges_origin.csv
        ↓
3_提取dtk文档_添加节点和关系/补充内容/*_nodes.csv
3_提取dtk文档_添加节点和关系/补充内容/*_edges.csv
        ↓
3_提取dtk文档_添加节点和关系/最终版本/nodes.csv
3_提取dtk文档_添加节点和关系/最终版本/edges.csv
```

## 3. 第 1 阶段：DeepSparkHub 爬虫

目录：`1_deepspark数据爬虫`

关键文件：

- `crawl_deepsparkhub_new.py`：DeepSparkHub 爬虫主脚本。
- `data/nodes_v1.3.csv`：当前保留的第 1 阶段节点结果，986 行。
- `data/edges_v1.3.csv`：当前保留的第 1 阶段关系结果，1891 行。

脚本依赖：

- Python
- `requests`
- `pandas`
- 网络访问 Gitee API
- 环境变量 `GITEE_TOKEN`

提前配置输出文件名（crawl_deepsparkhub_new.py 319-320行）

    nodes_path = os.path.join(output_dir, "nodes_vXXX.csv")
    edges_path = os.path.join(output_dir, "edges_vXXX.csv")

脚本运行方式：

```powershell
cd .\1_deepspark数据爬虫
$env:GITEE_TOKEN="你的 Gitee Token"
python .\crawl_deepsparkhub_new.py
```

脚本核心逻辑：

- 访问 `https://gitee.com/api/v5/repos/deep-spark/deepsparkhub`。
- 从 `models` 目录开始递归查找 `README.md`，最大深度为 `MAX_DEPTH = 5`。
- 从模型路径推断：
  - `Software`
  - `Framework`
  - `SoftwareInstance`
  - `Guide`
  - `Dataset`
  - `Hardware`
  - `Runtime`
  - `DeploymentConfig`
  - `Author`
- 从 README 的 `Supported Environments` 表格中提取硬件、运行时和 release 信息。
- 从 README 的 `References` 部分推断作者。
- 从主 README 的模型表格中补充数据集信息。

生成的主要关系：

- `SoftwareInstance -> INSTANCE_OF -> Software`
- `SoftwareInstance -> USES_FRAMEWORK -> Framework`
- `SoftwareInstance -> CAN_DEPLOY_ON -> DeploymentConfig`
- `DeploymentConfig -> CONFIGURES_HARDWARE -> Hardware`
- `DeploymentConfig -> CONFIGURES_RUNTIME -> Runtime`
- `Hardware -> SUPPORTS_RUNTIME -> Runtime`
- `Software -> DEVELOPED_BY -> Author`
- `SoftwareInstance -> HAS_GUIDE -> Guide`
- `SoftwareInstance -> TRAINED_ON -> Dataset`


## 4. 第 2 阶段：天数文档补充

目录：`2_提取天数文档_添加节点和关系`

关键文件：

- `nodes_origin.csv`：第 2 阶段节点结果，2341 行。
- `edges_origin.csv`：第 2 阶段关系结果，4321 行。
- `tianshu_documents/1. 天数智芯加速卡软件栈文档合集_V4.2.0.pdf`
- `tianshu_documents/天数智芯加速卡软件栈⽂档合集_V4.3.0.pdf`

当前处理方式：

- `nodes_origin.csv` 和 `edges_origin.csv` 是在第 1 阶段 CSV 的基础上扩展得到的。
- 扩展数据来自 `tianshu_documents` 子目录中的天数智芯文档。
- 具体提取方式是使用 AI Studio 中的 Gemini 对 PDF 文档进行分块提取，人工整理出新的节点和关系后合并进 CSV。

补充建议 1：

- `./2_提取天数文档_添加节点和关系` 文件夹中的 csv 文件，是在上一步 csv 文件的基础上，使用 ai studio 中的 Gemini 分块提取 `./2_提取天数文档_添加节点和关系/tianshu_documents` 子文件夹中文档中的节点和关系数据实现的，未来建议编写脚本实现自动化提取。

第 2 阶段没有自动化脚本。后续如果继续扩展，建议新增脚本，至少覆盖：

- PDF 文本抽取。
- 表格抽取。
- Runtime、Hardware、API、Library 等实体识别。
- 关系生成。
- 与第 1 阶段 CSV 的去重合并。

## 5. 第 3 阶段：DTK 文档批量提取和合并

目录：`3_提取dtk文档_添加节点和关系`

关键脚本：

- `extract_dtk_api_graph.py`：单 PDF 提取逻辑，可传入 PDF 路径和输出路径。
- `batch_generate_dtk_graphs.py`：批量处理 `dtk文档` 下全部 PDF，输出到 `补充内容`。
- `merge_dtk_graphs.py`：合并补充 DTK CSV 和源数据 CSV，输出到 `最终版本`。

关键数据目录：

- `dtk文档`：14 份 DTK 兼容性手册 PDF。
- `补充内容`：每份 DTK PDF 对应一组 `_nodes.csv` 和 `_edges.csv`。
- `最终版本`：最终交付 CSV 和知识图谱说明文档。

### 5.1 DTK 输入文档

`dtk文档` 下共有 14 份 PDF：

- `DTK-22.04.2兼容性手册.pdf`
- `DTK 22.10.1 兼容性手册.pdf`
- `DTK 23.04.1 兼容性手册.pdf`
- `DTK 23.10 兼容性手册.pdf`
- `DTK 23.10.1 兼容性手册.pdf`
- `DTK 24.04 兼容性手册.pdf`
- `DTK 24.04.1 兼容性手册.pdf`
- `DTK 24.04.2 兼容性手册.pdf`
- `DTK 24.04.3 兼容性手册.pdf`
- `DTK 25.04 兼容性手册.pdf`
- `DTK 25.04.1 兼容性手册.pdf`
- `DTK 25.04.2 兼容性手册.pdf`
- `DTK 25.04.3 兼容性手册.pdf`
- `DTK 25.04.4 兼容性手册.pdf`

### 5.2 `extract_dtk_api_graph.py`

用途：

- 从单份 DTK 兼容性手册 PDF 中提取 API 节点和关系。

依赖：

- Python
- `pdfplumber`

单文档运行方式：

```powershell
cd .\3_提取dtk文档_添加节点和关系
python .\extract_dtk_api_graph.py ".\dtk文档\DTK 25.04.3 兼容性手册.pdf" ".\补充内容\DTK_25.04.3_兼容性手册_nodes.csv" ".\补充内容\DTK_25.04.3_兼容性手册_edges.csv"
```

脚本核心逻辑：

- 从 PDF 文件名解析版本号。
- 将版本号转换为：
  - `runtime_id`，例如 `DTK 25.04.3` 转为 `runtime:dtk25043`
  - `runtime_name`，例如 `DTK 25.04.3`
  - `source_url`，例如 `https://download.sourcefind.cn:65024/1/main/DTK-25.04.3/Document`
- 用 `pdfplumber` 读取 PDF 表格。
- 根据章节判断表格含义：
  - 支持列表：生成 `Runtime -> SUPPORTS_API -> API`
  - 兼容性列表：生成 `Runtime -> COMPATIBLE_WITH -> API`
  - 映射列表：生成 `API -> MAPS_TO -> API`
- API 节点字段：
  - `id=API:{API名称}`
  - `label=API`
  - `name={API名称}`
  - `source_url={DTK文档URL}`
  - `extra/library={PDF中对应二级标题}`
- 每份 PDF 都会新增一个 Runtime 节点。
- 对每个 API 节点做运行时关系覆盖检查，保证至少有一个 `SUPPORTS_API` 或 `COMPATIBLE_WITH`。
- 内置了多轮清洗规则，用于过滤表头、截断残片、明显拼接错误和部分枚举合并问题。

### 5.3 `batch_generate_dtk_graphs.py`

用途：

- 批量处理 `dtk文档` 目录中的所有 PDF。
- 每份 PDF 生成一组 CSV 到 `补充内容`。

运行方式：

```powershell
cd .\3_提取dtk文档_添加节点和关系
python .\batch_generate_dtk_graphs.py
```

输出示例：

- `补充内容/DTK_25.04.3_兼容性手册_nodes.csv`
- `补充内容/DTK_25.04.3_兼容性手册_edges.csv`

当前 `补充内容` 规模：

- 共 14 个 `_nodes.csv`
- 共 14 个 `_edges.csv`

### 5.4 `merge_dtk_graphs.py`

用途：

- 读取 DTK 补充 CSV。
- 读取第二阶段生成的 CSV。
- 合并并去重。
- 输出到 `最终版本`。

运行方式：

```powershell
cd .\3_提取dtk文档_添加节点和关系
python .\merge_dtk_graphs.py
```

去重规则：

- `nodes.csv`：按 `id` 去重，保留第一次出现的整行。
- `edges.csv`：按完整三元组 `(source_id, relation, target_id)` 去重。

编码处理：

- 读取 CSV 时优先尝试 `utf-8-sig`。
- 如果失败，回退到 `gb18030`。
- 写出时使用 `utf-8-sig`。

### 5.5 最终版中的人工补充

补充建议 2：

- `./3_提取dtk文档_添加节点和关系/最终版本` 中的 csv 文件是在执行完所有自动化的添加和整合数据的脚本之后，手动加入 hardware 节点和 supports runtime 关系得到的，未来建议将最后这一步也用自动化脚本实现。

当前最终版中额外人工补充的硬件节点包括：

- `hardware:BW150`
- `hardware:BW100`

当前最终版末尾还补充了这些硬件到 DTK Runtime 的 `SUPPORTS_RUNTIME` 关系。

注意：当前这些人工补充的 `SUPPORTS_RUNTIME` 边中，`target_id` 使用的是 `DTK 24.04.3`、`DTK 25.04.4` 这类 Runtime 名称，而不是 `runtime:dtk24043` 这类 Runtime 节点 id。后续如果追求图谱严格一致性，建议核对并统一为 Runtime 节点 id。

## 6. 最终版知识图谱结构

最终版说明文档：

- `3_提取dtk文档_添加节点和关系/最终版本/知识图谱数据说明.md`

主要实体：

- `Software`
- `Framework`
- `SoftwareInstance`
- `DeploymentConfig`
- `Hardware`
- `Runtime`
- `Dataset`
- `Guide`
- `Author`
- `API`

主要关系：

- `INSTANCE_OF`
- `USES_FRAMEWORK`
- `TRAINED_ON`
- `HAS_GUIDE`
- `DEVELOPED_BY`
- `SUPPORTS_RUNTIME`
- `SUPPORTS_API`
- `CONFIGURES_HARDWARE`
- `CONFIGURES_RUNTIME`
- `CAN_DEPLOY_ON`
- `MAPS_TO`
- `COMPATIBLE_WITH`

最终版当前关系规模概览：

- `SUPPORTS_API`：61981
- `COMPATIBLE_WITH`：3240
- `CAN_DEPLOY_ON`：434
- `INSTANCE_OF`：301
- `USES_FRAMEWORK`：301
- `HAS_GUIDE`：301
- `DEVELOPED_BY`：296
- `TRAINED_ON`：228
- `MAPS_TO`：95
- `SUPPORTS_RUNTIME`：38
- `CONFIGURES_RUNTIME`：10
- `CONFIGURES_HARDWARE`：10

最终版当前节点规模概览：

- `API`：5684
- `SoftwareInstance`：301
- `Software`：264
- `Guide`：256
- `Author`：76
- `Dataset`：64
- `Runtime`：23
- `DeploymentConfig`：10
- `Framework`：4
- `Hardware`：4

## 7. 复跑建议

建议按以下顺序复跑：

1. 复跑第 1 阶段 DeepSparkHub 爬虫。
2. 生成或更新第 2 阶段 `nodes_origin.csv` 和 `edges_origin.csv`。
3. 将第 2 阶段 `nodes_origin.csv` 和 `edges_origin.csv` 提供给第 3 阶段合并脚本。
4. 在 `3_提取dtk文档_添加节点和关系` 下运行 `python .\batch_generate_dtk_graphs.py`。
5. 在 `3_提取dtk文档_添加节点和关系` 下运行 `python .\merge_dtk_graphs.py`。
6. 手动或脚本化补充 DTK 硬件节点和 `SUPPORTS_RUNTIME` 关系。
7. 校验 `nodes.csv` 和 `edges.csv` 是否存在重复。

推荐校验项：

- `nodes.csv` 中 `id` 是否唯一。
- `edges.csv` 中 `(source_id, relation, target_id)` 是否唯一。
- 所有 `MAPS_TO` 是否都是 `API -> API`。
- 新增 API 是否至少有 `Runtime -> SUPPORTS_API/COMPATIBLE_WITH -> API`。
- 手动补充的 `SUPPORTS_RUNTIME` 是否使用了统一的 Runtime id。

## 8. 后续架构调整建议

补充建议 3：

- 现在的知识图谱架构中，author 是和 software 连接，构成 `DEVELOPED_BY` 关系，其实和 softwareinstance 建立连接更合适，由于时间原因未做修改。
- 修改方式很简单，只需要将 `./1_deepspark数据爬虫/crawl_deepsparkhub_new.py` 中的：

```python
add_edge(software_id, "DEVELOPED_BY", author_id_to_link)
```

改为：

```python
add_edge(instance_id, "DEVELOPED_BY", author_id_to_link)
```

- 然后重新运行程序生成第 1 步的 csv 文件，再重新执行第 2 步和第 3 步得到最终版本。

## 9. 已知问题和风险

- 第 2 阶段目前依赖 Gemini 人工分块提取，复现性弱，建议脚本化。
- 第 3 阶段最终硬件节点和 DTK `SUPPORTS_RUNTIME` 关系是人工加入，建议脚本化。
- 最终版 `nodes.csv` 曾经过人工编辑，读取时建议同时兼容 `utf-8-sig` 和 `gb18030`。
- DTK PDF 表格解析依赖当前手册版式。若后续手册版式变化，需要重新校验 `extract_dtk_api_graph.py` 中的章节识别、表格续行、API 清洗和关系生成规则。

