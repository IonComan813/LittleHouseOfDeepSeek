# 交接文档（给下一个接手的开发会话）

> 写于 2026-11-13，M2.5 完成时。先读这份，再读 `README.md`（架构图）、`docs/ROADMAP.md`（每步的实测记录）、
> `docs/PROTOCOL.md`（伪代码、HTTP 接口、文件）。

## 1. 用户与环境

- 用户用中文交流；**改动后请用中文汇报**，报告要具体（做了什么、实测结果、用户要做什么）。
- 运行环境：**Windows Server 2025 Datacenter 24H2**，用户通过 mstsc（RDP）登录桌面；**DSH 桌面版 0.2.2-rc.2**，作为应用运行（不是服务）。
  profile 多半叫 `desktop`（安装脚本优先选它）。用户的 profile 里还装了别的插件。
- **NapCat** 已经在本机登录 QQ 并能收发（M5 用）。
- 模型：**DeepSeek-V4.1-Flash**（API id `deepseek-flash`，支持图片输入；`deepseek-v4-pro` 只支持文本）。
- 用户希望：轻量、为自己定制；服务器算力不富裕（所以画面默认只在需要时渲染一帧）；
  时间与现实 1:1；画面**只读**（人和 DS 都不用键鼠操作游戏，DS 用伪代码）；暖色田园风；
  她的形象是**蓝发鲸鱼少女**（呆毛、鲸鳍耳、鲸尾、蓝白女仆装、围裙上的小鲸鱼）。
- 用户可能会离开一段时间，喜欢「能做的先做完再汇报」，不喜欢需要一直守着确认的操作。

## 2. 当前状态（全部已推送到 `claude/laughing-turing-ush012`）

| 里程碑 | 内容 |
| --- | --- |
| M0 | DSH 插件骨架、随机唤醒进独立「小屋生活」会话、工具白名单、Python 小屋进程、伪代码、安装脚本 |
| M1 | 内容表；饥饿 / 精力；做饭、打扫、摆家具、种菜、钓鱼、捡贝壳、收藏架、猫 |
| M1.5 | 潮汐湾 / 开拓署 / 快递员阿陆的设定；贝币经济（每周补给、订货、寄售箱）；大量随机性 |
| 日记 | `diary_write` / `diary_read`，DS 自己决定写不写；每天一个 Markdown |
| M2 / M2.5 | 程序化像素画（pygame-ce）；`house_glance` 给她看一帧；`view.bat` 只读动画窗口（同一进程）；动作节拍与走路 / 特效动画 |

测试：`house/` 59 个（`python -m unittest discover -s tests`，无 pygame 时跳过 3 个），`plugin/` 10 个（`npm test`）。
每个里程碑都在容器里用真实 DSH 0.2.2-rc.2 + deepseek-flash 跑过端到端；
**M2.5 的动画窗口只在容器里用 SDL dummy 驱动验证过，还没在用户的 Windows 桌面上看过真窗口**。

## 3. 关键设计与踩过的坑（改代码前务必看）

DSH（cordis 插件框架）相关：

- **会话创建**照抄 dsh-schedule：`ctx.get('sessionController').create({ sessionId, cwd, agentPreset })`
  → `resolveAgent(sessionId)`（返回 `{agent}` 或 `{error}`）→ `agent.followup(createUserMessage({content, source: {kind: 'little-house'}}))`
  → `ctx.sessions.flush(agent.session)`。标题用 `ctx.get('sessionTitle')?.rename(session, title)`。
- **preset 子插件注册的工具，在 agent 看来是「继承的」**：`tools.restrict({ allow: [] })` 会连自己的工具一起藏掉。
  现在的做法：`restrict({ deny: <挂载时全部全局工具名> })` + `tools.guard()` 只放行 `OWN_TOOLS`（`plugin/agent-scope.js`）。
  新增工具时**必须把名字加进 `OWN_TOOLS`**，否则会被守卫拒绝执行。
- `systemPrompt.suppressRuntimeContext()` 去掉编程向上下文；`working-directory` 一段是 required，去不掉（无害）。
- 生活会话的系统提示词用 `complete: true` 的 section（人设 + 规则）。**QQ 会话不能这样做**：complete 会把 dsh-onebot 的平台提示词也吞掉。
- `exec.concludeTurn()`（`house_rest` 里）直接结束这一轮。
- **`defineTool` 的输出 schema 顶层不能写 `required`**；在 `ctx.inject(...)` 回调里抛的错会被**静默吞掉**——所以插件把日志写到
  `~/.dsh/little-house/plugin.log`。调试先看这个文件。
