# 交接文档（给下一个接手的开发会话）

> 2026-11-13 写于 M2.5；2026-11-14 在 M3 之后重写；2026-11-14 深夜在 M4 记忆、M5 手机 QQ、作息、夜空之后再次整体重写，之后随每次对话更新（那个会话里用户要求的）。
> 先读这份，再读 `README.md`（架构图）、`docs/PROTOCOL.md`（伪代码、一天的安排、QQ、记忆、HTTP 接口、文件——**现状以它为准**）、
> `docs/ROADMAP.md`（每一步的实测记录）。

## 1. 用户与环境

- 用户用中文交流；**改动后用中文汇报**，要具体：做了什么、实测结果、没测到什么、用户要做什么。
- **用户没有直接否认的建议，就当作认可，直接去做**（用户明说的）。需要用户拍板、又确实拿不准的设计问题才问，并给出建议。
  用户喜欢「能做的先做完再汇报」，不喜欢一直守着确认。用户的想法会变，前后矛盾时以最新的为准，真有冲突就问。
- **只在必要的时候用 API key 跑真实模型测试**：改了她看到的东西（规则、工具、消息）或者新玩法要看她会不会用时才跑；小改动用单元测试 + 本地快进。
- **每次用真实模型测试，都把完整日志给用户一份**（插件发给她的消息、她的思考、每段脚本和完整结果、手机消息、日记、结束）：
  `tools/fulllog.py` 导出成 Markdown，用 SendUserFile 发。记忆整理也一样（整理会话的输入和输出、`memory/memory.md`）。
- **交接文档只在用户明确要求时更新**（这一版就是）；PROTOCOL / README / ROADMAP / INSTALL-WINDOWS 随代码一起改。
- **设计时长要省着用**：用户嫌时间偏长时会说（做饭、收拾乱子都压过一次）。新动作先给短的。
- 运行环境：**Windows Server 2025 Datacenter 24H2**，mstsc（RDP）登录桌面；**DSH 桌面版 0.2.2-rc.2**，作为应用运行（不是服务）。
  profile 多半叫 `desktop`（安装脚本优先选它），里面还装了别的插件。**NapCat** 已经在本机登录 QQ。用户在中国（东八区）。
- 模型：**DeepSeek-V4.1-Flash**（API id `deepseek-flash`，支持图片输入；`deepseek-v4-pro` 只支持文本）。
- 用户希望：轻量、为自己定制；服务器算力不富裕（画面只在需要时渲染）；时间与现实 1:1；画面**只读**（人和 DS 都不用键鼠操作游戏，
  DS 用伪代码）；暖色田园风；她是**蓝发鲸鱼少女**（呆毛、鲸鱼尾巴、蓝白女仆装、围裙上的小鲸鱼；**没有鲸鳍耳**）；
  **一切尽量「在世界里」（in-universe）**：手机是 QQ 的道具，看画面是用手机拍照，对别人说话不提「自由活动」这类系统词。

## 2. 当前状态

代码在 **`claude/practical-ptolemy-31lvw0`**（从 `claude/happy-ptolemy-yj8v0n` 快进而来；更早的 M0–M2.5 在 `claude/laughing-turing-ush012`）。
**都还没合并进 `main`。** 用户还**没在自己的 Windows 上跑过 M4 / M5**，也没接真实 NapCat——所有端到端测试都在容器里用假 NapCat 做的。

| 里程碑 | 现状 |
| --- | --- |
| M0–M3 | DSH 插件、Python 小屋进程、伪代码、世界、经济、随机事件、LPC 画面、动作花真实时间 |
| 一天 | 7:30–8:30 醒来 = 第一段自由活动，中午、傍晚、晚上各一段（40 分钟）；23:30–24:00 睡觉（睡前整理日记）；0 点换天 |
| 会话 | **每天一个会话**：当天的自由活动、手机 QQ、睡前都在里面；第一条消息带完整人设 + 记忆；系统提示词只有人设第一段 + 规则 |
| M4 记忆 | 每晚 0:10 用不带人设的「记忆整理」会话读当天会话全文 + 日记 → JSON → `memory.json`，按天淡忘 |
| M5 QQ | 插件直连 NapCat；手机道具；私聊（主人 + 账号的好友）；好友请求；图片、QQ 表情；语音 / 文件挡掉；睡着时挡掉；群聊暂时关（代码注释保留） |
| M7 | 18 道家常菜、物价、猫玩具和乱子、看夜空 `look_at_sky()`（真实月相、流星雨）、在海边玩水 `play_in_water()`（水温、脚下、小鱼、海面上的光；月光不说月相，满月多写）、快递每天下午来一次（没有名字、不和她打交道）、日常活动（叫醒时才生成小结果） |

