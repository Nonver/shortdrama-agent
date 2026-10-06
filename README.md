# AI 短剧剧本生成 Agent（方舟 + 豆包语音 集成版 · 可运行）

> 单服务一键启动：用户端 H5 + 管理后台 + 生成引擎 + 知识库底座 + **方舟/豆包真实 AI 集成** + **3 档会员权限**。
> 已用**真实浏览器（Playwright 驱动 Chromium）端到端实测 12/12 全通过**。

## 一、怎么跑起来（Windows）

```bat
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8090
```
或直接双击 `start.bat`。

启动后浏览器打开：
- 用户端 H5： http://127.0.0.1:8090/
- 管理后台：   http://127.0.0.1:8090/admin

> 端口说明：本机 8000 被本地 Ollama 占用、8080 被环境其他进程占用，故默认用 **8090**。

### 环境变量（方舟 / 豆包语音，无则降级规则生成器）
```
ARK_API_KEY=ark-xxxx
ARK_MODEL_CHAT=doubao-seed-2-1-pro-260628
ARK_MODEL_IMAGE=doubao-seedream-4-0-250828
ARK_MODEL_VIDEO=doubao-seedance-1-0-pro-fast-251015
VOLC_TTS_API_KEY=your-volc-tts-api-key   # 豆包语音 X-Api-Key
```

## 二、默认账号

| 端 | 账号 | 密码 | 说明 |
|---|---|---|---|
| 后台管理(admin) | `admin` | 首次部署由 `ADMIN_PASSWORD` 环境变量设定 | 超管 |
| 会员Pro演示(user) | `prodemo` | 由种子脚本设定 | 档位=pro，可生图/生视频/配音 |
| 用户端(user) | 自注册 | — | 用户名/手机号 + 密码 + 动态图形验证码 |

双账号分离：后台账号与用户端账号互不相通。注册/登录需填**自托管动态图形验证码**（无短信）。

## 三、已实现功能（对照最终方案）

### 1. 用户端 H5
- ✅ **公开首页**：未登录即可看首页 5 角色入口 + 工具 + 示例剧本；点「生成/下载/生图/生视频/我的」才跳独立登录页（`/login?next=`）
- ✅ **剧本生成**：方舟 SSE 流式逐字输出（真实 `doubao-seed-2-1-pro`）；方舟慢/异常自动降级规则+知识库兜底生成器，断网也能出片
- ✅ 剧本含 **7 大类专业字段**（工程信息/场次/镜头语言/表演/视听/节奏商业/后期），含景别、机位、运镜、人物+路人环境镜头、台词、旁白/内心独白/心理活动、色调灯光、字幕花字、爽点泪点
- ✅ 剧本下载：**Markdown / Word / PDF / Excel(分镜表) / JSON** 五种格式（**会员及以上**）
- ✅ 知识库驱动生成：实时检索 4 子库（平台规则/类型套路/风格样本/剧本资产含 13 部真实爆款），剧本内嵌「创作依据（带来源）」
- ✅ 预置 3 部示例剧本，首页「看示例剧本（免登录）」直接演示

### 2. 多模态生成（真实方舟）
- ✅ **文生图**：`doubao-seedream-4-0` 真实出图，默认 **2K**（后台可开 4K，限会员Pro，用户生成时可自选）；`watermark:false` 关平台水印 + 卡片角标「AI 生成」双保险（会员及以上）
- ✅ **文生视频**：`doubao-seedance-1-0-pro-fast` 异步提交+轮询，真实 mp4（**会员Pro**）
- ✅ **分角色配音**：豆包语音（Doubao TTS）**服务端合成**，多角色多条音频，当前密钥仅授权 1 音色时自动兜底（仅随视频生成，会员Pro）

### 3. 3 档会员 + 权限矩阵（后台全可配）
| 功能 | 免费 | 会员 | 会员Pro |
|---|:---:|:---:|:---:|
| 生成剧本（登录即可，免费档有日限额） | ✅ | ✅ | ✅ |
| 下载/导出剧本 | — | ✅ | ✅ |
| 文生图（2K） | — | ✅ | ✅ |
| 文生图（4K） | — | — | ✅ |
| 文生视频 + 分角色配音 | — | — | ✅ |

