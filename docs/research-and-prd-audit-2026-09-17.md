# ScholarTree / PaperNexus 竞品调研与 PRD v1.0 审核

日期：2026-09-17  
范围：论文发现、引用网络、文献计量可视化、知识演进叙事、数据源与商业可行性。  
方法：以产品官网、官方帮助中心、API 文档和原始论文为主；价格和功能按访问当日页面记录。

## 1. 结论

建议继续验证，但不建议按当前 PRD 直接进入四周全功能开发。

现有市场已经证明“从种子论文生成关系图”有需求，也已有强竞品。当前方案真正可能成立的差异化不是缩放、节点大小或引用图本身，而是：

> 输入 1–3 篇种子论文，在 10 分钟内得到一条可核查的研究演进路线、关键转折论文和优先阅读清单；每一条关系都标明证据类型和数据来源。

当前 PRD 的四个致命风险是：

1. 把引用边解释为“因果、启发、继承”。引用只能证明 A 引用了 B，也可能是背景、比较或反驳。
2. 把局部、剪枝后的图指标当成论文的客观重要性。介数中心性会随采样范围显著变化。
3. 假定用户会为漂亮的图付费。用户更可能为节省阅读时间、发现遗漏和产出可复用结果付费。
4. 同时做 Web、Tauri、Python sidecar、动态图布局、LLM、存储和商业系统。四周只能形成 Demo，不能形成成熟产品。

产品名称也需要重新核查。GitHub 已存在多个 `ScholarTree` 和 `PaperNexus` 项目，其中已有项目与学者关系图、论文交互阅读有关。正式投入品牌前应检查商标、域名、应用商店和主要社交账号。

## 2. 竞品与替代方案