- 工具结果里返回图片：`ctx.inject(['attachments'], ...)`，`attachments.saveImage({data, mediaType, name})`，再返回
  `{ type: 'image', attachment: ref }`（见 `house_glance`）。
- 插件引用宿主包（`@deepseek-ai/dsh-tools`、`dsh-llm`、`cordis`、`schemastery`）靠 `peerDependencies` + DSH 的 peer 拦截；
  插件目录没有 `node_modules` 也能跑。安装脚本只建 junction + 改 profile 的 `package.json`（和 surfcore 一样）。
- 改 profile 的 `cordis.patch.yml` 会**热重载**插件（小屋进程跟着重启、首次唤醒倒计时重来）；改插件 JS 要重启 DSH。
  新 profile 的 patch 文件里常有一行 `[]`，**直接追加会让 DSH 启动失败**，要先删掉。
- 会话日志是多帧 zstd（`~/.dsh/sessions/<cwd>/<id>/session.v4.jsonl.zstd`），要跨帧解压；DSH 运行时文件可能还没刷全。

小屋相关：

- 存档 `world/world.json` 有版本号（当前 v3），`World.load_json` 里有 v1→v2→v3 迁移。**改存档结构要加迁移并写测试。**
- 时间：`Clock`（可偏移 / 加速，测试里用 `clock.advance`）；`tick()` 按 ≤1 小时步进补算，最多 14 天。
- 「世界自己发生的事」用 `world.log(..., actor="world")`，会进 `/news`，唤醒时告诉她「你不在的时候」。
  她自己的动作是 `actor="resident"`，唤醒时变成「上次醒着的时候，你……」。
- 世界描述里提到的地方 / 东西必须真的能去 / 能用（M0 时写了「院子尽头是沙滩」却没有沙滩，模型连续失败）。
- **画面和文字必须描述同一个世界（用户明确要求）。** 文字说「格子地毯」，画面就不能画成菱形拼接；画面里画出来的东西，
  文字里也要有，最好还能 `examine`。唯一的来源是 `content.py` 的 `APPEARANCE` 表：`render.py` 按它画，
  `examine`、房间描述、家具物品的描述都用它。改画面时同步改这张表；新画的东西加进表里
  （`tests/test_consistency.py` 会检查「画了但没描述」）。画面上的陈设（冰箱、水槽、衣柜、树）是 `C.SCENERY` 里的真实物件。
- 很多动作不带参数时作用于「这里所有的」（`water()`、`pick()`、`harvest()`、`display()`），这对省 token 很重要。
- 画面：`render.render(world, t, pose)`；不传 pose 时用 `anim.snapshot_pose`（定格最近的动作）。
  窗口在 `display.py`，跑在小屋进程**主线程**（HTTP 在后台线程），开关走 `POST /window`。渲染时持有 `house.lock`。
  **不要在小屋进程里设置 `SDL_VIDEODRIVER=dummy`**（会让后来打开的真窗口失效）；离屏渲染本来就不需要显示驱动。
- 新动作要在 `anim.EFFECTS` 里配一个特效名（可选），站位规则在 `actions.ACTION_SPOTS` / `world.stand_at`。

## 4. 下一步（按用户意图排序）

1. **请用户在 Windows 上验证 M2.5**：`git pull`、`pip install pygame-ce`、重启 DSH、双击 `view.bat`，看窗口是否正常、角色是否会走。
   可能的问题：DSH 拉起的子进程能否在 RDP 桌面上开窗口（应当可以，DSH 作为应用运行）；`python` 是否是装了 pygame-ce 的那个。
2. **M5 QQ（复用 dsh-onebot）**——用户已同意复用，两种方式都可以：
   - 方案 A（先试）：dsh-onebot 原样安装，它的 `agentPreset` 配置指向我们新增的 `little-house-qq` preset：
     `dsh-persona` 行（同一份人设，**不要 complete**）、`dsh-little-house/diary`（`config.source: QQ`）、一个注入「小屋近况 + 最近日记」的
     system prompt section、可选只读的 `house_look`。主动发消息时直接调 NapCat OneBot HTTP。
     关键待验证：我们往 dsh-onebot 的那个 QQ 会话里 `followup` 一条「你想主动说点什么」时，回复会不会经 dsh-onebot 发回 QQ；
     不会的话主动消息和后续对话会断开上下文。
   - 方案 B：把 dsh-onebot 的 connection / cq / inbound / outbound 核心（BSD-3，保留声明）搬进本插件。
   - **夜间（0–8 点）**：QQ 消息按概率决定是否送达模型；不送达就直接回一句「她在睡觉」；送达的话由模型决定回不回。
   - 主动分享要有：安静时段、每日上限、白名单。
