"""配置项中文说明表（CFG_META_1105）。

面板原来直接把 config.json 的键名摊出来（llm_model / proactive_probability…），
没人看得懂。这里给每一项配：分组 / 中文名 / 一句话说明，内部状态键直接隐藏。
"""

# 分组顺序（面板按这个顺序排）
GROUPS = [
    ("conn", "连接与账号"),
    ("model", "模型与密钥"),
    ("persona", "人设"),
    ("talk", "说话方式"),
    ("proactive", "主动说话"),
    ("voice", "语音"),
    ("qzone", "QQ 空间"),
    ("memory", "记忆"),
    ("perm", "权限与黑名单"),
    ("sleep", "作息"),
    ("feat", "功能开关"),
    ("misc", "其他设置"),
    ("raw", "未归类的设置"),
]

# 键 -> (分组, 中文名, 说明)
META = {
    # ---- 连接 ----
    "ws_url": ("conn", "协议端地址", "QQ 协议端（SnowLuma）的 WebSocket 地址，换成别的协议端才需要改"),
    "self_qq": ("conn", "机器人 QQ", "机器人登录用的那个号（小号）"),
    "master_qq": ("conn", "主人 QQ", "只有这个号被当主人，撒娇和特权都对他"),
    "self_name": ("conn", "对外昵称", "她在群里显示的名字"),
    "panel_port": ("conn", "面板端口", "管理面板监听的端口，重装后才生效"),
    "ws_port": ("conn", "协议端监听端口", "机器人等协议端连进来的端口，跟协议端那边填的要一致"),
    "update_url": ("conn", "更新检查地址", "查新版本用的地址，留空就不查"),
    "market_repo": ("conn", "插件市场索引", "user/repo、http(s) 直链或本地 index.json 文件名"),
    "market_branch": ("conn", "插件市场分支", "索引在哪个分支上，一般 main"),
    "market_mirror": ("conn", "插件市场镜像", "GitHub 打不开时用的镜像前缀"),

    # ---- 模型 ----
    "llm_key": ("model", "DeepSeek 密钥", "用来思考说话的 API key，sk- 开头"),
    "llm_base": ("model", "接口地址", "DeepSeek 的接口地址，一般不用动"),
    "llm_model": ("model", "主模型", "主力模型名，比如 deepseek-flash / deepseek-chat"),
    "llm_model_fallback": ("model", "备用模型", "主模型报错时自动切的备用模型"),
    "chat_max_tokens": ("model", "回复长度上限", "一次回复最多多少 token，越大越能展开，也越费钱"),
    "chat_max_tokens_noadmin": ("model", "群友的回复上限", "非管理员触发时用的 token 上限，比主人那档小"),
    "vision_model": ("model", "看图模型", "识图用的模型名"),

    # ---- 人设 ----
    "persona": ("persona", "人设正文", "她的整段人格设定。改完保存再重启，会立刻换个人"),
    "persona_mode": ("persona", "人设模式", "auto / 整段 / 分段：一条回复要不要拆成几条发"),
    "persona_name": ("persona", "她叫什么", "自我介绍用的名字，比如 傻鱼"),
    "persona_role": ("persona", "身份定位", "一句话：她是谁、和主人什么关系、能不能做现实里的事"),
    "persona_personality": ("persona", "性格", "脾气秉性，写几条关键的就行，别写成简历"),
    "persona_speech": ("persona", "说话方式", "语气、长度、口癖、禁忌"),
    "persona_likes": ("persona", "喜欢 / 讨厌", "在乎什么、烦什么，用来决定她的反应"),
    "persona_rules": ("persona", "不做的事", "硬边界：不装活人、不说自己能出门、不泄露主人隐私"),
    "persona_extra": ("persona", "补充设定", "别的想加的都写这儿，可以是零散设定"),

    # ---- 说话 ----
    "reply_delay_per_char": ("talk", "打字延迟（每字）", "一个字停顿多少秒，模拟真人打字"),
    "reply_delay_min": ("talk", "最短停顿", "整条消息至少停多久再发"),
    "reply_delay_max": ("talk", "最长停顿", "整条消息最多停多久"),
    "reply_delay_jitter": ("talk", "延迟抖动", "在停顿上随机加减多少秒，避免节奏太机械"),
    "reply_max_segments": ("talk", "最多分几条", "一次回复最多拆成几条消息发出去"),
    "reply_max_chars_per_segment": ("talk", "每条字数上限", "拆分时每条最多多少字"),
    "single_message_max_chars": ("talk", "单条上限", "短回复整条发时的字数上限"),
    "strip_parentheses": ("talk", "删掉括号", "开启后回复里的（动作）括号会被真删掉"),
    "tame_ellipsis": ("talk", "收敛省略号", "把一长串省略号收拾成正常的"),
    "quote_reply": ("talk", "引用回复", "回复时带上被回复那条消息"),
    "auto_emote_probability": ("talk", "带表情概率", "回复时顺手甩一张表情图的概率，0 就是不带"),
    "debug_reply": ("talk", "调试输出", "把原始回复也打到日志里，排查用"),

    # ---- 接话闸门（REPLY_GATE_1106）----
    "reply_gate": ("talk", "接话闸门", "off=只走本地规则 / loose=拿不准就接 / balanced=让模型判（推荐）/ strict=没把握就闭嘴"),
    "gate_llm": ("talk", "让模型判说话对象", "关掉后只按 @、叫名字、引用判断，省 token"),
    "gate_llm_timeout": ("talk", "判定超时", "判一次最多等几秒，超时就按「大家」交给概率"),
    "gate_conf_min": ("talk", "判定把握门槛", "strict 档下低于这个把握度就当没跟她说"),
    "gate_budget_per_min": ("talk", "每群每分钟判定次数", "防刷屏烧 token，0 表示不限"),
    "gate_cache_seconds": ("talk", "判定缓存", "同一句话的判定结果缓存多久"),

    # ---- 破甲面板（PURGE_1106）----
    "purge_dir": ("misc", "dsh-purge 目录", "破甲面板用的 dsh-purge 安装目录，留空自动找"),
    "purge_node": ("misc", "破甲用的 node", "跑 dsh-purge 的 node.exe，留空自动找"),
    "purge_dsh_base": ("misc", "DSH 宿主根", "带 dsh-agent-instructions 的 @deepseek-ai 目录，留空自动找"),

    # ---- 主动 ----
    "proactive_probability": ("proactive", "主动接话概率", "群友说话但没点她时，插嘴的概率。0.2 已经算活泼"),
    "proactive_cooldown_seconds": ("proactive", "接话冷却", "同一个群两次主动接话至少隔多少秒"),
    "proactive_threshold": ("proactive", "兴趣门槛", "她判断「这话我接不接得住」的分数线，越高越挑剔"),
    "master_proactive_probability": ("proactive", "对主人插话概率", "主人在群里说话时她的接话概率"),
    "autonomy_enable": ("proactive", "自主活动总开关", "关掉后她不再自己判断要不要说话"),
    "autonomy_interval_min": ("proactive", "自主判断间隔", "多久自己盘一次「现在要不要开口」，单位分钟"),
    "bubble_noreply_cooldown_min": ("proactive", "冒泡没人接的冷却", "她冒泡后没人理，多久之内不再冒，单位分钟"),
    "autonomy_after_reply_gap_seconds": ("proactive", "刚说完就不冒泡", "刚跟人说完话，多少秒内不主动冒泡（防连发）"),
    "convo_window_seconds": ("proactive", "会话有效期", "跟某人聊起来后，这段会话保持多久，单位秒"),
    "convo_cooldown_seconds": ("proactive", "会话内最小间隔", "会话中她两条消息之间至少隔多少秒"),
    "convo_no_mention_turns": ("proactive", "几次不提就结束会话", "对方隔久了还没提她，累计几次就认为话题结束"),
    "convo_miss_min_gap_seconds": ("proactive", "算「没提我」的间隔", "间隔超过多少秒还没提她，才计一次，快聊不算"),

    # ---- 语音 ----
    "voice_chance": ("voice", "转语音概率", "短句被合成语音发出去的概率"),
    "voice_cooldown_min": ("voice", "语音冷却", "两次语音之间至少隔多少分钟"),
    "voice_max_chars": ("voice", "语音字数上限", "超过这个字数的内容不转语音"),

    # ---- 空间 ----
    "qzone_api": ("qzone", "空间服务地址", "本机空间服务的地址，用内置的话不用改"),
    "qzone_secret": ("qzone", "空间服务密钥", "空间服务的头 X-Qzone-Secret，别外传"),
    "qzone_every_hours": ("qzone", "发说说间隔", "多久自动发一条说说，单位小时"),
    "qzone_min_gap_hours": ("qzone", "说说最小间隔", "两次发说说最少隔多久，防止刷屏"),

    # ---- 记忆 ----
    "memory_per_session": ("memory", "每会话记几条", "每个群/私聊保留多少条上下文"),
    "memory_warn_enable": ("memory", "记忆告警", "记忆量太大时在日志里提醒"),

    # ---- 权限 ----
    "admins": ("perm", "管理员", "这批号能用管理指令，但还不是主人"),
    "non_admin_daily_limit": ("perm", "群友每日条数", "普通群友每天最多触发她多少次，0 表示不限"),
    "blacklist_users": ("perm", "黑名单用户", "这些号发什么都不理"),
    "whitelist_users": ("perm", "白名单用户", "只理这些号（配合开关用）"),
    "blacklist_groups": ("perm", "黑名单群", "这些群她不说话"),
    "whitelist_groups": ("perm", "白名单群", "只在这些群说话"),
    "auto_accept_friend": ("perm", "自动同意好友", "有人加好友自动通过"),
    "auto_accept_group_invite": ("perm", "自动进群", "被拉群邀请自动接受"),
    "silence_minutes": ("perm", "禁言时长", "被禁言时默认禁多少分钟"),
    "reply_cooldown_seconds": ("perm", "全局回复冷却", "两次回复之间至少隔多少秒，0 表示不限制"),

    # ---- 作息 ----
    "auto_sleep_start": ("sleep", "自动睡觉", "每天几点开始勿扰，格式 HH:MM"),
    "auto_sleep_end": ("sleep", "自动起床", "每天几点自己醒过来"),
    "wake_broadcast": ("sleep", "起床广播", "睡醒后在群里说一声"),

    # ---- 其他 ----
    "run_timeout": ("misc", "命令超时", "执行本地命令最多等多少秒"),
    "look_interval_min": ("misc", "看屏幕间隔", "多久看一次主人电脑屏幕，单位分钟"),
    "look_speak_cooldown_min": ("misc", "看屏幕后闭嘴多久", "看完屏幕后多久不再主动提"),
    "growth_interval_min": ("misc", "成长记录间隔", "多久沉淀一次成长记忆，单位分钟"),
    "agent_enabled": ("misc", "代理模式", "主人在私聊发 ! 开头的命令直接操作电脑"),
    "meme_harvest_auto": ("misc", "自动收集梗", "每天去网上扒一次梗"),
    "sing_enable": ("misc", "翻唱", "允许她唱歌（需要本机有 RVC）"),
    "local_mode": ("misc", "本地模式", "本地跑的时候不连云端、不建隧道"),
    "master_group_threshold": ("proactive", "主人的特殊门槛", "主人说话时她插话的额外阈值，0 表示主人有特权全接"),
    "vision_master_only": ("perm", "只有主人能看图", "开启后群友发图她不看"),

    # ---- 插件商店 / 分享 ----
    "store_repo": ("misc", "分享目标仓库", "把自己的插件分享到哪个 GitHub 仓库，user/repo 形式"),
    "store_branch": ("misc", "分享分支", "分享提交到哪个分支，一般 main"),
    "store_path": ("misc", "分享目录", "仓库里放插件的目录，比如 plugins"),
    "store_token": ("misc", "GitHub token", "分享插件用的 fine-grained PAT（Contents 读写），用完记得撤销"),
    "store_api_base": ("misc", "GitHub API 地址", "一般不用改，走镜像时才填"),
    "store_mirror": ("misc", "仓库镜像", "GitHub 打不开时用的镜像前缀"),
    "store_author": ("misc", "分享署名", "分享到商店时署的名字"),
}