| 产品 | 已有能力 | 关系依据 | AI / 叙事 | 价格或限制 | 对本项目的含义 |
|---|---|---|---|---|---|
| [Connected Papers](https://www.connectedpapers.com/about) | 单篇种子生成相似论文图、Prior Works、Derivative Works、多种子图 | 共被引与文献耦合；官网明确说明它“不是 citation tree” | 无连续视口叙事 | 免费版每月 5 张图；高级版无限图 | “单篇论文生成图”不是差异点 |
| [ResearchRabbit](https://www.researchrabbit.ai/features) | 论文、作者和概念关系图，迭代推荐，收藏、协作 | 引用、参考文献和推荐算法 | 个性化推荐，非可信演进叙事 | [免费版](https://www.researchrabbit.ai/pricing)无限搜索/收藏、最多 50 个 seed；Plus 约 10 美元/月年付 | 免费基础能力很强，不能只靠可视化收费 |
| [Litmaps](https://www.litmaps.com/features) | Seed Map、引用发现、动态映射、监控、Zotero、分享 | 引用与参考文献 | 无本 PRD 所述连续叙事 | [免费版](https://www.litmaps.com/pricing)2 张图、每图 100 篇；Pro 约 10 美元/月 | 是最接近的商业竞品 |
| [Inciteful](https://inciteful.xyz/) | Paper Discovery、Literature Connector、引用网络、Zotero 导出 | 引用图和图分析 | 无连续叙事 | 免费、开源导向 | PageRank/图分析和上下游探索也不是空白 |
| [Semantic Scholar](https://www.semanticscholar.org/product) | TLDR、推荐、Research Feeds、Highly Influential Citations | 引用、引用上下文模型、语义推荐 | 单篇 TLDR | 免费 | “摘要 + 重要引用”已有免费替代品 |
| [scite](https://doi.org/10.1162/qss_a_00146) | 展示引用上下文并区分 supporting、contrasting、mentioning | 引用上下文分类 | Assistant；当日公开页无法完整核验 | 付费/机构产品，精确当日价格未核验 | 证明“边的语义”已是产品能力；本项目需把它与宏观路线结合 |
| [Citation Gecko](https://github.com/CitationGecko/gecko-react) | 前后向引用、seed 递归扩展、表格/网络切换、Zotero/BibTeX | 直接引用 | 无 | MIT 开源；当日公开 demo 访问受限 | 早期 MVP 的基础发现流程已有开源基线 |
| [VOSviewer](https://www.vosviewer.com/) | 引用、共被引、文献耦合、合作与术语网络，可缩放和聚类 | 文献计量网络 | 无面向新手的脉络叙事 | 免费桌面/在线工具 | 专业文献计量用户已有成熟工具 |
| [CiteSpace](https://doi.org/10.1002/asi.20317) | 时间区视图、聚类、突现检测、介数中心性突出转折点 | 引用/共被引和文献计量 | 以分析解释为主 | 学术工具 | “时间轴 + 介数找关键节点”至少自 2005 年已有公开方法 |
| [Local Citation Network](https://localcitationnetwork.github.io/) | 本地引用网络、前后向检索、共引、引用上下文、CSV/RIS/JSON 导出 | OpenAlex / Semantic Scholar 等 | 有限 | 免费 Web 工具 | 本项目必须在可信解释和工作流上胜出 |

市场空白更准确地说是：现有工具大多擅长“发现和展示”，但较少把一个局部图转换成可验证、可编辑、可导出的研究演进路线。这个空白需要用户验证，不能仅凭竞品页面推断付费需求。

ResearchRabbit 与 Litmaps 的官网页脚目前都标注 Litmap Ltd.。这意味着“地图 + 推荐 + 监控”两条直接竞品路线已在同一经营主体下汇合，更容易快速互相补齐；不能把普通引用图或文献监控当作长期壁垒。

## 3. 逐条审核

### 3.1 文档概述与产品定位

| 原文 | 判断 | 修改建议 |
|---|---|---|
| “知识链拓扑分析工作台” | 可保留为内部描述，外部理解成本高 | 外部副标题改为“可验证的论文演进地图” |
| “有向时间轴与多级语义缩放” | 是交互方案，不是商业价值 | 价值主张先写节省什么时间、帮助做什么决策 |
| “因果拓扑” | 删除 | 改为“引用与语义证据支持的演进网络” |
| “低被引关键桥接论文” | 可作为假设，不能先当承诺 | 先验证专家是否认可算法找到的桥接论文 |
| Web + Windows/Tauri | MVP 范围过大 | P0 只做 Web；验证留存后再决定桌面端 |

首要用户应明确为：已经掌握 1–3 篇种子论文、正在进入陌生细分方向的硕博研究生。首要任务是建立阅读顺序和研究背景，不是自动完成系统综述。

### 3.2 核心业务流程

当前流程是“输入 → 抓取 → 计算 → 看图”，缺少用户成果和反馈回路。应增加：

- 支持 1–3 篇种子，而非只支持单篇。
- 导入 DOI、arXiv、PMID、OpenAlex ID、URL、BibTeX、RIS；Zotero 导入优先于 Tauri。
- 节点的待读、已读、收藏、排除、备注、相关/不相关反馈。
- 输出优先阅读清单、关键路径、为什么应读。
- 导出 BibTeX、RIS/CSV、PNG/PDF 和可分享链接。
- 显示检索范围、构图时间、数据源、算法版本和遗漏风险。

### 3.3 F-101 多模态种子输入

“多模态”用词错误，这些都是文本标识符。改名为“多标识符种子解析”。

必须补充：

- 标题模糊搜索，而非仅精确英文标题；支持非英文标题。
- 候选项显示摘要片段、作者、年份、来源、DOI 和匹配置信度。
- arXiv 预印本与正式发表版本合并，并保留版本关系。
- 同名、撤稿、勘误、数据污染和错误合并的处理。

arXiv ID 解析不能只依赖 OpenAlex。建议先用 arXiv API 取规范标题、作者和 DOI；有 DOI 时查 OpenAlex，无 DOI 时做标题 + 作者 + 年份匹配，再由 Semantic Scholar 的 `ARXIV:<id>` 解析作为可选补充。低置信结果始终要求用户确认。

这是必须先验证的数据质量点。2026-09-17 对 OpenAlex 的现场查询中，`Attention Is All You Need` 的首个标题结果返回了一条 2025 年同名记录，而经典 2017 论文没有排在首位；按 `1706.03762` 搜索还返回了明显无关、引用数异常的记录。产品不能把上游检索第一名直接当真，必须进行 DOI/作者/年份/来源的交叉校验。

PRD 响应示例中的 `W2964177114` 当日返回 404，也不应把任何外部数据库 ID 永久硬编码为演示真值。测试和演示应先动态解析，再固定内部 canonical ID 与来源快照。

### 3.4 F-102 抓取与剪枝

固定“前 10 年、后 5 年”不适合跨学科；固定每层 Top 15–20 也会形成路径依赖。

建议：

- 默认采用节点预算，时间窗口由领域模板和用户控制。
- 候选来源分开记录：直接引用、被引用、共被引、文献耦合、语义相似。
- 排序同时考虑种子相关性、直接路径距离、年份/领域归一化影响力和多样性。
- 每个节点保存 `selection_reason`，说明为何进入图谱。
- 首屏先返回 10–20 个骨干节点，再渐进补齐 50–100 个探索节点。
- 保存构图参数和候选被淘汰原因，保证可复现和可解释。

把固定时间窗改成三种模式：祖先模式向前追溯、后继模式追到当前、双向模式按预算自适应。时间滑块优先作为显示过滤器，不要在默认情况下永久删除底层候选。允许稀疏主题少于 80 个节点，不能为满足下限加入噪声。

“整个历史从何而来”不能作为完整性承诺。OpenAlex 明确说明 `referenced_works` 可能短于论文真实参考文献表，因为来源缺失、未匹配或 Crossref 未提供参考文献。[官方说明](https://help.openalex.org/data/works/citations/)

### 3.5 F-201 综合权重

当前单一分数不应直接上线：

- 原始引用数偏向老论文和高引用学科。
- 局部图的介数中心性高度依赖剪枝策略。
- Citation Velocity 对刚发表论文不稳定，且 `counts_by_year` 只覆盖最近十年。
- PageRank 在流程图出现，却未进入公式。
- `0.4/0.4/0.2` 没有用户或离线评测依据。

改为三个可切换维度：

1. **影响力**：优先使用 OpenAlex 的 `fwci` 或 `citation_normalized_percentile`，并显示数据缺失。
2. **桥接性**：局部介数 + 跨聚类连接，但明确标注“仅对当前采样图有效”。
3. **主题相关性**：语义相似、引用距离、多种子覆盖度和用户反馈。

节点大小只能表达当前选中的一个维度；颜色表达聚类；描边表达新近增长或桥接。抽屉应展示各分量，禁止把综合分数包装成客观真理。

若保留 Citation Velocity，必须定义公式。MVP 可用最近两个完整自然年的平均引用量取 `log1p`，排除当年不完整数据，再按领域和论文年龄转为 percentile。不要在每张图内单独做 min-max 后跨图比较，因为同一论文会因邻居不同而改变大小。

### 3.6 F-202 时间轴布局

- OpenAlex 原始边是“本论文 → 它引用的论文”，即通常从新到旧。若界面想显示“早期 → 后期”的影响流，必须将其标为派生的 `influence_flow`，同时保留原始 `citation` 方向。
- 同月和月份缺失无法保证严格顺序；在线发表、预印本和正式发表还可能形成日期冲突。
- 社团 ID 没有天然纵向顺序。聚类应在无向的混合相似图上做，而不是直接对稀疏 DAG 强行聚类。
- 优先 Leiden。原论文指出 Louvain 可能产生连接很差甚至不连通的社团，而 Leiden 提供连接性保证。[Traag et al., 2019](https://doi.org/10.1038/s41598-019-41695-z)
- 动态扩图时应固定已有节点，局部放置新增节点，避免破坏用户空间记忆。
- 微观层也不应显示全部边；默认只显示骨干边，用户按类型打开其他边。

Sigma.js 适合渲染，并支持节点/边 reducer 和箭头类型，但坐标、聚类、碰撞规避和宏观气泡需要应用自己实现。[Sigma.js 数据模型](https://www.sigmajs.org/docs/advanced/data/)

### 3.7 F-301 / F-302 语义缩放

`35%` 和 `75%` 是待实验的实现参数，不应写成固定业务规则。阈值应由屏幕像素密度、当前节点数和标签碰撞动态决定。

三层可改为用户任务：

- **领域层**：主题、时间跨度、代表论文、分支规模。
- **路线层**：10–30 个骨干节点、关键路径和转折点。
- **论文层**：元数据、证据、引用上下文和用户操作。

必须补充面包屑、迷你地图、返回上级、重置视图、固定节点、键盘/触控板操作、标签遮挡策略和减少动画选项。“气泡炸开”和粒子动效降到 P2。

### 3.8 F-401 节点交互

把“受谁启发 / 启发了谁”改为“引用了谁 / 被谁引用”。只有取得引用上下文并分类后，才能谨慎标记“使用、扩展、比较、支持、反驳”；无法判断时显示“关系未知”。

抽屉增加：

- 数据来源、最后更新时间、版本、撤稿/更正标记。
- 入选原因、关系证据、算法置信度。
- 待读/已读/收藏/排除/备注。
- 导出引用、打开来源、添加 Zotero。
- 原始摘要与 AI 内容视觉分离。

OpenAlex 的 `open_access.oa_url` 是可免费阅读位置，不等于所有内容都可由商业产品重新分发。产品应链接到合法位置；只有在许可证允许且确有需要时才做代理下载。[OpenAlex OA 说明](https://help.openalex.org/data/works/open-access/)

摘要也需要逐字段许可策略。OpenAlex 用 `abstract_inverted_index` 而非纯文本，并说明这样做有法律原因；技术上可还原不等于当然拥有商业再分发权。Semantic Scholar 的数据又可能受 CC BY-NC、ODC-BY 与第三方权利约束。缓存、展示或发送到第三方 LLM 前，应建立“来源 × 字段 × 用途 × 许可 × 保留期”矩阵。

### 3.9 F-402 动态生长

新增节点会改变分数、聚类、布局、叙事和缓存，PRD 需定义图版本。

建议流程：预览新增数量与方向 → 用户确认 → 局部插入 → 后台生成新图版本 → 可撤销。达到预算时允许替换低相关节点或创建新分支。`Top 10` 必须声明排序依据。

### 3.10 F-501 / F-502 视口叙事

删除“平移或缩放后自动调用 LLM”。它会造成内容跳动、成本浪费和不可复现。改为：

- 用户主动点击“解释当前视图”。
- 以稳定的节点集合或聚类 ID 为输入，不以像素位置为知识边界。
- 每个事实性句子带论文编号；点击可定位到节点与证据。
- 区分“原文明确陈述”“模型综合判断”“证据不足”。
- 无摘要时不允许用标题和邻居标题推断论文贡献。
- 缓存键包含排序后的节点 ID、边、图版本、数据版本、模型、Prompt 版本、语言和输出模式。
- 支持纠错、编辑、重新生成，并记录成本和延迟。

`120–180` 字可作为折叠摘要，但应有可展开的详细版。核心质量指标是事实支持率，不是字数。

### 3.11 E-101 至 E-103

- **E-101**：方向定义错误。按 PRD 自定义的“早 → 晚”影响流，新论文没有衍生工作表现为出度为零；按 OpenAlex 原始引用边则是入度可能为零。应分别命名两个方向，避免混淆。
- **E-102**：删除“降级推理模式”。显示数据不足，只展示标题、年份和已知连接。
- **E-103**：两次重试过少且 `1s, 3s` 不是标准指数序列。遵循 `Retry-After`，区分瞬时 429 与日额度耗尽；后者重试不会成功。备用缓存只能覆盖访问过的数据，不能保证首次查询。

还需增加：任务进度、部分结果、取消/恢复、上游字段缺失、重复记录、撤稿、图无连通路径、超大引用数、LLM 超时、预算耗尽和删除账户数据。

### 3.12 架构与技术栈

| 现方案 | 审核 | 建议 |
|---|---|---|
| React + TypeScript + Sigma.js | 可用 | 保留；性能不是首要风险，可读性和稳定布局才是 |
| FastAPI + NetworkX | 原型可用 | 保留；生产任务放到异步 worker，图计算先不引入复杂分布式系统 |
| CDlib 的 Leiden/Louvain | 描述不精确 | 明确所用后端；优先 `igraph`/`leidenalg` 或已验证实现 |
| IndexedDB + SQLite | Web 与桌面边界混乱 | Web 首版用托管数据库；IndexedDB 只做短期缓存与离线草稿 |
| Tauri + Python sidecar | 技术上可行但显著增加打包、签名、更新和多架构成本 | PMF 前删除；Tauri 官方确实支持把 Python API server 打成 sidecar，但不是“免费功能” |
| REST / WebSocket / SSE | 同时存在但职责未定义 | 构图用 job + 轮询或 SSE；LLM 用 fetch streaming；无需 WebSocket |

“零服务器成本”与 Web 后端、账户、支付、日志和共享项目不相容。OpenAlex 数据本身是 CC0，但 2026 年 API 是按使用量计费：免费 API key 每日有 1 美元额度；列表/筛选每 1000 次 0.10 美元，搜索每 1000 次 1 美元，内容下载每 1000 份 10 美元。[定价](https://help.openalex.org/access/pricing/)｜[示例成本](https://help.openalex.org/access/example-costs/)

按每个 150 节点各做一次反向引用 filter 粗估，单图约 0.015 美元，尚未包含高被引论文分页、搜索、全文和 LLM。免费层足以做原型，但商业流量必须设置每图请求预算、服务端排序 Top-K、批量 OR 拉元数据和成本告警。Semantic Scholar 更适合在用户点击节点或边时补充 citation context / intent / `isInfluential`；其 key 的常见初始端点额度约 1 RPS，不适合作为首屏递归主干。

原 PRD 对 Tauri “10–20 MB、内存减少 80%”的承诺没有当前方案的测量依据。Python、PyInstaller、NetworkX 和 igraph sidecar 会显著扩大包体，并引入端口、权限、健康检查、崩溃回收与升级测试。

### 3.13 API 合约

`POST /graph/build` 被描述为异步，却同步返回整图。改为：

1. `POST /api/v1/graphs`：校验种子和参数，返回 `graph_id`、`job_id`。
2. `GET /api/v1/jobs/{job_id}`：阶段、进度、部分结果、错误、上游额度。
3. `GET /api/v1/graphs/{graph_id}?version=n`：返回带 provenance 的图。
4. `POST /api/v1/graphs/{graph_id}/expansions`：创建可撤销扩展。
5. `POST /api/v1/narratives`：创建带证据的叙事；用 fetch stream 或 `GET` SSE 读取。

补充：幂等键、取消、超时、部分失败、鉴权、访问控制、图版本、算法版本、数据快照时间和缓存策略。原生浏览器 `EventSource` 只支持 GET；若保留 POST + `text/event-stream`，前端需用 `fetch` 读取流。

### 3.14 四周路线图

原路线图可做技术 Demo，不可叫商业 MVP。更合理的顺序：

- **第 1–2 周：异步问题与交付验证**。用户通过表单提交种子；半人工完成至少 15 份路线，以只读链接交付；用打开论文、加入待读、导出、复用与付款行为验证，不要求同步访谈。
- **第 3–4 周：数据质量原型**。只做 CLI/Notebook 或静态网页，测试 20 个主题、三类学科、候选召回和关键路径。
- **第 5–8 周：Web Alpha**。种子解析、骨干图、证据抽屉、阅读状态、导出、项目保存。
- **第 9–12 周：可信叙事与计费实验**。按需叙事、引用编号、错误反馈、成本计量、付费墙。
- **留存成立后**：Zotero 深度集成、分享、协作、监控；桌面端最后评估。

## 4. 必须先验证的假设与停损条件

| 优先级 | 假设 | 低成本实验 | 继续门槛 | 失败动作 |
|---|---|---|---|---|
| P0 | 用户经常需要从种子论文理解脉络 | 公开提交页获得至少 30 次有效种子提交 | 至少 15 份结果被打开；≥20% 在 14 天内提交第二个主题 | 换人群或换任务 |
| P0 | 路线与清单比普通关系图更有价值 | 半人工交付 15 份结果并记录行为 | ≥40% 加入待读或导出；≥30% 打开至少 3 篇论文 | 缩成报告工具或停止复杂图形 |
| P0 | 用户愿意付款 | 同时展示 19/39/69 元价格并收可退订金 | 至少 5 人支付或明确进入付费试用 | 不做桌面端和协作，重做价值主张 |
| P0 | 数据能可靠识别种子和版本 | 100 个跨学科种子集 | 标识符成功率 ≥95%；错误合并 <1% | 增加多源校验或限制学科 |
| P0 | 关键路径可信 | 20 个主题、领域专家盲评 | Top 20 相关率 ≥60%；关键路径覆盖 ≥70% | 不宣传“关键桥梁” |
| P0 | AI 叙事可核查 | 人工审计 100 条事实 | 无证据或证据不支持 <5% | 只输出抽取式内容 |
| P1 | 使用会重复发生 | Alpha 行为数据 | 两周复用 ≥30%；4 周留存 ≥15% | 收缩为一次性路线报告 |
| P1 | 单位经济成立 | 记录每次构图和解释成本 | 数据 + 模型成本 < 收入 10–15% | 收紧额度、BYOK 或调整价格 |

“图很好看”不算成功。有效发现定义为：用户在首次会话中保存、导出或加入待读至少 3 篇论文。

关键路径实验还应做采样敏感性测试：同一种子以 80/150/300 节点、不同时间窗和剪枝策略重复构图，比较 bridge Top-10 的 Jaccard / Kendall 稳定性。若不稳定，只能称为“当前图中的桥接角色”。另用 30–60 篇跨计算机、医学、物理与人文的论文，从 PDF 人工建立小型真值集，测 reference recall、摘要命中、OA 链接有效率、版本重复和日期冲突。

## 5. 商业建议

首轮可测试：免费版每月 3 个项目、每图 100 篇、有限解释；学生 Pro 中国区 29–49 元/月、国际区 6–10 美元/月；实验室版在协作需求被验证后再测试。

ResearchRabbit 和 Litmaps 已将个人付费锚点放在约 10 美元/月，单纯限制图数量缺乏竞争力。付费能力应围绕可验证叙事、阅读路线、导出、监控和团队复用。

以 39 元/月、500 名付费用户计算，月收入为 19,500 元；若免费转付费为 3%，需约 16,700 名活跃免费用户。因此增长必须依靠公开可分享地图、Zotero 工作流、课程与实验室传播、搜索流量，而不能依赖买量。

## 6. 研究限制

- 产品功能和价格会变化，本文只代表 2026-09-17 可访问的官方页面。
- 未进行真实用户行为测试或付费实验，因此“市场空白”和定价均为待验证假设。同步访谈不是必需条件，但必须接触真实用户并观察结果使用行为。
- OpenAlex 现场异常只证明产品必须做多源校验，不能据此推断整个数据源普遍不可用。
- 图算法的最终权重需要用领域专家标注集和用户行为数据校准，不能由本报告直接确定。

## 7. 主要来源

- [Connected Papers: About](https://www.connectedpapers.com/about)
- [ResearchRabbit: Features](https://www.researchrabbit.ai/features)；[Pricing](https://www.researchrabbit.ai/pricing)
- [Litmaps: Features](https://www.litmaps.com/features)；[Pricing](https://www.litmaps.com/pricing)
- [Semantic Scholar Product](https://www.semanticscholar.org/product)；[API](https://www.semanticscholar.org/product/api)
- [Inciteful](https://inciteful.xyz/)
- Nicholson et al. (2021). [scite: A smart citation index](https://doi.org/10.1162/qss_a_00146)
- [Citation Gecko repository](https://github.com/CitationGecko/gecko-react)
- [VOSviewer](https://www.vosviewer.com/)
- [Local Citation Network](https://localcitationnetwork.github.io/)
- Chen, C. (2006). [CiteSpace II](https://doi.org/10.1002/asi.20317)
- Traag, V. A., Waltman, L., & van Eck, N. J. (2019). [From Louvain to Leiden](https://doi.org/10.1038/s41598-019-41695-z)
- [OpenAlex Works](https://help.openalex.org/data/works/)；[Citations](https://help.openalex.org/data/works/citations/)；[Attributes](https://help.openalex.org/data/works/attributes/)
- [OpenAlex Pricing](https://help.openalex.org/access/pricing/)；[Example Costs](https://help.openalex.org/access/example-costs/)；[Authentication](https://help.openalex.org/api/authentication/)
- [Semantic Scholar Graph API](https://api.semanticscholar.org/api-docs/graph)；[API License Agreement](https://www.semanticscholar.org/product/api/license)
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [Sigma.js](https://www.sigmajs.org/docs/)；[Tauri sidecars](https://v2.tauri.app/develop/sidecar/)

本报告使用 AI 辅助检索、核对和整理；关键外部事实均附可访问来源，产品假设单独标注为待验证。
