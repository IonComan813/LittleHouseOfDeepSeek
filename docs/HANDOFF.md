# 交接文档（给下一个接手的开发会话）

> 2026-11-13 写于 M2.5；2026-11-14 在 M3 + LPC 画面 + 内容扩充之后整体重写。
> 先读这份，再读 `README.md`（架构图）、`docs/PROTOCOL.md`（伪代码、动作时长、HTTP 接口、文件）、`docs/ROADMAP.md`（每步的实测记录）。

## 1. 用户与环境

- 用户用中文交流；**改动后用中文汇报**，要具体：做了什么、实测结果、用户要做什么。
- **只在必要的时候用 API key 跑真实模型测试**：改动不太可能出问题、或者改动比较小时，单元测试 + 本地快进就够了，不调用 DeepSeek。
  改了她看到的东西（规则、工具、开场消息）或者新玩法需要看她会不会用时才跑。
- **每次用真实模型测试，都把完整的伪代码日志给用户一份**（插件发给她的消息、她的思考、每段 `house_do` 脚本和完整结果、日记、结束），
  用第 6 节的 `tools/fulllog.py` 导出成 Markdown，用 SendUserFile 发过去。
- **交接文档只在用户明确说要换会话时更新**（这一版就是用户要求写的）；其他文档（PROTOCOL / README / ROADMAP）随代码一起改。
- **设计时长要省着用**：用户嫌时间设得偏长时会说（做饭、收拾乱子都压过一次）。新动作先给短的。
- 用户喜欢「能做的先做完再汇报」，不喜欢一直守着确认；但需要用户拍板的设计问题（方向、取舍）要问，并给出建议。
- 运行环境：**Windows Server 2025 Datacenter 24H2**，mstsc（RDP）登录桌面；**DSH 桌面版 0.2.2-rc.2**，作为应用运行（不是服务）。
  profile 多半叫 `desktop`（安装脚本优先选它）。用户的 profile 里还装了别的插件。**NapCat** 已经在本机登录 QQ 并能收发（M5 用）。
- 模型：**DeepSeek-V4.1-Flash**（API id `deepseek-flash`，支持图片输入；`deepseek-v4-pro` 只支持文本）。
- 用户希望：轻量、为自己定制；服务器算力不富裕（画面只在需要时渲染）；时间与现实 1:1；画面**只读**（人和 DS 都不用键鼠操作游戏，
  DS 用伪代码）；暖色田园风；她是**蓝发鲸鱼少女**（呆毛、鲸鱼尾巴、蓝白女仆装、围裙上的小鲸鱼；**没有鲸鳍耳**，用户要求去掉了）。

## 2. 当前状态

代码在 `claude/happy-ptolemy-yj8v0n`（M0–M2.5 在 `claude/laughing-turing-ush012`，本分支从它快进而来）。**都还没合并进 `main`。**

| 里程碑 | 内容 |
| --- | --- |
| M0–M1.5 | DSH 插件、独立的「小屋生活」会话、工具白名单、Python 小屋进程、伪代码、世界内核、贝币经济、随机事件 |
| 日记 | `diary_write` / `diary_read`，她自己决定写不写 |
| M2 / M2.5 | 只读像素画面；`house_render` 看一帧；`view.bat` 动画窗口（同一进程） |
| M2.6 | 画面换成 LPC 素材（家具、厨房、户外、四季的树、作物）；她由 LPC 角色图层拼成 + 代码画的鲸鱼部分；团子是 LPC 橘猫 |
| M3 | 动作花真实时间（实时执行器、可打断）；每日作息（自由活动 / 平淡的日常）；操作提示 |
| M7（进行中） | 18 道家常菜、物价对齐人民币、新作物和肉类、陪猫玩 + 猫玩具、猫闯的祸和 `tidy()`、`goto(团子)` |

测试：`house/` 88 个（`python -m unittest discover -s tests`，无 pygame 时跳过渲染测试），`plugin/` 11 个（`npm test`）。
在容器里用真实 DSH 0.2.2-rc.2 + deepseek-flash 跑过多次端到端（实测记录在 ROADMAP）。
**还没在用户的 Windows 桌面上看过动画窗口和新画面**——请用户 `git pull` 后双击 `view.bat` 看。