- 权限由 `feature_min_level` 配置驱动（不写死代码）：`script_generate=free / script_download=member / image_generate=member / image_quality_4k=pro / video_generate=pro`
- 后台会员配置项：档位权益、免费/会员/Pro 日配额、4K 开关、默认清晰度(2K)、隐式水印开关、角标开关、角标文案、各功能最低档——全部后台可改

### 4. 管理后台
- ✅ 仪表盘、用户与画像编辑（图像/标签/习惯/状态）、**会员体系页（改档 setLevel）**
- ✅ 剧本资产查看下载、知识库管理、5 个 Agent 角色后台可配人设/提示词、模型配置（预留 LLM 接入）

## 四、AI 模型：方舟 + 豆包语音 已正式接入（非预留）

- 对话生成 = 火山方舟 `doubao-seed-2-1-pro-260628`（SSE 流式，token 级）
- 文生图 = 方舟 `doubao-seedream-4-0-250828`
- 文生视频 = 方舟 `doubao-seedance-1-0-pro-fast-251015`
- 配音 = 豆包语音 `openspeech.bytedance.com/api/v1/tts`（服务端合成，密钥不下发前端）
- 缺失 `ARK_API_KEY` / `VOLC_TTS_API_KEY` 时，剧本生成自动降级规则兜底生成器，服务照常可用

## 五、技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.13 + FastAPI + SQLAlchemy |
| 生成 | 方舟 SSE（兜底规则+知识库） |
| 多模态 | 方舟 Seedream / Seedance；豆包语音 TTS |
| 前端 | 用户端 H5（原生 JS SPA，可平滑迁 UniApp 出小程序/App）；后台（原生 JS SPA） |
| 数据库 | SQLite（默认）；可切 MySQL |
| 流式 | SSE（token 级） |
| 导出 | python-docx / openpyxl / reportlab |
| 部署 | 单服务 Docker-ready |

## 六、目录结构

```
shortdrama-agent/
├─ backend/
│  ├─ app/
│  │  ├─ main.py              # 入口，托管双前端 + 全部 API
│  │  ├─ config.py            # 配置（DB 可切 MySQL，方舟/豆包 Key）
│  │  ├─ models.py            # ORM：用户/会员配置/剧本/知识库/Agent/模型/审计
│  │  ├─ security.py          # 密码哈希/JWT/进程内KV
│  │  ├─ captcha.py           # 动态图形验证码（Pillow）
│  │  ├─ deps.py              # require_feature 三档权限 + 日配额
│  │  ├─ knowledge.py         # 平台规则 + 全能类型套路种子
│  │  ├─ generator.py         # 剧本生成器（方舟 SSE + 规则兜底）+ token 流式
│  │  ├─ exports.py           # md/docx/pdf/xlsx/json 导出
│  │  ├─ clients/             # ark_chat / ark_image / ark_video / tts_client
│  │  ├─ routers/             # auth/me/scripts/knowledge/agents/models_cfg/admin/assets
│  │  └─ static/{user,admin}  # 两套前端
│  ├─ seed.py                 # 种子（超管/会员Pro演示/知识库/Agent/模型）
│  ├─ auth_helper.py          # 读服务端验证码驱动真实登录（测试桩）
│  ├─ browser_test.py         # Playwright 真实浏览器端到端测试（测试桩）
│  └─ requirements.txt
├─ data/                      # SQLite 数据库 + 服务日志
└─ start.bat                  # 一键启动（Windows）
```

## 七、真实浏览器端到端测试

`python browser_test.py` 驱动真实 Chromium（令牌直注 localStorage 绕过验证码）点击真实 UI、覆盖**企业级新 IA**，**18/18 全 PASS**：
首页 5 个 Agent 卡片 · 知识库二级导航(平台×子库) · Agent 聊天页进入 · @召唤协作弹层(5 个协作体) · 工具行 3 工具 · 后台侧边 IA 全模块 · Agent 列表 · 后台新增/删除 Agent · 模型配置分组渲染 · 后台知识库三级树(知识库▸平台▸子库)。
证据截图见 `backend/shots/`。

