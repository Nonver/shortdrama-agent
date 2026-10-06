"""联网核实后写入『用户端公开资料库』（visibility=public）：cases/monetize/compliance。

与后台 internal 库（platform/genre/style/asset/guide）完全隔离，绝不外泄内部机密。
幂等：按 (sublib, key) upsert；仅首次写入或同步内容/标签/来源。

运行：cd backend && ../.venv/Scripts/python.exe seed_public_kb.py
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.db import SessionLocal
from app.models import KnowledgeItem

COLLECTED_AT = "2026-08"

# ============================================================ 合规手册（compliance）
COMPLIANCE = [
    {"key": "aigc_biaoshi_banfa", "title": "《人工智能生成合成内容标识办法》2025-09-01 施行",
     "tags": ["AIGC", "合规", "标识", "国家网信办"],
     "content": "四部门（国家网信办、工信部、公安部、广电总局）联合发布，2025-09-01 起施行。\n"
                "要求 AI 生成的文本/图片/音频/视频/虚拟场景须『亮明身份』，分显式+隐式两类标识。\n"
                "配套强制性国标《网络安全技术 人工智能生成合成内容标识方法》同步实施。\n"
                "违反由网信、电信、公安、广电依职责处理。",
     "meta": {"source": "国家网信办 cac.gov.cn/2025-03/14/c_1743654685899683.htm；中国政府网 gov.cn", "collected_at": COLLECTED_AT}},

    {"key": "aigc_xianshi", "title": "显式标识：用户明显可感知的文字/声音/图形标识",
     "tags": ["AIGC", "显式标识", "合规"],
     "content": "显式标识指在内容或交互界面中以文字、声音、图形等呈现、用户明显可感知的标识。\n"
                "文本：起始/末尾/中间适当位置加文字或通用符号提示。\n"
                "图片：适当位置加显著提示标识。\n"
                "音频：起始/末尾/中间加语音或节奏提示。\n"
                "视频：起始画面+播放周边加显著提示，末尾/中间可补充。\n"
                "虚拟场景：起始画面加显著提示。下载/复制/导出时文件须含显式标识。",
     "meta": {"source": "《人工智能生成合成内容标识办法》第四条", "collected_at": COLLECTED_AT}},

    {"key": "aigc_yinshi", "title": "隐式标识：文件元数据 + 数字水印",
     "tags": ["AIGC", "隐式标识", "水印"],
     "content": "隐式标识指通过技术措施在文件数据中添加、用户不易感知的标识。\n"
                "须在文件元数据中写入：生成合成内容属性、服务提供者名称或编码、内容编号等。\n"
                "鼓励添加数字水印等形式隐式标识。\n"
                "传播平台核验到隐式标识的，须在发布内容周边加显著提示。",
     "meta": {"source": "《人工智能生成合成内容标识办法》第五条、第六条", "collected_at": COLLECTED_AT}},

    {"key": "aigc_wenzi_guanjianci", "title": "文字标识须含『人工智能/AI/生成/合成』关键词",
     "tags": ["AIGC", "文字", "合规"],
     "content": "专家明确：文字显式标识必须同时包含『人工智能』或『AI』『生成』或『合成』等关键词，字型清晰可见。\n"
                "即 AI 内容制作者/发布者的标识至少满足『显著易见』。",
     "meta": {"source": "央视网 news.cctv.com/2025/03/20 专家解读", "collected_at": COLLECTED_AT}},

    {"key": "aigc_shipin_biaoshi", "title": "视频标识位置：起始画面 + 播放周边",
     "tags": ["AIGC", "视频", "合规"],
     "content": "视频类生成合成内容：起始画面与播放周边适当位置加显著提示标识，可在末尾/中间补充。\n"
                "本平台生视频默认在片头叠加『AI 生成』显式标识并写入元数据，符合办法要求。",
     "meta": {"source": "《人工智能生成合成内容标识办法》第四条（四）", "collected_at": COLLECTED_AT}},

    {"key": "aigc_fabu_shengming", "title": "用户发布 AIGC 须主动声明并标识",
     "tags": ["AIGC", "发布", "合规"],
     "content": "用户用网络传播服务发布生成合成内容的，应主动声明并使用服务提供者的标识功能进行标识。\n"
                "平台须提供必要标识功能并提醒用户声明。",
     "meta": {"source": "《人工智能生成合成内容标识办法》第六条、第十条", "collected_at": COLLECTED_AT}},

    {"key": "aigc_jinzhi", "title": "禁止恶意删除/篡改/伪造/隐匿标识",
     "tags": ["AIGC", "红线", "合规"],
     "content": "任何组织和个人不得恶意删除、篡改、伪造、隐匿生成合成内容标识；\n"
                "不得为他人实施上述行为提供工具或服务；不得通过不正当标识手段损害他人合法权益。",
     "meta": {"source": "《人工智能生成合成内容标识办法》第十条", "collected_at": COLLECTED_AT}},

    {"key": "weiduanju_fenlei_shenhe", "title": "微短剧分类分层审核（重点/普通/其他）",
     "tags": ["微短剧", "审核", "备案", "广电"],
     "content": "广电总局 2025-02 通知：按三类分三个层级审核管理。\n"
                "重点微短剧、普通微短剧报省级以上广电主管部门规划备案+成片审查；\n"
                "其他微短剧由播出/引流平台自审把关+版权核定，定期报属地省级广电备案。",
     "meta": {"source": "国家广电总局《关于进一步统筹发展和安全促进网络微短剧行业健康繁荣发展的通知》", "collected_at": COLLECTED_AT}},

    {"key": "weiduanju_xuke", "title": "所有微短剧须持证或完成上线报备",
     "tags": ["微短剧", "许可证", "备案"],
     "content": "网络视听平台、小程序、投流方播出或引流推送的所有微短剧，均须持有《网络剧片发行许可证》\n"
                "或完成相应上线报备登记程序。平台不得上线未标注许可证/备案号的剧，也不得引流推送。",
     "meta": {"source": "国家广电总局通知；新华网 news.cn/20250205", "collected_at": COLLECTED_AT}},

    {"key": "weiduanju_pianTou", "title": "片头须标注许可证号 / 备案号",
     "tags": ["微短剧", "片头", "备案号"],
     "content": "节目上线前须在片头按相应格式标注《网络剧片发行许可证》号或节目登记备案号。\n"
                "未标注的不得上线传播。",
     "meta": {"source": "国家广电总局通知；人民网", "collected_at": COLLECTED_AT}},

    {"key": "weiduanju_zhongdian", "title": "重点微短剧：总局统一备案公示",
     "tags": ["重点微短剧", "备案", "广电"],
     "content": "符合特殊题材、总投资≥100万元、长短视频平台主推/首页首屏推荐、或自愿按重点申报之一者，属重点微短剧。\n"
                "规划备案由国家广电总局统一备案公示管理；拟首页首屏推荐的由总局对完成片复核。",
     "meta": {"source": "国家广电总局通知", "collected_at": COLLECTED_AT}},

    {"key": "weiduanju_putong", "title": "普通微短剧：30-100万，省局审查",
     "tags": ["普通微短剧", "审查"],
     "content": "总投资额度在 30万元（含）—100万元之间且非重点推荐的，属普通微短剧，\n"
                "报省级以上广电主管部门规划备案和成片审查。",
     "meta": {"source": "国家广电总局通知", "collected_at": COLLECTED_AT}},

    {"key": "weiduanju_qita", "title": "其他微短剧：<30万，平台自审+报属地备案",
     "tags": ["其他微短剧", "自审", "平台"],
     "content": "总投资不足30万元且非重点推荐的，由播出或为其引流的平台履行内容管理职责，\n"
                "负责内容审核把关与版权核定，定期将审核剧目信息报属地省级广电主管部门备案。",
     "meta": {"source": "国家广电总局通知", "collected_at": COLLECTED_AT}},

    {"key": "banquan_zhenren", "title": "版权红线：勿用影视剧片段 / 真人肖像声音",
     "tags": ["版权", "肖像", "侵权"],
     "content": "不得搬运影视剧片段；勿使用真人肖像、声音（侵权赔偿可达数万~数十万元）。\n"
                "本平台生图/生视频默认平台授权，用于合规创作；商用须自行确保素材权属清晰。",
     "meta": {"source": "平台版权提示 + 公开侵权判例", "collected_at": COLLECTED_AT}},

    {"key": "weichengnian", "title": "未成年人保护：不得诱导消费、不良内容",
     "tags": ["未成年人", "合规", "红线"],
     "content": "不得诱导未成年人消费；不得含有危害未成年人身心健康的内容。\n"
                "涉及校园、低龄向题材须格外审慎，避免不良示范。",
     "meta": {"source": "《未成年人保护法》及平台审核规则", "collected_at": COLLECTED_AT}},

    {"key": "neirong_hongxian", "title": "内容红线：色情低俗 / 暴力 / 炫富拜金",
     "tags": ["内容红线", "低俗", "暴力"],
     "content": "色情低俗、以暴制暴、炫富拜金等被重点整治。\n"
                "先审后播新规落地后，相关低俗擦边内容显著减少。创作须价值观正向。",
     "meta": {"source": "广电总局通知；红果/抖音平台反馈", "collected_at": COLLECTED_AT}},

    {"key": "lowsu_cabian", "title": "低俗擦边、以暴制暴被重点整治",
     "tags": ["低俗", "擦边", "整治"],
     "content": "『先审后播』备案新规后，制作方在剧本/拍摄阶段即强化合规意识，\n"
                "低俗擦边、以暴制暴、炫富拜金内容显著减少，现实题材增多。",
     "meta": {"source": "新华网 2025-02-10 广电总局网络视听司解读", "collected_at": COLLECTED_AT}},

    {"key": "pingtai_xianhenghou", "title": "平台先审后播 + 白名单制度",
     "tags": ["先审后播", "白名单"],
     "content": "落实『分类分层审核』与『白名单』制度，规范微短剧传播秩序，确保播出安全。\n"
                "全部微短剧实现『持证上岗』。",
     "meta": {"source": "新华网 news.cn/20250210", "collected_at": COLLECTED_AT}},

    {"key": "chukou_baobei", "title": "出海也须符合国内备案 + 当地法规",
     "tags": ["出海", "备案", "合规"],
     "content": "国内上线须备案；出海须同时符合目标市场（如美国、东南亚）的内容与广告法规。\n"
                "海外获客成本高，须评估 ROI 再投。",
     "meta": {"source": "DataEye 出海报告；中航证券", "collected_at": COLLECTED_AT}},

    {"key": "shuzi_shuiyin", "title": "鼓励数字水印作为隐式标识",
     "tags": ["数字水印", "隐式标识"],
     "content": "《标识办法》鼓励在生成合成内容中添加数字水印等形式的隐式标识，\n"
                "便于溯源与维权。",
     "meta": {"source": "《人工智能生成合成内容标识办法》第五条", "collected_at": COLLECTED_AT}},

    {"key": "yingyong_shangdian", "title": "应用分发平台须核验标识材料",
     "tags": ["应用商店", "核验"],
     "content": "互联网应用程序分发平台上架/上线审核时，须要求说明是否提供 AI 生成合成服务；\n"
                "提供的须核验其标识相关材料。",
     "meta": {"source": "《人工智能生成合成内容标识办法》第七条", "collected_at": COLLECTED_AT}},

    {"key": "xieyi_biaoshi", "title": "用户协议须说明标识规范",
     "tags": ["用户协议", "标识"],
     "content": "服务提供者应在用户服务协议中明确说明生成合成内容标识的方法、样式等，\n"
                "提示用户理解标识管理要求。",
     "meta": {"source": "《人工智能生成合成内容标识办法》第八条", "collected_at": COLLECTED_AT}},

    {"key": "aigc_liucheng", "title": "全流程标识：生成 → 传播各环节",
     "tags": ["全流程", "标识", "溯源"],
     "content": "办法推动由生成到传播各环节全流程安全管理，解决『哪些是生成的/谁生成的/从哪生成的』。\n"
                "传播平台须在元数据加传播要素信息（平台名称/编码、内容编号）。",
     "meta": {"source": "人民网财经频道解读", "collected_at": COLLECTED_AT}},

    {"key": "fanweiquan", "title": "仿冒媒体/政府/他人声音须显式标识",
     "tags": ["仿冒", "显式标识", "红线"],
     "content": "借助 AI 模仿他人话语表达、模仿媒体新闻发布、模仿政府部门公告等，必须进行显式标识。\n"
                "普通个人文字创作若不侵权通常不需专门标识。",
     "meta": {"source": "央视网专家解读", "collected_at": COLLECTED_AT}},

    {"key": "shuju_cunzheng", "title": "提供无标识内容须留存日志≥6个月",
     "tags": ["日志", "留存"],
     "content": "用户申请提供无显式标识的生成合成内容，服务提供者可在用户协议明确标识义务与责任后提供，\n"
                "并依法留存提供对象信息等相关日志不少于六个月。",
     "meta": {"source": "《人工智能生成合成内容标识办法》第九条", "collected_at": COLLECTED_AT}},

    {"key": "guangdian_2025", "title": "2025 广电重点：完善微短剧治理",
     "tags": ["广电", "2025", "治理"],
     "content": "2025 全国广播电视和网络视听 10 项重点工作中，『全面提升网络视听领域治理能力，\n"
                "完善节目类视听内容管理』居重要位置；适時以部门规章出台《微短剧管理办法》。",
     "meta": {"source": "中国新闻出版广电报 2025-03-24", "collected_at": COLLECTED_AT}},

    {"key": "weiduanju_guanli_banfa", "title": "《微短剧管理办法》拟以部门规章出台",
     "tags": ["微短剧管理办法", "部门规章"],
     "content": "广电总局表示将在分级分类审核基础上深入调研，适时以部门规章形式出台《微短剧管理办法》，\n"
                "推动行业精品化、规范化。关注后续正式文本。",
     "meta": {"source": "新华网 2025-02-10 广电总局网络视听司", "collected_at": COLLECTED_AT}},
]

# ============================================================ 变现地图（monetize）
MONETIZE = [
    {"key": "iap_mode", "title": "IAP 内购付费：单集/整部解锁",
     "tags": ["IAP", "付费", "变现"],
     "content": "应用内购买：用户单集付费或整部解锁，平台抽成。回款快、现金流好，\n"
                "但对前几集钩子与转化能力要求极高。长视频会员微短剧亦属此列。",
     "meta": {"source": "网易《中国微短剧产业链地图》2025", "collected_at": COLLECTED_AT}},

    {"key": "iaa_mode", "title": "IAA 广告免费：红果模式代表",
     "tags": ["IAA", "免费", "广告", "红果"],
     "content": "应用内广告：免费看剧，靠前贴片/激励视频/中插广告变现，按播放与时长与制作方分账。\n"
                "红果短剧以此形成『用户增长—广告收入—内容预算』正循环；2025 国内 IAA 占比约 71%。",
     "meta": {"source": "网易产业链报告；中航证券 2026-08", "collected_at": COLLECTED_AT}},

    {"key": "iaap_hunhe", "title": "混合变现 IAAP",
     "tags": ["混合", "IAAP", "变现"],
     "content": "广告+付费结合。免费用户看广告，付费用户去广告/抢先看。\n"
                "抖音等平台分成可达 90-95%，兼顾规模与 ARPU。",
     "meta": {"source": "搜狐 AI短剧分润解析 2025", "collected_at": COLLECTED_AT}},

    {"key": "pingtai_fenchang", "title": "平台分账：按播放/时长/互动分成",
     "tags": ["分账", "平台", "变现"],
     "content": "平台将剧集广告收入综合播放量、用户互动等数据，按比例与创作方分账。\n"
                "红果基于生态内流量优势无需高价外部投流，分账更直接惠及制作方。",
     "meta": {"source": "海克财经《红果吃透微短剧》", "collected_at": COLLECTED_AT}},

    {"key": "hongguo_fenchang", "title": "红果分账：月释放 5亿+，爆款单月超百万",
     "tags": ["红果", "分账", "案例"],
     "content": "红果每月稳定向内容端释放 5亿元以上预算；2025-03 分账金额超 5亿元。\n"
                "《家里家外》《乡下真千金竟是老祖宗》等爆款当月均获超 100万元分账。",
     "meta": {"source": "海克财经；红果官方数据", "collected_at": COLLECTED_AT}},

    {"key": "juben_fenchang", "title": "红果剧本分账：8/9/10 月 5000/6600/7300 万",
     "tags": ["红果", "剧本分账"],
     "content": "红果将分账延伸至产业链前端：2025 年 8/9/10 月剧本分账分别突破 5000万/6600万/7300万元。\n"
                "演员分账机制下，爆款主演单部可获 100-150万元+分账。",
     "meta": {"source": "红果官方；海克财经", "collected_at": COLLECTED_AT}},

    {"key": "yanyuan_fenchang", "title": "编剧/演员分账延伸（类好莱坞版税）",
     "tags": ["编剧", "演员", "分账"],
     "content": "红果面向编剧、演员、制作方提供从 IP 选取、剧本、演员合作到结算的全流程服务；\n"
                "创作者凭代表作从后续播放/发行持续分成，激励长期投入精品。",
     "meta": {"source": "海克财经《红果吃透微短剧》", "collected_at": COLLECTED_AT}},

    {"key": "douyin_chenxing", "title": "抖音辰星/星光计划：净收益最高 90% 归版权方",
     "tags": ["抖音", "扶持", "分成"],
     "content": "抖音『辰星计划』『星光计划』：全渠道免付费净收益 90% 归版权方，\n"
                "部分 IP 改编项目叠加 50% 额外扶持。",
     "meta": {"source": "搜狐 AI短剧分润解析", "collected_at": COLLECTED_AT}},

    {"key": "kuaishou_xingmang", "title": "快手星芒创想：联合运营最高分账 90%",
     "tags": ["快手", "扶持", "分账"],
     "content": "快手『星芒创想计划』提供资金与流量支持，联合运营模式最高分账 90%。\n"
                "并对漫剧拿出最大力度扶持（现金+流量激励）。",
     "meta": {"source": "搜狐 AI短剧分润解析；快手商业沙龙", "collected_at": COLLECTED_AT}},

    {"key": "bili_aijue", "title": "B站觉醒计划：覆盖 30%-100% 制作成本",
     "tags": ["B站", "扶持", "分成"],
     "content": "B站『觉醒计划』覆盖 30%-100% 制作成本，分成比例最高达 80%。\n"
                "适合口碑/二次元向内容。",
     "meta": {"source": "搜狐 AI短剧分润解析", "collected_at": COLLECTED_AT}},

    {"key": "iqiyi_jili", "title": "爱奇艺会员激励：独家新片分成可达 100%",
     "tags": ["爱奇艺", "会员", "分成"],
     "content": "爱奇艺独家新片会员激励分成比例可达 100%，优质团队享『保底+分成』双重保障。\n"
                "适合横屏精品微短剧。",
     "meta": {"source": "搜狐 AI短剧分润解析", "collected_at": COLLECTED_AT}},

    {"key": "pinpai_dingzhi", "title": "品牌定制 / 内容植入（剧情带货）",
     "tags": ["品牌", "定制", "植入"],
     "content": "品牌方出资定制剧情并植入产品。案例《夫妻的春节》（抖音『她的世界』）16 集，\n"
                "播放超 5.8亿次，为丸美等品牌实现春节剧情带货爆发。",
     "meta": {"source": "网易产业链报告", "collected_at": COLLECTED_AT}},

    {"key": "duanhuj_dianshang", "title": "短剧 + 电商：剧情带货闭环",
     "tags": ["电商", "带货", "变现"],
     "content": "在剧情中自然植入商品，结尾/购物车转化。适合服饰、食品、日用等品类。\n"
                "与品牌定制结合效果最佳，须标注广告/合作属性避免违规。",
     "meta": {"source": "网易产业链报告；公开案例", "collected_at": COLLECTED_AT}},

    {"key": "ip_yansheng", "title": "IP 衍生：续作系列化拉长 LTV",
     "tags": ["IP", "衍生", "系列化"],
     "content": "爆款做续作/番外（如《云渺》系列、《十八岁太奶奶》系列）拉长用户生命周期价值。\n"
                "网文 IP 改编确定性高，降低选品风险。",
     "meta": {"source": "海克财经；云合数据", "collected_at": COLLECTED_AT}},

    {"key": "huiyuan_dingyue", "title": "会员订阅：免广告 / 抢先看",
     "tags": ["会员", "订阅"],
     "content": "平台会员制（如红果/番茄联合会员）免广告、抢先看，构成稳定订阅收入。\n"
                "与 IAA 互补，提升 ARPU。",
     "meta": {"source": "海克财经《红果吃透微短剧》", "collected_at": COLLECTED_AT}},

    {"key": "sichu_daoliu", "title": "私域导流：引流至微信/社群",
     "tags": ["私域", "导流"],
     "content": "以短剧内容吸粉，导流至私域（微信/社群/小程序）做复购或课程等转化。\n"
                "须遵守平台外链与诱导分享规则。",
     "meta": {"source": "行业通用打法", "collected_at": COLLECTED_AT}},

    {"key": "chuhai_neigou", "title": "短剧出海内购：2025 海外 22.79 亿美元（+129%）",
     "tags": ["出海", "内购", "IAP"],
     "content": "2025 海外微短剧双端内购收入约 22.79亿美元，同比 +129%；下载 18.55亿次，+300%。\n"
                "中国出海厂商贡献约 95% 收入。新兴市场（印度/印尼/巴西）成下载主力。",
     "meta": {"source": "DataEye 研究院；中航证券 2026-08", "collected_at": COLLECTED_AT}},

    {"key": "chuhai_huoce", "title": "出海获客成本高：北美 5.28-15 美元/用户",
     "tags": ["出海", "获客成本", "ROI"],
     "content": "海外投流成本是核心症结：北美单用户获客成本 5.28-15 美元，部分为制作费十倍以上。\n"
                "80%-90% 出海项目难回本，须重内容供给与本地化运营。",
     "meta": {"source": "中航证券 2026-08", "collected_at": COLLECTED_AT}},

    {"key": "ai_jiangben", "title": "AI 降本：成本 1/5-1/10，单集约 15 万",
     "tags": ["AI", "降本", "效率"],
     "content": "AI 将制作成本降至传统真人剧 1/5-1/10，单集成本约 15万，周期从 3 个月压缩至 2 周。\n"
                "中文在线自研工具链将 11 环节压至 5 步，成本降 60%。漫剧单部 10-30万、周期 10-13天。",
     "meta": {"source": "搜狐 AI短剧分润；中航证券", "collected_at": COLLECTED_AT}},

    {"key": "touliu_fenhong", "title": "投流分账：制作方利润受买量挤压",
     "tags": ["投流", "买量", "分账"],
     "content": "IAP 模式制作方分账较高；IAA 模式下平台掌握流量分发，制作方广告分账远低于付费分账。\n"
                "2025 投流规模约 423亿，AI 短剧投流成本约占总流水 70%，腰部盈利比例仅 3-5%。",
     "meta": {"source": "中航证券 2026-08；DataEye", "collected_at": COLLECTED_AT}},

    {"key": "baobei_tuichao", "title": "平台补贴退潮，精品化导向",
     "tags": ["补贴", "精品化", "趋势"],
     "content": "红果 2026-05 仅对部分剧本保留保底，持续低质治理；平台资源向精品倾斜。\n"
                "依赖补贴与低成本批量的团队面临出清，优质 IP/稳定产出能力更重要。",
     "meta": {"source": "中航证券 2026-08", "collected_at": COLLECTED_AT}},

    {"key": "xianliang_baohdi", "title": "保底 + 分成双保障",
     "tags": ["保底", "分成"],
     "content": "头部平台对优质团队提供『保底+分成』：先给保底降低风险，上线后按表现分成。\n"
                "适合有稳定爆款率的厂牌。",
     "meta": {"source": "搜狐 AI短剧分润；爱奇艺政策", "collected_at": COLLECTED_AT}},

    {"key": "shichang_guimo", "title": "市场规模：2025 约 634 亿（+26%），2027 料 856 亿",
     "tags": ["市场", "规模", "数据"],
     "content": "2025 中国微短剧核心市场规模约 634.3亿元，同比 +26%；预计 2027 增至 856.5亿元（CAGR 19.2%）。\n"
                "月活用户 2026-02 达 7.18亿，红果 3.04亿 MAU 领先。",
     "meta": {"source": "中航证券 2026-08；DataEye；QuestMobile", "collected_at": COLLECTED_AT}},

    {"key": "mianfei_zhanybi", "title": "免费模式主导：IAA 占比约 71%",
     "tags": ["免费", "IAA", "占比"],
     "content": "2025 商业模式：IAA（广告）市场占比约 71%，IAP（内购）降至 26%，混合仅 3%。\n"
                "免费看剧已成主导，重塑盈利模型为『广告+内容预算分账』。",
     "meta": {"source": "中航证券 2026-08；行业白皮书", "collected_at": COLLECTED_AT}},
]

# ============================================================ 爆款拆解（cases）
CASES = [
    {"key": "case_taigrandma", "title": "《十八岁太奶奶驾到》2025 年度第一 44.44 亿播放",
     "tags": ["爆款", "红果", "系列化", "反差"],
     "content": "2025-06 上线，全年全网播放 44.44亿（云合数据年度第一）；第二部 34.28亿（年度第六）。\n"
                "拆解：年龄反差+家族荣耀爽点，系列化连载（第三/四部预约超 587万）。",
     "meta": {"source": "云合数据 2025 年度榜；海克财经", "collected_at": COLLECTED_AT}},

    {"key": "case_yunmiao", "title": "《云渺》修仙单元案，番茄 IP 改编剧王",
     "tags": ["爆款", "修仙", "单元", "IP"],
     "content": "原著《我，修仙大佬强亿点怎么了》番茄小说连载；微短剧按前 100 章试水，单元案件推进。\n"
                "热度走高即推续作，形成《云渺》系列，反馈驱动创作。",
     "meta": {"source": "海克财经；番茄小说", "collected_at": COLLECTED_AT}},

    {"key": "case_jialijiawai", "title": "《家里家外》川渝方言 28.42 亿（听花岛）",
     "tags": ["爆款", "方言", "现实", "听花岛"],
     "content": "2025-03 多平台上线，年度第七 28.42亿。川渝方言+现实家庭议题，情绪真实。\n"
                "听花岛厂牌：70部中48部破10亿，爆款率 69%。",
     "meta": {"source": "云合数据；海克财经", "collected_at": COLLECTED_AT}},

    {"key": "case_huozong", "title": "《霍总，夫人马甲又掉了》霸总 10.98 亿",
     "tags": ["爆款", "霸总", "番茄IP"],
     "content": "红果 2025-11 月榜第一 10.98亿。原著《千金归来，她才是豪门真大佬》番茄 8.5分。\n"
                "拆解：马甲/掉马反差+豪门爽点，IP 已验证。",
     "meta": {"source": "云合数据；番茄小说", "collected_at": COLLECTED_AT}},

    {"key": "case_beidai", "title": "《东北年代之我的大腰子》8.61 亿",
     "tags": ["爆款", "年代", "东北"],
     "content": "红果月榜第三 8.61亿。年代怀旧+地域喜剧，下沉市场强共鸣。",
     "meta": {"source": "云合数据 2025-11", "collected_at": COLLECTED_AT}},

    {"key": "case_banshu", "title": "《半熟老公》8.21 亿（演员分账破百万）",
     "tags": ["爆款", "都市", "情感"],
     "content": "红果月榜第四 8.21亿。都市情感+生活化表达；主演凭此获 100万+ 分账。",
     "meta": {"source": "云合数据；红果分账机制", "collected_at": COLLECTED_AT}},

    {"key": "case_houfu", "title": "《侯府主母要寿终正寝》7.08 亿",
     "tags": ["爆款", "古装", "女频"],
     "content": "红果月榜第七 7.08亿。古装女频+宅斗爽点，番茄 IP 改编。",
     "meta": {"source": "云合数据 2025-11", "collected_at": COLLECTED_AT}},

    {"key": "case_niangniang", "title": "《哎呀皇后娘娘来打工》AI 短剧爆款",
     "tags": ["爆款", "AI", "古装"],
     "content": "AI 短剧分润代表案例，古装+反差设定跑通分润模型。\n"
                "说明 AI 原生制作亦可出圈，关键仍在选题与钩子。",
     "meta": {"source": "搜狐 AI短剧分润解析", "collected_at": COLLECTED_AT}},

    {"key": "case_80houma", "title": "《我在80后妈当》穿越年代强钩子",
     "tags": ["爆款", "穿越", "年代", "钩子"],
     "content": "现代女主睁眼穿越成 80 年代后妈，身份反差瞬间锁定；前 3 秒即抛强钩子。\n"
                "可作为钩子密度范本。",
     "meta": {"source": "平台示例（公开可查标题）", "collected_at": COLLECTED_AT}},

    {"key": "case_gongtongdian", "title": "爆款共性①：前 3 秒强钩子",
     "tags": ["方法论", "钩子", "3秒"],
     "content": "开场 3 秒须抛出冲突/悬念/反差，锁住划走的用户。\n"
                "例：被当众羞辱、身份错位、生死危机。钩子决定完播与转化。",
     "meta": {"source": "爆款结构方法论", "collected_at": COLLECTED_AT}},

    {"key": "case_fancha", "title": "爆款共性②：身份 / 处境反差",
     "tags": ["方法论", "反差"],
     "content": "最强爽点来自反差：废柴→大佬、底层→豪门、现代→古代、晚辈→长辈。\n"
                "反差越大，情绪释放越爽。",
     "meta": {"source": "爆款结构方法论", "collected_at": COLLECTED_AT}},

    {"key": "case_danyuan", "title": "爆款共性③：单元推进（案/任务）",
     "tags": ["方法论", "单元", "结构"],
     "content": "以独立单元（案件/任务/关卡）推进，单集闭环又有主线钩子，\n"
                "降低观看门槛、利于算法分发与续看。",
     "meta": {"source": "爆款结构方法论", "collected_at": COLLECTED_AT}},

    {"key": "case_ip_gaibian", "title": "爆款共性④：网文 IP 改编确定性高",
     "tags": ["方法论", "IP", "改编"],
     "content": "番茄/阅文等高分网文已验证爽感套路与读者基础，大幅降低选品风险。\n"
                "红果头部剧多来自番茄 IP（如《霍总》《半熟老公》）。",
     "meta": {"source": "海克财经；云合数据", "collected_at": COLLECTED_AT}},

    {"key": "case_xulie", "title": "爆款共性⑤：续作系列化拉长 LTV",
     "tags": ["方法论", "系列化", "LTV"],
     "content": "爆款即做续作/番外（《云渺》《十八岁太奶奶》系列），复用 IP 与粉丝，\n"
                "拉长用户生命周期价值，提升分账总额。",
     "meta": {"source": "海克财经；云合数据", "collected_at": COLLECTED_AT}},

    {"key": "case_yuyan", "title": "爆款共性⑥：情绪价值（爽/泪/甜）",
     "tags": ["方法论", "情绪", "爽点"],
     "content": "每 10-15 秒一个小冲突、每 30 秒一个反转，持续供给爽/泪/甜。\n"
                "情绪密度决定分享与追更。",
     "meta": {"source": "爆款结构方法论", "collected_at": COLLECTED_AT}},

    {"key": "case_gouzi_midu", "title": "钩子密度：10-15 秒小冲突，30 秒反转",
     "tags": ["方法论", "钩子密度", "节奏"],
     "content": "单集节奏：开头钩子→中段冲突升级→结尾悬念。\n"
                "密集爽点对抗划走，是免费模式留存关键。",
     "meta": {"source": "爆款结构方法论；平台审核反馈", "collected_at": COLLECTED_AT}},

    {"key": "case_pingtai_xuan", "title": "平台选择：红果免费/IAA，抖音投流",
     "tags": ["方法论", "平台", "选型"],
     "content": "红果走免费+IAA 分账、用户规模大；抖音适合投流+IAP 引爆；快手漫剧扶持强。\n"
                "按内容调性与变现目标选首发平台。",
     "meta": {"source": "中航证券；平台公开策略", "collected_at": COLLECTED_AT}},

    {"key": "case_renqun", "title": "人群差异：下沉 / 银发 / 女性向",
     "tags": ["方法论", "人群", "用户"],
     "content": "下沉与银发用户爱年代/家庭；女性向爱霸总/甜宠/宅斗；男频爱玄幻/逆袭。\n"
                "人群决定题材与台词风格。",
     "meta": {"source": "平台用户画像；行业洞察", "collected_at": COLLECTED_AT}},

    {"key": "case_shichang", "title": "爆款率不足 0.1%，精品化是出路",
     "tags": ["方法论", "爆款率", "数据"],
     "content": "DataEye：2025 超 16万部新剧，热力值超 5000万爆款仅 12部，26H1 爆款率不足 0.1%。\n"
                "头部厂牌爆款率远高于均值，精品内容稀缺性在积累反制力量。",
     "meta": {"source": "DataEye；中航证券 2026-08", "collected_at": COLLECTED_AT}},

    {"key": "case_tinghua", "title": "听花岛：爆款率 69% 的厂牌样本",
     "tags": ["案例", "听花岛", "厂牌"],
     "content": "听花岛 70部中 48部破 10亿（爆款率 69%），代表稳定优质产出能力。\n"
                "说明行业议价权向精品制作方倾斜。",
     "meta": {"source": "中航证券 2026-08", "collected_at": COLLECTED_AT}},

    {"key": "case_xiaoshuo_fankui", "title": "小说评论驱动拍摄优化",
     "tags": ["方法论", "反馈", "IP"],
     "content": "原著读者评论可优化拍摄；未完结小说作者据剧集反馈动态调整后续剧情。\n"
                "形成 IP↔剧集反馈闭环。",
     "meta": {"source": "海克财经《红果吃透微短剧》", "collected_at": COLLECTED_AT}},

    {"key": "case_duanhou_ceshui", "title": "先改前 100 章试水",
     "tags": ["方法论", "试水", "IP"],
     "content": "长篇 IP 先取前段章节试水改编，视市场反馈再决定续改，降低试错成本。",
     "meta": {"source": "海克财经《云渺》案例", "collected_at": COLLECTED_AT}},

    {"key": "case_pinpai_anli", "title": "《夫妻的春节》品牌剧情带货 5.8 亿播放",
     "tags": ["案例", "品牌", "带货"],
     "content": "抖音『她的世界』16集，春节节点完成『预热—爆发—长尾』，为丸美剧情带货爆发。\n"
                "项目制+投放驱动，数据好即加投衍生。",
     "meta": {"source": "网易产业链报告", "collected_at": COLLECTED_AT}},

    {"key": "case_chuhai_anli", "title": "出海路径：ReelShort / DramaBox",
     "tags": ["案例", "出海", "APP"],
     "content": "独立 APP 为主：ReelShort 本土原创、DramaBox 翻译改编、FreeReels 免费获客。\n"
                "竞争在内容供给、流量获取、算法分发与运营能力。",
     "meta": {"source": "中航证券 2026-08", "collected_at": COLLECTED_AT}},

    {"key": "case_ai_manju", "title": "AI 漫剧：单部 10-30 万，周期 10-13 天",
     "tags": ["案例", "AI", "漫剧"],
     "content": "AI 全流程制作单分钟成本约 400元，单部 10-30万，周期 10-13天，去真人化。\n"
                "2025 漫剧市场破 200亿，红果/腾讯/百度等入局。",
     "meta": {"source": "中航证券 2026-08", "collected_at": COLLECTED_AT}},

    {"key": "case_ai_fangzhenren", "title": "AI 仿真人剧占比升至 60%+",
     "tags": ["趋势", "AI", "仿真人"],
     "content": "AI 仿真人剧在漫剧百强榜占比从 2025 初 7% 升至 2026-03 的 60%+，完成品类替代。\n"
                "26Q1 AI剧/漫剧合计播放近 1300亿次。",
     "meta": {"source": "DataEye 研究院；中航证券 2026-08", "collected_at": COLLECTED_AT}},

    {"key": "case_xuanju", "title": "选题：价值观正向更易过审+推流",
     "tags": ["方法论", "选题", "过审"],
     "content": "正向价值观（励志/亲情/逆袭）过审快、易获平台推流；\n"
                "低俗擦边/以暴制暴被限。选题即合规起点。",
     "meta": {"source": "广电总局通知；平台审核反馈", "collected_at": COLLECTED_AT}},

    {"key": "case_biaoti", "title": "片名：避免哗众取宠 / 低俗庸俗",
     "tags": ["方法论", "片名", "合规"],
     "content": "通知点名『片名哗众取宠、低俗庸俗』问题。片名须抓眼球但不踩线，\n"
                "清晰传递类型与爽点。",
     "meta": {"source": "新华网 2025-02-10 广电总局", "collected_at": COLLECTED_AT}},

    {"key": "case_jiagou", "title": "单集结构：钩子-冲突-反转-悬念",
     "tags": ["方法论", "结构", "单集"],
     "content": "单集标准结构：开场 3 秒钩子→中段冲突升级→临近结尾反转→收尾留悬念引下集。\n"
                "每集自闭环又串主线。",
     "meta": {"source": "爆款结构方法论", "collected_at": COLLECTED_AT}},

    {"key": "case_changjing", "title": "场景：少场景 / 强表情 / 高信息密度",
     "tags": ["方法论", "场景", "制作"],
     "content": "控制场景数量降成本；用强表情与近景传递情绪；对话信息密度高，少废镜头。\n"
                "适配竖屏与碎片化观看。",
     "meta": {"source": "爆款制作方法论", "collected_at": COLLECTED_AT}},
]


def all_items():
    out = []
    plan = [("compliance", COMPLIANCE), ("monetize", MONETIZE), ("cases", CASES)]
    for sublib, items in plan:
        for i, it in enumerate(items):
            d = dict(it)
            d["sublib"] = sublib
            d["platform"] = "general"
            d["visibility"] = "public"
            d["sort_order"] = i
            out.append(d)
    return out


def main():
    db = SessionLocal()
    try:
        synced = 0
        for it in all_items():
            s, k = it["sublib"], it["key"]
            row = db.query(KnowledgeItem).filter(
                KnowledgeItem.sublib == s, KnowledgeItem.key == k).first()
            if not row:
                db.add(KnowledgeItem(**it))
                synced += 1
            else:
                row.title = it["title"]
                row.content = it["content"]
                row.tags = it["tags"]
                row.meta = it["meta"]
                row.visibility = "public"
                row.platform = "general"
                row.sort_order = it["sort_order"]
                synced += 1
        db.commit()
        print(f"[public-kb] 已同步 {synced} 条公开资料库条目（compliance/monetize/cases 三类）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