测试：`house/` 105 个（`python -m unittest discover -s tests`），`plugin/` 29 个（`npm test`）。

她现在能用的工具（生活会话，preset `little-house`）：
`house_do(script)`、`house_photo`（用手机给小屋拍照，自己看）、`end_free_time`、`end_errand`、
`phone_message(text, photo?, to?)`、`phone_friend_request(qq, accept)`、`diary_write` / `diary_edit(time, text)` / `diary_read(day?)`。

## 3. 关键设计与踩过的坑（改代码前务必看）

### DSH（cordis 插件框架）

- **会话创建**照抄 dsh-schedule：`ctx.get('sessionController').create({ sessionId, cwd, agentPreset })`
  → `resolveAgent(sessionId)`（返回 `{agent}` 或 `{error}`）。标题用 `ctx.get('sessionTitle')?.rename(session, title)`。
- **发消息给她一律用 `agent.steer(createUserMessage(...))`**：空闲时开一轮，正在跑的一轮在下一步插进去（QQ 消息在她做饭时也能进来）。
  `followup` 只用在一次性的记忆整理会话。发完 `ctx.sessions.flush(agent.session)`。
- **会话事件**：`ctx.on('session/event', (session, event) => …)`，事件有 `user/message`、`assistant/message`、`tool/call`、`tool/result`、`turn/end`。
  插件用它记当天会话全文（`transcripts/`）和等记忆整理会话的回答（`runOnce`）。
- **preset 子插件注册的工具，在 agent 看来是「继承的」**：`tools.restrict({ allow: [] })` 会连自己的工具一起藏掉。
  做法：`restrict({ deny: <挂载时全部全局工具名> })` + `tools.guard()` 只放行 `OWN_TOOLS`（`plugin/agent-scope.js`）。**新增工具必须加进 `OWN_TOOLS`**。
- 工具超时是工具自己声明的（`defineTool({ timeoutMs })`）；`house_do` 声明 60 分钟并响应 `exec.signal`。
  **Node 的 `fetch` 5 分钟收不到响应头就断**，所以 `house_do` 分段等：`POST /do {wait: 240}`，没做完就 `POST /report`。
- **DSH 进程里 Node 自带的 `WebSocket`（和 fetch 一样走全局 dispatcher）可能被代理劫持，连 127.0.0.1 都连不上**（容器里就是）。
  所以 QQ 用自己写的极简 WebSocket 客户端（`plugin/lib/ws-client.js`，`node:http` + `agent: false`）。
- `systemPrompt.suppressRuntimeContext()` 去掉编程向上下文；`complete: true` 的 section 是她的整个系统提示词。
- `exec.concludeTurn()`（`end_free_time` 里）直接结束这一轮。
- **`defineTool` 的输出 schema 顶层不能写 `required`**；`ctx.inject(...)` 回调里抛的错会被**静默吞掉**——看 `~/.dsh/little-house/plugin.log`。
- 工具结果里返回图片：`ctx.inject(['attachments'], …)` → `attachments.saveImage({data, mediaType, name})` → `{ type: 'image', attachment }`。
  用户消息里带图片：`{ type: 'image', attachment: ref }` 放进 `createUserMessage` 的 content（QQ 收到的图片就是这样给她看的）；宿主级服务用 `ctx.get('attachments')`。
- 插件引用宿主包靠 `peerDependencies` + DSH 的 peer 拦截；插件目录没有 `node_modules`。**单元测试只能测 `lib/` 里的纯函数**。
- 改 profile 的 `cordis.patch.yml` 会热重载插件；改插件 JS 要重启 DSH。patch 一行会**整体替换**该行的 `config`；新 profile 里那行 `[]` 要先删掉。
- 会话日志是多帧 zstd（`~/.dsh/sessions/<cwd>/<id>/session.v4.jsonl.zstd`）；用量在 `assistant/message.data.usage`，**`inputTokens` 不含缓存命中**（`cacheReadTokens` 另算）。