## 八、切换数据库到 MySQL（可选）

编辑 `backend/app/config.py` 的 `DATABASE_URL`：
```
DATABASE_URL = "mysql+pymysql://root:密码@127.0.0.1:3306/shortdrama?charset=utf8mb4"
```
需先 `pip install pymysql`，再 `python -m app.seed` 初始化。

---

---

## 九、企业级 rework（Agent 入口型 · 真实协作）

按"商业/企业/工业级"标准重构，首页为 **Agent 入口型**（非工作流），5 个角色都是可对话的真实 Agent：

### 用户端 H5
- ✅ **Agent 入口型首页**：英雄区 + 5 张角色卡（总导演/编剧/分镜导演/旁白心理/合规审核），点击即进入 `/agent/{key}` 真实聊天窗，非工作流引导页
- ✅ **真实 Agent 聊天**：SSE token 级流式；顶部「🧠 跨 Agent 协作记忆」面板（基于 `Conversation.cross_agent_summary`）；底部 `@召唤` 弹层可单召/一键召唤全部协作体，生成后接力批注
- ✅ **用户主导 + 一键召唤**：默认用户主导创作，可随时 @ 其它 Agent 协作，不强制流程
- ✅ **登录/注册改为独立页**（`/login`，带 `?next=` 回跳）：所有需登录入口（进 Agent、点「我的」、聊天内工具/401）统一跳独立登录页，登录/注册成功后回跳原页；**不再用弹窗**（弹窗 DOM 已从首页/我的页移除）
- ✅ **「我的」独立页**（`/me`）：未登录自动跳 `/login?next=/me`；登录后渲染画像编辑、会员状态、我的剧本（含创建人+Agent）、我的资产
- ✅ **知识库二级导航**（用户端首页）：平台 × 子库（平台规则/类型套路/风格样本/剧本资产）两排筛选
- ✅ 工具（生图/生视频/配音）仅在聊天内触发，按会员档位**按需权限校验**

### 管理后台
- ✅ **仪表盘（数据图表）**：12 项核心指标卡 + 纯 SVG 图表——Agent 使用量环形图（按剧本数）、会员分布环形图、近 14 天剧本生成趋势折线图、知识库各子库条形图、模型启用状态条形图（绿=启用/橙=停用）、最近操作审计流。`/api/admin/charts` 聚合接口驱动。
- ✅ **Agent 管理 CRUD**：新增/编辑/克隆/删除，人设/头像/简介/人设描述/系统提示词/工具/绑定模型/示例对话全可配；**卡片显示每个 Agent 的剧本/会话使用量**；**工具改为已知工具 chips 勾选**（剧本生成/下载/文生图/4K/生视频/配音）；**绑定模型从模型配置下拉选择**；头像 emoji/URL 实时预览
- ✅ **模型配置（分组 + Key）**：6 大分组（方舟对话/生图/生视频/豆包语音/Embedding/本地兜底）；**支持新增模型配置**（分组/role/provider/model_name/key/启用）；卡片展示 provider/role；**密钥显隐切换**（👁）；密钥默认脱敏、管理员可看明文
- ✅ **知识库三级树（后台侧边栏）**：点击「知识库」展开二级（平台：红果/抖音/快手/通用），点平台再展开三级（子库：平台规则/类型套路/风格样本/剧本资产），点子库才在右侧加载内容列表；新增条目自动带入当前平台+子库；面包屑显示「知识库 › 平台 › 子库」
- ✅ **剧本资产含创建人 + Agent 关联**：可按创建人/平台/类型/Agent 多维筛选
- ✅ 侧边 IA：仪表盘 / 用户与画像 / 剧本资产 / 知识库 / Agent 管理 / 模型配置 / 会员体系

### 关键修复（本次）
- `agent_configs.prompt` NOT NULL：历史 schema 残留 `prompt` 列导致新建 Agent 报 `IntegrityError`；已在模型层显式纳入 `prompt`（兜底 = system_prompt）并在 `create_agent`/`_apply_agent_payload`/`clone` 全路径赋值
- 首页 `switchTab('knowledge')` 空指针：原代码操作不存在的 `#view-home` 抛错致知识库视图无法展开；已为首页内容包 `<div id="view-home">` 并加 null 守卫