3. **M4 记忆**：小屋和 QQ **共用一份**记忆。原料：`world/events.jsonl`（事件）+ `diary/*.md`（她自己写的）+ QQ 会话。
   思路：每天（或每次唤醒结束后）让模型把当天总结成一段；再维护一张会衰减的长期记忆卡（参考 surfcore 的 memory-card 设计），
   注入生活会话和 QQ 会话；`diary_read` 已可按需翻看。
4. M3：**动作时长与任务队列（见 4.5，用户明确要求）**；**三餐作息表（见 4.6，用户在考虑）**；每日 token 预算（80% 提醒 / 100% 停），可以从会话日志的 `assistant/message.data.usage` 累计。
5. M6 上网（屋里的「电脑」：RSS、小说阅读带书签、只读、站点白名单、防 SSRF）；M8 设置界面。

## 4.5 用户的要求：动作要花时间（把「回放」变成真正的实时）

**现状与问题。** 现在伪代码已经是直接发给 pygame 所在的那个小屋进程执行的；但每个动作在世界逻辑里都是**瞬间完成**的：
一段 `goto(沙滩); fish()` 一到达，世界状态当场就变成「她在沙滩、鱼已钓到」，窗口里的走路和动作只能在事后按节拍追着播放
（这就是 M2.5 文档里说的「回放」）。用户希望画面是**真正实时**的：她发出指令后，角色在世界里真的花时间去做，画面画的就是此刻的真实状态。

**用户的要求（原话要点）：做操作要有时间要求，比如做饭要五分钟，此期间角色可以去做别的事。**

建议的实现方向（M3 的一部分，改动较大，先和用户确认细节）：

1. **动作有时长。** 在 `content.py` 里给动作配时长，例如（游戏时间与现实 1:1，可再和用户商量）：

   | 动作 | 时长 | 她是否被占用 |
   | --- | --- | --- |
   | 走路 | 按路程，约 1 秒 / 格 | 占用 |
   | 浇水、捡东西、摆东西、开邮箱 / 包裹 | 10–30 秒 | 占用 |
   | 打扫一个房间 | 3 分钟 | 占用 |
   | 做饭 | **5 分钟**（煮着的时候不用守着） | 只占用开头 / 结尾，中间她可以去做别的 |
   | 钓鱼一次 | 1–3 分钟（随机） | 占用 |
   | 小睡 rest | 20 分钟 | 占用 |
   | 播种、收获 | 1 分钟 | 占用 |

2. **两类任务。**
   - *占用型*：她本人在做，做完才能做下一件（走路、打扫、钓鱼）。
   - *后台型*：开始后自己进行，到点产生结果（锅里的菜、以后的洗衣机、烤箱……）。做饭 = 「开火」（几秒）+ 5 分钟后菜好了
     （世界事件「锅里的番茄炒蛋好了」；放太久可能会糊——可以作为随机性的一部分）。期间她可以去院子浇水。
3. **伪代码语义要改。** `house_do` 不再一次性执行完，而是把动作放进她的**任务队列**，由小屋的模拟线程按时间推进：
   - 简单做法：`house_do` 阻塞到队列里的占用型动作做完再返回结果（几十秒以内）；超过上限（比如 2 分钟）就先返回
     「正在做……，预计 X 分钟后完成」，她可以 `house_look` 查看进度，或者用一个 `wait(分钟)` 动作等待。
   - 后台任务完成时写 `actor="world"` 的事件（进 `/news`），下次醒来或下一次 `look()` 时她会知道。
   - 唤醒的行动次数预算、`house_rest` 结束会话，都要考虑「还有后台任务在跑」的情况（比如做饭时去休息 → 菜会糊）。
4. **画面随之变成实时。** 有了任务队列，渲染器直接画「她此刻在任务中的位置和动作」：走路就是真实的位置插值，
   做饭就是锅在冒热气、她在旁边；`anim.Animator` 的回放和积压加速可以去掉，`snapshot_pose` 改为读当前任务。
   静态「瞥一眼」也就自然是真实的这一刻。
5. **资源。** 默认仍然不开窗口；模拟线程只是推进时间（很便宜）。窗口打开时才持续渲染。
   她的提示词里已经写了「本机算力有限，house_glance 偶尔看一眼即可」。

## 4.6 用户在考虑：每天的活动时段（作息）

**用户的想法：** 限制她每个真实日历日自由活动的次数。早、中、晚三次（对应三餐）就不错，可能再加一次深夜。
每次给足活动时间，**半小时或一小时**。唤醒时间可以固定，也可以在给定区间里投骰子。