### 一天、会话和作息（`plugin/index.js`）

- `dayKey()` = `dayOf(now, session.rolloverHour)`，默认 0 点换天。`dayAgent()` 拿当天会话（有锁，避免唤醒和 QQ 同时开两个）。
- `intro(agent)`：会话的第一条消息前面加「（日期，新的一天。）## 你是谁（完整人设）## 你的记忆」。人设文件里的 `<!-- -->` 注释不给她；
  `personaBrief()`（第一段）放系统提示词。
- 作息：`dayTimes()` = 当天醒来时间（第一个时段的开始）和睡觉时间（`sleep.from–to` 随机，存在 `plugin-state.json` 的 `beds`）。
  `isAsleep()` = 醒来之前或睡觉之后。`goToBed()`：结束所有窗口和接管，告诉小屋 `asleep: true`，发「该睡觉了，看看今天的日记」。
  醒来就是早上那段自由活动（`buildWakeMessage({ wokeUp: true })`，`asleep: false`）。
- **自由活动窗口**（`windows`，按会话 id）：`openWindow` → 到点 `timeUp`。**`timeUp` 先问小屋 `/status`**：正在做事，或有开了头的事
  （`unfinished`：灶上的菜、这次做好没吃的菜、猫弄的乱子）就**加时**（最多 30 分钟，`POST /session {overtime: true}`），小屋只接受做完这些的动作；
  否则结束。`end_free_time` 第一次调用如果还没写日记，只**问**（日记、要不要给主人发消息），再调一次就结束——**不强制写日记**。
  她提前停下、时间还多时 2 分钟后再叫她（最多 2 次）；加时里她停下就结束。
- **自由活动以外**：`house_do` 先用 `look_only` 试（`surroundings` / `inventory` / `help` 马上回答）；要做别的，小屋回 `needs_control`，
  插件就让她**接管角色**（`startControl`，最多 `control.maxMinutes` = 30 分钟），做完 `end_errand()`；忘了的话这一轮结束时自动交还。睡前那一轮不能接管。
- QQ 消息来时（`phoneBuzz`），自由活动以外的开头是「（23:10，不是自由活动时间。你的角色此刻在客厅，陪团子玩（团子……）。手机响了，是 QQ 消息：）」。

### 手机和 QQ（`plugin/qq.js`、`lib/onebot*.js`）

- 正向连接 NapCat 的「WebSocket 服务端」（`qq.url` + `accessToken`），断线指数退避重连；动作按 `echo` 对应回复。
- 谁的私聊交给她：主人（`ownerQQ`）+ `others`（默认 `friends` = **NapCat 登录的那个账号的好友**，`sub_type === 'friend'`；`listed` / `none`）。
  别人显示成「主人的朋友<备注或昵称>」（好友请求里还不是朋友，不这么叫）。给她发过消息的人记在 `qq-contacts.json`，`phone_message(to: 名字)` 用。
- **她直接写的文字不会发出去**，回消息只能用 `phone_message`（空行分条、`[表情:名称]` ↔ QQ face、去 Markdown）。
- 语音 / 视频 / 文件 / 合并转发 / 卡片在桥这里挡掉（`readMessage().dropped`），只记录；只有这些内容的消息不叫醒她。
- 睡着时一律不交给她，自动回 `qq.sleepReply`（同一聊天半小时一次）。
- 好友请求（`post_type: request`）：告诉她是谁、验证消息，规则让她先问主人，再 `phone_friend_request`（`set_friend_add_request`）。
  睡着时来的存在 `qq-requests.json`，早上醒来的消息里告诉她。
- 群聊：用户说**先不做**。`qq.js` 里群聊的代码以注释保留，配置里的 `groups` / `names` 也注释掉了。
- QQ 表情名表 `lib/qq-faces.js` 是从 dsh-onebot 搬的（BSD-3，文件头保留许可，NOTICE 里登记）。