她现在能用的工具：`house_do(script)`（所有行动，包括看看四周 `surroundings()`）、`house_render`（看一帧画面）、
`end_free_time(note?)`（结束这次自由活动，可以提前）、`diary_write` / `diary_read`。

## 3. 关键设计与踩过的坑（改代码前务必看）

### DSH（cordis 插件框架）

- **会话创建**照抄 dsh-schedule：`ctx.get('sessionController').create({ sessionId, cwd, agentPreset })`
  → `resolveAgent(sessionId)`（返回 `{agent}` 或 `{error}`）→ `agent.followup(createUserMessage({content, source: {kind: 'little-house'}}))`
  → `ctx.sessions.flush(agent.session)`。标题用 `ctx.get('sessionTitle')?.rename(session, title)`。
- **preset 子插件注册的工具，在 agent 看来是「继承的」**：`tools.restrict({ allow: [] })` 会连自己的工具一起藏掉。
  做法：`restrict({ deny: <挂载时全部全局工具名> })` + `tools.guard()` 只放行 `OWN_TOOLS`（`plugin/agent-scope.js`）。
  **新增工具时必须把名字加进 `OWN_TOOLS`**，否则会被守卫拒绝执行。
- **工具超时是工具自己声明的**（`defineTool({ timeoutMs })`），不声明就不限时；`house_do` 声明了 60 分钟并响应 `exec.signal`
  （DSH 中止这一轮时 `POST /interrupt`）。
- **Node 的 `fetch` 5 分钟收不到响应头就断**，所以 `house_do` 分段等：`POST /do {wait: 240}`，没做完就 `POST /report {id, wait: 240}` 接着等。
- `systemPrompt.suppressRuntimeContext()` 去掉编程向上下文（也就没有 DSH 自带的日期时间）；`working-directory` 一段去不掉（无害）。
  她看到的所有时间都来自小屋的游戏时钟，插件开场消息的时间也从 `/status` 的 `now` 取。
- 生活会话的系统提示词用 `complete: true` 的 section（人设 + 规则）。**QQ 会话不能这样做**：complete 会把 dsh-onebot 的平台提示词也吞掉。
- `exec.concludeTurn()`（`end_free_time` 里）直接结束这一轮。
- **`defineTool` 的输出 schema 顶层不能写 `required`**；在 `ctx.inject(...)` 回调里抛的错会被**静默吞掉**——插件把日志写到
  `~/.dsh/little-house/plugin.log`。调试先看这个文件。
- 工具结果里返回图片：`ctx.inject(['attachments'], ...)`，`attachments.saveImage({data, mediaType, name})`，再返回
  `{ type: 'image', attachment: ref }`（见 `house_render`）。
- 插件引用宿主包（`@deepseek-ai/dsh-tools`、`dsh-llm`、`cordis`、`schemastery`）靠 `peerDependencies` + DSH 的 peer 拦截；
  插件目录没有 `node_modules` 也能跑。所以**单元测试只能测 `lib/` 里的纯函数**（`index.js` 引宿主包，测试里 import 不了）。
- 改 profile 的 `cordis.patch.yml` 会**热重载**插件（小屋进程跟着重启）；改插件 JS 要重启 DSH。
  新 profile 的 patch 文件里常有一行 `[]`，**直接追加会让 DSH 启动失败**，要先删掉。patch 一行会**整体替换**该行的 `config`。
- 会话日志是多帧 zstd（`~/.dsh/sessions/<cwd>/<id>/session.v4.jsonl.zstd`），要跨帧解压；用量在 `assistant/message.data.usage`。

### 小屋：实时执行

- `house/littlehouse/tasks.py` 的 `Runner` 按游戏时钟播放脚本。每个动作是生成器（`actions.process`），yield 阶段
  （`walk` 沿路点走、`work` 做事、`wait` 等待），返回结果文字。打断时把 `Interrupted(done)` 抛进生成器，由动作自己决定做一半的结果
  （炒菜糊、打扫进度保留、钓鱼空竿……）。执行器只在被推进时动：小屋 ticker 线程（忙时 0.25 秒一次）、等脚本的 HTTP 请求、测试里的快进。