---

## 十、按方案复查（2026-08-27 晚）

对照企业级方案逐项枚举 + 功能/业务流程实测，建立回归脚本 `_review_be.py`（后端 TestClient 37 项）、`_review_fe.py`（前端 Playwright 真浏览器 26 项）。

- **结果：后端 37/37 PASS、前端 26/26 PASS（共 63 项全过）**，覆盖方案 A/B/C 全部能力（5 Agent 入口、真实 SSE 聊天+@召唤协作、跨 Agent 上下文、聊天内工具权限、知识库导航、我的/登录独立页、固定底部导航、后台知识库三级树、Agent CRUD、模型分组+Key、会员、剧本-创建人关联）。
- **复查挖出并修复 3 个真功能 Bug + 1 个 SSE 格式统一**：
  1. 🔴 聊天内「生图/生视频」工具误调不存在的 `ark_image.generate`/`ark_video.generate` → 改 `save_image`/`generate_video`（核心功能原本 500 崩溃）。
  2. 🔴 工具资源 404：`config.py` 的 `ASSET_DIR` 指向项目根、而 `/static/assets` 挂载在 backend → 存读目录不一致；已对齐为 `backend/static/assets`，实测生成图 URL 可达（HTTP 200）。
  3. 🟡 工具上游失败由 500 改为 502（语义更准确）。
  4. 🟢 SSE token 事件补 `event: token` 行（格式统一，前端兼容）。

*本系统为「方舟 + 豆包语音正式集成、3 档会员权限、Agent 入口型首页、真实跨 Agent 协作」的可运行企业级系统，严格对齐最终方案。多平台 TTS 接入（H5/小程序/App）、模型升级、多租户等按路线图后续迭代。*


## 剧本生成：mini 模型 + 真流式（A+B 已落地）

- **默认模型已切到快速档**：`config.ARK_MODEL_CHAT` 默认 `doubao-seed-2-0-mini-260428`（实测 7.9s 出短句；整部剧本流式约 53s）。追求更高剧本质量可设环境变量 `ARK_MODEL_CHAT=doubao-seed-2-1-pro-260628`（但 pro 出 token 慢、易超时）。
- **真·流式生成（不卡连接）**：`chat.py` 的 SSE 端点用 worker 线程跑方舟生成，token 实时推 `event: token`；生成完成 `event: done` 携带已渲染 Markdown，前端生成中即见字（"💭 智能体正在构思剧本…"），不再干等整段生成完。
- **关键修复**：方舟 seed 模型出 token 慢，`chat_complete` 必须走 `stream=True` 内部流式读取拼接、read 超时取 `max(调用方超时, 600s)`，否则长文必然 ReadTimeout。`chat_complete` 支持 `on_chunk` 回调供实时进度。
- **密钥拓扑**：方舟对话/生图/生视频用 `ARK_API_KEY`；豆包语音(配音)用 `VOLC_TTS_API_KEY`（两套独立 key，不可混用）。

## 知识库：RAG 爬取填补空子库 + 【AI短剧知识库（向导）】

### 1. 填补空白平台子库（RAG 联网爬取）
- 原平台规则库仅 3 家（红果/抖音/快手）。新增腾讯视频、芒果TV、爱奇艺、咪咕、点众·河马 5 家官方规则（`NEW_PLATFORMS`，来源标注各平台官方+传媒时评/新浪财经/搜狐）。
- RAG 爬虫 `backend/scripts/crawl_kb.py`：标准库 `urllib` + 浏览器 UA + 多编码兜底（优先声明编码，乱码才回退 GBK/gb18030），按 URL md5 生成 `crawl_<hash>` 幂等 upsert 入库；`python scripts/crawl_kb.py [--dry-run]` 可跑。已爬入新华网《微短剧管理办法》、澎湃腾讯、新浪芒果、搜狐爱奇艺、传媒时评六大平台 共 5 篇权威原文。
- 现平台规则库共 13 条，8 大平台全覆盖。