### 记忆（`plugin/lib/memory.js`、`memory-scope.js`）

- 原料：**当天会话全文**（`recordTranscript` 边发生边写 `transcripts/<day>.jsonl`：消息、她写的话、工具调用、结果前 400 字；不含思考和 intro）
  + 当天日记 + 现有记忆（第一天没有）。没有会话记录的旧日子退回 `qq/<day>.jsonl`。
- 0:10（和 DSH 启动时，补最多 7 天）开「记忆整理 · 日期」会话（preset `little-house-memory`：**不带人设、没有任何工具**），回一个 JSON：
  `summary`（最近的日子，可含适量平凡日常）、`plans`（**想做的事，必须列**）、`memories`（**只放不能忘的**：约定、主人的习惯、重要的第一次）、
  `people`（TA 的身份或职业——只写提到过的、喜好和习惯、最近的事不超过四件；不写「印象」这种主观判断）、`recalled` / `done`（编号）。
  `memories` 的原话：「只放重要、不能忘的事：和别人的长期约定、小屋生活中很重要的大事、给自己立下的 flag 等等」。`mergeDay` 合并，`forget` 删掉忘了的，`archive.jsonl` 永久留底。
- 淡忘（纯代码）：按「上次想起」到今天的天数一档档变（清晰 → 清楚 → 模糊 → 只剩印象 → 忘记），想做的事快一倍，重要度 ≥ 90 不忘。
  `render(..., { maxChars })`：默认 6000 字，超了先少放旧日子。

### 小屋：实时执行、动作、错误提示

- `tasks.Runner` 按游戏时钟播放脚本；动作是生成器（yield `walk` / `work` / `wait`），打断时把 `Interrupted(done)` 抛进去。
  **到点不打断正在做的一步**，只是不再开始后面的步骤（`deadline`）。新动作：简单的在 `content.ACTION_SECONDS` 配时长，分阶段的写成 `proc=True` 生成器。
- **写错只有两类提示，不猜**（用户要求）：动作名不存在 → 列出「这里能用的动作 / 其他地方的动作」；写的东西找不到 → 列出这里有的、背包里有的、
  目录上有的、菜谱上的菜名。别的房间里有的东西说在哪。新东西不用再维护对照表。状态类提示（先 goto(厨房)、还缺原料……）照旧。
- 手机：`content.PHONE`，一直在背包里，`take_item` 拒绝拿走它；老存档加载时补上。
- 看夜空：`sky.py`（真实月相、月出、流星雨极大夜）+ `actions.sky_view()`（没有副作用的夜空描述）+ `look_at_sky()`；`content.SKY_EVENTS` 是随机小事。
  海边：`play_in_water()`，结果带 `actions.sea_light()`（清早朝阳、白天阳光、傍晚夕阳、晚上按真实月相的月光、雨 / 阴天）。
- 动作名：看名字就懂，多个词用下划线连起来（用户要求的）：`call_cat`、`feed_cat`、`stroke_cat`、`play_with_cat`、`tidy_mess`、`pick_up`、`water_plants`、`put_on_shelf`、`play_in_water`、`look_at_sky`；没有 `say`；`open` 管邮箱、包裹和漂流瓶。工具：`house_photo`、`end_errand`。
- **日常**（`content.IDLE_ACTIVITIES`，`world._routine`）：每小时一件，**只是个样子，不改变世界、不记录**；不安排答不上细节的事（看书）。
  有消息叫醒她时 `world.idle_story()` 才临时生成一个小结果（`actions.STORIES`：团子的反应、海边玩水 + 海面上的光、钓鱼（不会真钓到）、
  沙滩散步 / 夜里看海的海面、夜空），同一件事里不变。收拾屋子去最干净的房间（真正脏的留给她）；陪团子玩跟着猫走；钓鱼要有鱼竿、不打雷；
  午觉只在 12–16 点。日常里的收拾、陪猫、玩水、钓鱼、看星星，她在自由活动里也能自己做；发呆、喝茶、午觉、晒太阳、散步、看海没有对应动作。