**现状：** 每隔 90–240 分钟随机唤醒一次，安静时段 00:30–08:00，每天最多 8 次。每次唤醒其实是一阵连续的工具调用：
几十秒就做完一串动作，然后 `house_rest`，并不占用真实的半小时。

建议做成可配置的「作息表」，替换现在的随机间隔：

```yaml
wake:
  slots:                      # 每个时段里随机挑一个开始时间
    - { name: 早上, from: '07:30', to: '08:30', minutes: 45 }
    - { name: 中午, from: '11:30', to: '12:30', minutes: 45 }
    - { name: 傍晚, from: '17:30', to: '18:30', minutes: 60 }
    - { name: 深夜, from: '22:00', to: '23:00', minutes: 30, chance: 0.5 }   # 不一定每天都有
```

- 唤醒消息里告诉她这是哪一段（「早上醒来」「午饭时间」……），三餐自然对应做饭、吃饭。
- **「每次半小时到一小时」要和 4.5 的动作时长一起做才有意义。** 动作有了真实时长以后，一次活动才会真的持续那么久。
  做法：活动窗口打开期间，她的队列空了或者在等后台任务时，插件按需（比如每 5–10 分钟，或后台任务完成时）
  再 `followup` 一条「过了一会儿……（现在的情况）」，直到窗口结束或她主动 `house_rest`。
  这会增加 token：一天 3–4 个窗口 × 每窗口几次跟进，按现在每轮约 1–2 万 token（八成缓存）估算，
  需要和每日 token 预算一起设计。
- 骰子与固定时间都支持：`from == to` 就是固定时间。

**活动时段以外怎么解释（世界观）。** 目前的做法：
- 唤醒消息是「（你醒了过来……）」，结束工具叫 `house_rest`（「去休息」），所以两次活动之间她在**打盹 / 休息**。
- 0–8 点被当作**睡觉**（精力每小时 +12；画面里她躺在床上），白天两次活动之间精力每小时 −3、饥饿每小时 +5。
- 世界照常运转：植物会干、团子会饿、阿陆照常送货收货；这些变化在下次醒来时作为「你不在的时候」告诉她。

改成三餐作息后，建议把活动之间的时间解释为「**过着平淡的日常**」，而不只是打盹：
- 让模拟替她处理最基本的维持（比如两次活动之间不会饿到极限，或者自动吃掉一点存粮），避免她每次醒来都在补救；
- 画面在活动时段以外画她在做「待机」的事（窗边发呆、沙发上看书、床上睡觉），按时间段挑一个；
- 「上次醒着的时候，你……」照旧来自事件日志，日记照旧由她自己决定写不写。

这一块要先和用户确认：几个时段、每段多长、时段外她的状态，以及每日 token 上限。

## 5. 容器里的测试环境（下次如果还在同一个环境）

用户要求**保留**这些，不要删：

- scratchpad：`/tmp/claude-0/-home-user-LittleHouseOfDeepSeek/<session>/scratchpad/`（新会话路径会不同，找 `dsh/`、`venv/`、`dsh-home/`）
  - `dsh/`：`npm install @deepseek-ai/dsh@0.2.2-rc.2`，命令 `npx dsh`
  - `venv/`：带 pygame-ce 的 Python
  - `dsh-home/`：测试用 `DSH_HOME`，profile `lhtest`（手动安装方式）和 `web`（`dsh plugin add` 方式）
  - `pylib/`：`zstandard`，用于解压会话日志
- 启动方式：`DSH_HOME=<scratch>/dsh-home npx dsh --profile lhtest --patch <overlay.yml> --no-open --port 3099`
  （launcher 参数要在 app 参数前面）。overlay 里覆盖 `little-house` 行（`stateDir`、`house.python` 指向 venv、`firstWakeDelaySeconds: 5`）。
- **DeepSeek API key 已不再使用**：它曾保存在云环境「LittleHouseOfDeepSeek」的网络密钥里（由代理注入，从未写进任何文件）。
  用户需要的话可以在环境设置里删除那条网络密钥，并在 DeepSeek 后台作废旧 key。新会话需要实测时请用 `request_credential` 重新申请，
  不要让用户把 key 贴进聊天。

## 6. 仓库地图

```
plugin/            DSH bundle（index.js 服务、agent-scope.js、diary-scope.js、lib/、persona/、cordis.patch.yml、test/）
house/littlehouse/ 小屋（content / world / actions / script / server / scene / anim / render / display / repl / clock）
house/tests/       unittest
scripts/install.py 装进 / 卸出 DSH profile（junction + package.json，带备份）
view.bat           只读窗口
docs/              INSTALL-WINDOWS / PROTOCOL / ROADMAP / HANDOFF + 截图
```
