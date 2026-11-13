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
4. M3 收尾：每日 token 预算（80% 提醒 / 100% 停）。可以从会话日志的 `assistant/message.data.usage` 累计。
5. M6 上网（屋里的「电脑」：RSS、小说阅读带书签、只读、站点白名单、防 SSRF）；M8 设置界面。

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