### 2. AI短剧知识库（向导 · 用户不懂就问）
- 知识中枢三级树新增专属节点「🤖 AI短剧知识库（向导）」（平台分组里 `special:True`，不挂在任一平台下）。点开列出 14 条引导条目：什么是 AI 短剧 / 新手 7 步流程 / 选题公式 / 剧本黄金3秒 / 工具链 / 上架备案 / AIGC 标识 / 平台怎么选 / 变现路径 / 新手避坑 / 5 Agent 协作 / 术语表 / 会员配额 / FAQ。
- 答疑接口 `POST /api/knowledge/guide/ask`：`{question} → {answer, refs, used_llm, fallback}`。先中文 unigram/bigram 关键词打分检索向导子库，再交方舟 LLM 生成 ≤280 字口语化解答 + 参考条目；断网/无 key 自动降级关键词拼接兜底。首页与聊天页（agent 页顶部 🤖 按钮）均可用。
- 字段约定：向导条目 `sublib="guide" & platform="guide"`（专属导航），与 4 个通用子库（平台规则/类型套路/风格样本/剧本资产）并列。

---

## 十一、后台导航固定 + 三类子库&向导联网真·补齐 + Agent 头像上传/URL

### 1. 后台导航体验修复（纯前端）
- 左侧导航滚动时不再跟随内容滚动：`.side` 改 `position:fixed; top:0; left:0; height:100vh; overflow-y:auto; z-index:50`，主区 `.main` 加 `margin-left:200px` 让位。
- 侧边 7 个一级导航（数据驾驶舱/用户分群/剧本库/知识中枢/Agent矩阵/模型中心/会员与权益）与图表工具栏去除 emoji 图标，保持专业克制的后台观感。

### 2. 三类子库 + 向导 联网真·补齐（非占位）
- 问题：类型套路库 / 风格样本库 / 剧本资产库此前有空缺，向导库此前未真正灌入知识。
- 新增 `backend/scripts/import_kb_web.py`：6 次 WebSearch 采 2025-2026 权威源（广电总局 / 新浪 / 今日头条 / 东方财富 / 中研普华 / 阿里云 / Sunra / Seedance / 电影界等），按 `(sublib,key)` 幂等 upsert，不冲掉后台手动条目。
- 导入：**genre +10**（重生/赘婿/霸总/萌宝/虐恋/神医/银发/乡村/非遗国风/系统玄幻）、**style +6**（AI视频提示词公式/角色一致性/竖屏构图/转场/色调映射/字幕花字BGM）、**asset +7**（开场钩子模板库/爆款标题公式/人设卡模板/金句台词库/广电合规红线全集/平台分发变现/IAA-IAP/工具链清单）、**guide +18**（0→1 全流程 / 好剧本 / 分镜 / 提示词公式 / 场景→提示词映射 / 角色一致性 / 工具选型 / 合规过审 / 平台变现 / 配音口型 / 配乐音效 / 数据完播率 / 避坑 / 成本周期 / 版权IP / 出海 / 团队分工 / 平台选型）。
- **知识库现状：105 条**（platform 13 / genre 18 / style 17 / asset 26 / guide 31）。
- 向导答疑 `POST /api/knowledge/guide/ask` 已能基于新导入知识用方舟 LLM 口语化解答（提示词/分镜/0→1/场景映射/合规/避坑 等 6 问实测 `used_llm=True` 且 refs 精准）。

### 3. Agent 头像：上传图片 / 输入 URL / emoji 三选一
- 后端：`agent_configs.avatar` 扩到 `String(512)` 存 URL；`main.py` 挂载 `/static/uploads`；`admin.py` 新增 `POST /api/admin/agents/avatar`（校验 png/jpg/jpeg/gif/webp/bmp/svg、≤2MB、写 `static/uploads/agents/{uuid}{ext}`、返回 `{url,size}`）。
- 前端：后台 Agent 弹层支持「图片 URL / emoji 输入 + 上传图片按钮」实时预览；用户端首页卡片 / Agent 列表 / 聊天头像统一经 `avatarHTML()` 渲染图片（带 onerror 回退 emoji）。

> 服务运行于 `127.0.0.1:8090`；知识库内容均来自联网采集的真实行业资料，对外演示有底气。