- 加时：`world.free_open()`（插件还没关掉窗口）、`unfinished()`、`overtime_problem()`；`set_free(until, overtime)`；`resident.cooked` 记这次做的菜。
- 存档 `world/world.json` 当前 v5，`World.load_json` 里有迁移；**改存档结构要加迁移并写测试**。
- **画面和文字描述同一个世界**（用户明确要求）：唯一来源是 `content.APPEARANCE`；改画面时同步（`tests/test_consistency.py`）。
  画面里没画月亮，所以文字里的月相不冲突；以后要画月亮必须按 `sky.moon_phase` 画。
- 物价：1 贝币 ≈ 1 元人民币；开拓署略低于零售价收原料，不收做好的菜。

### 小屋：画面

- `render.render(world, t, pose)`；窗口在 `display.py`，跑在小屋进程**主线程**，开关走 `POST /window`。
  **不要在小屋进程里设置 `SDL_VIDEODRIVER=dummy`**（会让后来打开的真窗口失效）。容器里用 Xvfb 验证过真窗口能开、能动。
- LPC 素材在 `house/littlehouse/assets/lpc/`，`sprites.py` 运行时切图；**素材缺失时退回代码绘制**；**加新素材必须在 `CREDITS.md` 写清来源、许可、作者**。
- 墙和地板还是代码画的。用户的看法：地板不用换（一眼认得出）；墙最弱，但只是好不好看的问题，排得很后。

## 4. 下一步

1. **请用户在 Windows 上实际跑起来**：`git pull` 这个分支、完全重启 DSH；按 `docs/INSTALL-WINDOWS.md` 第 6 节开 NapCat 的 WebSocket 服务端、填 `qq` 配置。
   看一整天：早上醒来、QQ、好友请求、睡前、`memory/memory.md`、`plugin.log`。以前用过 dsh-onebot 的话别让它连同一个账号。
2. 还没在真实模型上碰到过的：早上醒来作为当天第一条消息（单元测试覆盖）、夜里来的好友请求早上告诉她、「别答应待会儿」那条规则、0:10 定时整理（整理本身测过）。
3. **M6 上网**：用手机上网（RSS、小说带书签、网页正文；只读、站点白名单、防 SSRF），看到的东西她可以写进日记 → 进记忆。
4. 群聊（用户说以后再做；代码已注释保留）。
5. M8 设置界面（额度、记忆查看、开关）；墙面素材（可选）。

## 5. 用户做过的决定（备查）

- 写错：**只有两类提示，列出能写的，不猜、不替她改**；菜名没有别名表。
- 不设精力 / 疲劳，只有饥饿；可以订即食食品。
- 作息：7:30–8:30 醒来就是早上的自由活动，中午、傍晚、晚上各一段（每天都有）；23:30–24:00 睡觉，睡前整理日记；睡着时 QQ 挡掉；0 点换天。
- **一天一个会话**（小屋 + 手机）；人设和记忆写在第一条消息里，系统提示词只放简短人设。
- 日记：醒着随时能写、改、读以前的；不强制，结束自由活动时问一句。改之前先 `diary_read()` 看时间。
- 记忆：原料是会话全文 + 日记；四块：最近的日子（可含平凡日常）、想做的事（必须有）、记得的事（长期约定、小屋生活里的大事、给自己立的 flag）、认识的人（身份、喜好习惯、最近四件事；不写印象）。
- QQ：直连 NapCat，不用 dsh-onebot；回复只能用 `phone_message`；条数不限；主动发消息只在自由活动里（随时），结束时问一句不强制；
  账号的好友可以私聊，她也能应他们的请求做事；好友请求先问主人；语音文件挡掉；群聊先不做。
- 自由活动以外：主人或朋友请她做事时可以接管角色，做完 `end_errand()`；不能答应「待会儿」做什么，请对方晚点再提醒（不提「自由活动」）。
- 自由活动到点：手上的事做完为止；成套的事（做饭→吃饭、猫弄坏的东西）可以顺延做完，其他动作拒绝，日记和 end_free_time 随时可以。
- 日常：不安排答不上来的事（看书）；只是个样子，没人问就不发生；有人问才临时生成结果；打扫不去真正脏的房间；有在海边玩水、钓鱼；不给植物「擦叶子」。
- 动作名要一看就懂：`play_with_cat`、`play_in_water`、`look_at_sky`。
- 时长：做饭分「必须守着」和「下锅后能走开」；一圈想做的事约 20 分钟；`tidy_mess` 每处 5–15 秒。
- 画面：LPC 素材；去掉鲸鳍耳；地板不用换。