# 功能开关的中文说明
FEATURE_META = {
    "autonomy": "自主活动：闲下来自己找事做",
    "search": "搜索：能用搜索引擎查东西",
    "vision": "看图：能看懂群友发的图片",
    "poke": "拍一拍：被拍会回应",
    "ban": "禁言：有权限时能禁人",
    "diary": "日记：每天自己写一篇",
    "web": "联网：抓网页、看热搜",
    "local": "本地操作：能在主人电脑上跑命令",
    "qzone": "空间：发说说、看动态",
    "proactive": "主动说话：没人叫也接话",
    "avatar": "换头像：自己定时换头像",
    "image": "发图：能搜图发图",
    "look": "看屏幕：能看主人屏幕（本地模式关掉）",
    "growth": "成长：记录自己的变化",
    "memory_index": "记忆索引：长期记忆的检索",
    "voice": "语音：把话合成语音发出来",
}

# 这些是运行状态，不给用户看
HIDDEN = {
    "last_auto_publish", "last_qzone_post", "qzone_last_post_at", "avatar.last_change",
    "avatar.current", "balance_last_check", "last_chat_seen", "autonomy_none_streak",
    "autonomy_last_spoke", "autonomy_last_run", "backup_last_ts", "tired_said_at",
    "last_private_dm_at", "last_bubble_text", "last_bubble_at", "temp_admins",
    "active_groups", "avatar.enabled", "avatar.interval_hours",
}