- 新动作：简单动作在 `content.ACTION_SECONDS` 配时长；要分阶段、能被打断的写成 `proc=True` 的生成器（参考 `_cook`、`_clean`、`_fish`、`_tidy`）。
  特效名在 `anim.EFFECTS`，站位在 `actions.ACTION_SPOTS` / `world.stand_at`。
- **写错就整段不执行、只给建议（用户要求）**：脚本先过 `actions.check_calls`，有不存在的动作或参数太多就整段拒绝（`script.refuse_bad_steps`），
  用 `actions.suggest`（常用词对照表 `SYNONYMS` + 拼写相近）给出建议。**绝不自动替她换成正确的动作**；菜名也一样
  （`content.DISH_ALIASES` 只用来提示「你是不是想做荷包蛋」）。新动作要考虑往 `SYNONYMS` 里加常见的别称。
- **操作提示**（用户要求）：每段结果末尾有 `menu_line`（这里能做的动作 + 简短说明，`actions.SHORT`）；只写动作名会走 `actions.options()`
  列出能填什么；做不了的动作要说怎么才能做（`先 goto(厨房)`、`团子在卧室……goto(团子)`、`可以 order(...)`）。**新动作要补这三处。**
- 脚本只在内存里；灶台上的菜（`world.jobs`）、乱子（`kind="mess"` 的物件）、猫的状态在存档里（v4）。

### 小屋：时间和作息

- 自由活动由插件 `POST /session {free_until}` 开关；小屋据此决定 `deadline`（到点不再开始新的一步）、结果里的「还剩多少分钟」、
  时段外的日常（`content.IDLE_ACTIVITIES`，每小时挑一件走过去做；23–7 点睡觉）和时段外的饥饿上限（≤ 60）。
- **没有精力 / 疲劳**（用户要求去掉，自由活动本来就短，不强迫她休息）；只有饥饿。没有 `rest()`，等就 `wait()`。
  饿了可以做饭，也可以订即食食品（饭团、三明治、便当……），省下做饭的时间去陪猫之类。
- 时长全部在 `content.py`：`WALK_TILES_PER_SEC`、`ACTION_SECONDS`、`EAT_SECONDS`、`RECIPES`（每道菜的 `work` / `wait`）、
  `CLEAN_DIRT_PER_MINUTE`、`FISH_SECONDS`、`PLAY_SECONDS`、`MESSES`。`tests/test_tasks.py` 有「一圈约二十分钟」的检查。
- 插件：`lib/wake.js` 作息表纯函数；每天投一次开始时间存在 `plugin-state.json` 的 `plans`；已结束的时段记在 `doneSlots`；
  DSH 在时段中途启动会以「继续」打开剩下的时间。她没调 `end_free_time` 就停下、时间还剩 ≥ 5 分钟时，2 分钟后再叫她（最多 2 次）。

### 小屋：世界

- 存档 `world/world.json` 有版本号（当前 v4），`World.load_json` 里有迁移。**改存档结构要加迁移并写测试。**
  旧存档里的旧菜（煎蛋、萝卜汤……）和旧家具（风铃、懒人沙发）保留为能吃 / 能显示的物品。
- 「世界自己发生的事」用 `world.log(..., actor="world")`，会进 `/news`，下次自由活动开始时告诉她「这段时间里」；
  她自己的动作是 `actor="resident"`，变成「上次自由活动的时候，你……」（太长的截到 40 字）。
- 世界描述里提到的地方 / 东西必须真的能去 / 能用。
- **画面和文字必须描述同一个世界（用户明确要求）。** 唯一来源是 `content.APPEARANCE`：`render.py` 按它画，`examine`、房间描述、
  家具描述都用它。改画面时同步改这张表（`tests/test_consistency.py` 检查「画了但没描述」）。
- 物价：**1 贝币 ≈ 1 元人民币**；开拓署按略低于零售价收购原料，不收做好的菜（`tests/test_world.py` 有检查）。
- 猫：`play` 的结果看当天脾气 / 饿不饿 / 刚玩过没有 / 是不是最爱的玩具；和她在一起后 10 分钟不乱走；没人看着时偶尔闯祸（`CAT_MISCHIEF`）。

### 小屋：画面