## 6. 容器里的测试环境

新会话的 scratchpad 路径会变，里面的东西会丢；**要长期保留的工具都放在仓库的 `tools/`**。

- 云环境「LittleHouseOfDeepSeek」有**启动脚本**：新容器建好时在 `/opt/lh` 装 DSH 0.2.2-rc.2（`/opt/lh/dsh`）和带 pygame-ce、zstandard 的 venv（`/opt/lh/venv`）。
  （2026-11-14 加的，下一个新会话才第一次真正跑；如果 `/opt/lh` 不在，就照 `tools/devenv.sh` 开头的注释手动装，约 1 分钟。）
- `tools/devenv.sh <工作目录> [分钟] [qq]`：建测试 profile `lhtest`、写 overlay，打印启动命令。分钟 > 0 时启动 5 秒后来一段临时自由活动；`qq` 连假 NapCat（主人 QQ 123）。
  启动命令里加 `TZ=Asia/Shanghai` 就是用户的时区（测晚上的事很方便：容器是 UTC）。
- `tools/fake-napcat.mjs`：假 NapCat（ws 3001，控制口 3002）。`POST /private {user_id, text, image, voice, nickname}`、`POST /request {user_id, nickname, comment}`、`GET /outbox`。
- `tools/fulllog.py <DSH_HOME> <out.md> [开场消息里的一段文字] [--diary 目录]`：导出完整日志（找最新的、第一条消息含那段文字的会话；当天会话用 `"## 你是谁"`）。
- `tools/shot.py <out.png>`：渲染一张截图。
- 想造「没做完的事」：DSH 停着时往 `world/world.json` 的 `jobs` 里塞一锅还没好的菜。想测记忆整理：把某天的 `transcripts/`、`diary/` 复制成更早的日期再重启。
- **DeepSeek API key** 在云环境的网络密钥里（代理注入，`DEEPSEEK_API_KEY=proxy-injected` 只是占位）。失效的话用 `request_credential` 重新申请，不要让用户贴进聊天。
- 等日志里的某一行时注意：`plugin.log` 里有以前的同名行，等待条件要带时间戳或只看新行。
- 杀测试进程时，别用会匹配到自己命令行的 `pkill -f`（会把当前 shell 也杀掉）：用 `pgrep` 列出再逐个 `kill`。

## 7. 仓库地图

```
plugin/            DSH bundle（纯 ESM JS，无构建）
  index.js         宿主服务 littleHouse：小屋进程、作息、当天会话、自由活动窗口 / 加时 / 接管、睡觉、记忆整理、会话全文
  agent-scope.js   生活会话的规则（简短人设 + 规则）和工具（house_do、house_photo、end_*、phone_*）
  diary-scope.js   diary_write / diary_edit / diary_read
  memory-scope.js  记忆整理会话（不带人设、没有工具）
  qq.js            QQ：收消息、好友请求、睡着时挡掉、phone_message、记录
  lib/             wake.js（作息、消息文本）、slots.js、diary.js、memory.js、onebot.js（消息格式）、onebot-client.js、ws-client.js、qq-faces.js、house-process.js
  persona/         示例人设（第一段 = 简短版）
  cordis.patch.yml 三行：little-house 服务、little-house preset、little-house-memory preset
house/littlehouse/ 小屋：content（一切数值、日常、夜空小事）/ world（状态、日常、加时、灶台）/ actions（动作、提示、日常小结果）/
                   sky（月相、流星雨）/ tasks（执行器）/ script（解析、结果格式）/ server（HTTP）/ scene / anim / render / sprites / display / repl / clock
house/tests/       unittest（world / tasks / anim / render / consistency / sky）
tools/             devenv.sh、fake-napcat.mjs、fulllog.py、shot.py（只用于开发）
scripts/install.py 装进 / 卸出 DSH profile
docs/              INSTALL-WINDOWS / PROTOCOL / ROADMAP / HANDOFF + 截图
```