- `render.render(world, t, pose)`；不传 pose 时用 `anim.current_pose`（此刻的真实状态）。窗口在 `display.py`，跑在小屋进程**主线程**，
  开关走 `POST /window`。渲染时持有 `house.lock`。**不要在小屋进程里设置 `SDL_VIDEODRIVER=dummy`**（会让后来打开的真窗口失效）。
- LPC 素材在 `house/littlehouse/assets/lpc/`（原样拷贝），`sprites.py` 运行时切图；`SPRITES` 表是名字 → (文件, 矩形)。
  **素材文件缺失时每样东西都退回代码绘制**（`tests/test_render.py` 有检查）。
  **加新素材时必须在 `CREDITS.md` 写清来源、许可、作者**（CC-BY-SA / GPL / OGA-BY，不是 Apache）。
- 她：`sprites.resident(direction, frame)` 把 LPC 角色图层（身体、头、长发、蓝衬衫、白围裙、裙子）叠起来，头发和裙子按亮度重新上色成蓝色，
  再画呆毛、鲸尾、围裙上的小鲸鱼。走路用左右 8 帧，其他时候面朝前。图层来自
  [Universal LPC Spritesheet Character Generator](https://github.com/LiberatedPixelCup/Universal-LPC-Spritesheet-Character-Generator)：
  路径在它的 `CREDITS.csv` 里，原图在 `spritesheets/<路径>`，有颜色的在 `spritesheets/<路径去掉 .png>/<颜色>.png`。
- 布局：场景仍是 40×26 个 16px 格子，LPC 素材按原尺寸画（32px = 2 格），家具位置按素材大小调过（`scene.FIXTURES`）。

## 4. 下一步（按用户意图排序）

1. **请用户在 Windows 上看新画面**：`git pull`、`pip install pygame-ce`、重启 DSH、双击 `view.bat`。
   旧的插件配置如果覆盖过 `wake`（minIntervalMinutes 等旧键），要换成新的 `slots`。
2. **M5 QQ（复用 dsh-onebot）**——用户已同意复用：
   - 方案 A（先试）：dsh-onebot 原样安装，`agentPreset` 指向新增的 `little-house-qq` preset：`dsh-persona` 行（同一份人设，**不要 complete**）、
     `dsh-little-house/diary`（`config.source: QQ`）、注入「小屋近况 + 最近日记」的 system prompt section、可选只读的 `surroundings`。
     关键待验证：我们往 dsh-onebot 的 QQ 会话里 `followup` 一条消息时，回复会不会经 dsh-onebot 发回 QQ。
   - 方案 B：把 dsh-onebot 的 connection / cq / inbound / outbound 核心（BSD-3，保留声明）搬进本插件。
   - **用户的决定**：自由活动以外也可以回复收到的 QQ 消息，但不主动发；主动行动（主动分享）都放在自由活动时间里。
     自由活动 40 分钟里，小屋里的一圈大约 20 分钟，剩下的留给 QQ 和上网。
   - 夜间（0–8 点）：QQ 消息按概率决定是否送达模型；不送达就直接回一句「她在睡觉」。主动分享要有每日上限、白名单。
3. **M4 记忆**：小屋和 QQ **共用一份**。原料：`world/events.jsonl` + `diary/*.md` + QQ 会话。每天（或每段自由活动后）总结一段，
   再维护一张会衰减的长期记忆卡（参考 surfcore 的 memory-card），注入生活会话和 QQ 会话。
4. M6 上网（屋里的「电脑」：RSS、小说阅读带书签、只读、站点白名单、防 SSRF），放在自由活动里用；M8 设置界面。
5. 画面的剩余部分（可选）：墙、地板、篱笆还是代码画的；LPC 里有木地板 / 墙面素材可以换。
6. 每日 token 预算：用户决定先不做。

## 5. 用户做过的决定（备查）

- 工具名：`house_render`（看画面）、`end_free_time`（结束自由活动）；`house_surroundings` 工具已删，看看四周用脚本里的 `surroundings()`
  （`look()` 完全去掉，写了会提示用 `surroundings()`）。
- 写错动作名：整段不执行，提示正确写法，不自动替换。
- 不设精力，只有饥饿；目录里可以订即食食品。
- 作息：早上 7:30–8:30 随机开始，40 分钟；中午、傍晚同样；深夜一半日子有。开始和结束直接告诉她，不做世界观包装。
- 动作时长：做饭要分「必须守着」和「下锅后能走开」；一圈想做的事约 20 分钟；`tidy` 每处 5–15 秒；其他简单动作现在的时长可以。
- 菜谱：十多道地道中餐（必须有白米饭、荷包蛋、红烧肉），原料自己种或买；物价对齐人民币。
- 画面：用 LPC 素材（Kenney 的不够好认）；订货目录的家具按 LPC 有的来；去掉鲸鳍耳。
- 猫：可以陪玩、玩具可以买、随机结果和房间联动、闯的祸要能收拾。

## 6. 容器里的测试环境（下次如果还在同一个环境）

用户要求**保留**这些，不要删。scratchpad 路径：`/tmp/claude-0/-home-user-LittleHouseOfDeepSeek/<session>/scratchpad/`（新会话会不同）。

- `dsh/`：`npm install @deepseek-ai/dsh@0.2.2-rc.2`，命令 `npx dsh`（要 `DEEPSEEK_API_KEY=proxy-injected`，真 key 由代理注入）。
- `venv/`：带 pygame-ce 和 zstandard 的 Python。
- `dsh-home/`：测试用 `DSH_HOME`，profile `lhtest`，插件 junction 指向仓库的 `plugin/`（`scripts/install.py --profile lhtest`）。
- `overlay.yml`：覆盖 `little-house` 行（`stateDir: <scratch>/lh-state`、`house.python` 指向 venv、`wake.firstWakeDelaySeconds: 5`、
  `wake.testMinutes`）= 启动 5 秒后来一段临时自由活动。启动：
  `DEEPSEEK_API_KEY=proxy-injected DSH_HOME=<scratch>/dsh-home npx dsh --profile lhtest --patch <scratch>/overlay.yml --no-open --port 3099`
  （launcher 参数在 app 参数前面）。等 `plugin.log` 出现 `over in session` 就是这段结束了。
- `tools/fulllog.py <dsh-home> <开场消息里的一段文字，如 "临时，07:04"> <输出.md> <events.jsonl>`：导出完整伪代码日志给用户。
  `tools/readsession.py`、`tools/calls.py`：快速看会话。`tools/shot.py`：渲染一张摆满东西的测试画面。
- `lpc-dl/`、`lpc-dl2/`、`ulpc/`：下载的 LPC 原始包（已拷进仓库的只是用到的那些）。
- **网络**：云环境「LittleHouseOfDeepSeek」的允许列表里有 `opengameart.org`、`lpc.opengameart.org`、`kenney.nl`（kenney 返回 403）；
  GitHub 的 `raw.githubusercontent.com` 和 `media.githubusercontent.com`（LFS）可以下载公开仓库的文件。
- **DeepSeek API key**：保存在云环境「LittleHouseOfDeepSeek」的网络密钥里（由代理注入，从未写进任何文件）。2026-11-14 换过一次。
  失效的话用 `request_credential` 重新申请，不要让用户把 key 贴进聊天。

## 7. 仓库地图

```
plugin/            DSH bundle：index.js（服务、作息、自由活动窗口）、agent-scope.js（规则 + 工具）、diary-scope.js、
                   lib/（wake.js 作息纯函数、slots.js 默认时段、house-process.js、diary.js）、persona/、cordis.patch.yml、test/
house/littlehouse/ 小屋：content（内容表，一切数值）/ world（状态、日常、乱子、灶台）/ actions（动作、提示、菜单）/
                   tasks（实时执行器）/ script（解析、结果格式）/ server（HTTP）/ scene（布局）/ anim（此刻姿态）/
                   render（渲染）/ sprites（LPC 切图、拼她）/ display（窗口）/ repl / clock / assets/lpc（素材 + CREDITS.md）
house/tests/       unittest（world / tasks / anim / render / consistency）
scripts/install.py 装进 / 卸出 DSH profile（junction + package.json，带备份）
view.bat           只读窗口
docs/              INSTALL-WINDOWS / PROTOCOL / ROADMAP / HANDOFF + 截图
```
