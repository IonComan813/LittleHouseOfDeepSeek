# Little House of DeepSeek

让一个 [DeepSeek Harness（DSH）](https://github.com/deepseek-ai/deepseek-harness) agent **住进一间海边小屋**：
每天早、中、晚和睡前各有一段四十分钟的自由活动时间，由她自己安排——做饭、种菜、钓鱼、捡贝壳、
把收获卖给开拓署换贝币、买家具布置房间、陪猫——每段结束前写几句日记。做事要花真实的时间：
炖一锅汤要几分钟，下锅后可以先去院子里浇水。自由活动以外，她自己过着平淡的日常。

![白天的小屋](docs/screenshot-day.png)

<details><summary>晚上 / 走路动画</summary>

![晚上的小屋](docs/screenshot-night.png)
![从客厅走到沙滩](docs/animation-strip.png)

</details>

> 当前进度：**M0 → M5 完成**（世界、经济、日记、会动的只读像素画面、动作花真实时间、每日作息、记忆、手机 QQ）。下一步是上网（M6）。
> 路线图见 [docs/ROADMAP.md](docs/ROADMAP.md)；接手开发请先读 [docs/HANDOFF.md](docs/HANDOFF.md)。

## 安装（Windows）

见 [docs/INSTALL-WINDOWS.md](docs/INSTALL-WINDOWS.md)。简要：

```powershell
git clone https://github.com/IonComan813/LittleHouseOfDeepSeek.git
cd LittleHouseOfDeepSeek
python -m pip install pygame-ce
python scripts\install.py
```

然后完全退出并重新打开 DSH。想看画面：双击 `view.bat`（只读，关掉不影响她）。

## 技术概览

```
┌──────────────────────── DSH（桌面版 / Web，Node） ────────────────────────┐
│ dsh-little-house（plugin/，纯 ESM JS，无构建步骤，作为 bundle 装进 profile）  │
│                                                                            │
│  index.js — 宿主级服务 `littleHouse`                                         │
│   · 拉起 / 连接小屋进程（发现文件 + 令牌），挂了自动重启，DSH 退出时让它存档退出 │
│   · 每天一个「小屋生活 · 日期」会话（0 点换天）：几段自由活动 + 手机 QQ +       │
│     睡前整理日记；第一条消息（早上醒来）开头是完整人设和她的记忆               │
│   · 作息：23:30–24:00 睡觉，第一段自由活动开始时醒来；睡着时 QQ 消息挡掉       │
│   · 作息表：每天几段自由活动（时段内随机开始，各 40 分钟），到点结束；          │
│     开始消息 = 时段 +「刚才在…」+「这段时间里…」+ look（agent.steer 送进去） │
│   · QQ（qq.js）：直连 NapCat（OneBot 11 正向 WebSocket）；私聊消息作为        │
│     「手机响了」送进当天的会话；图片能看，语音 / 文件在桥这里挡掉；夜里按概率叫醒 │
│   · 记忆：换天后开「记忆整理」会话（不带人设、没有工具），日记 + QQ → JSON →   │
│     memory.json（会淡忘，lib/memory.js）                                     │
│   · plugin.log                                                              │
│                                                                            │
│  preset `little-house`（cordis.patch.yml）— 生活会话只挂这些行：             │
│   · agent-scope.js：简短人设 + 小屋规则（complete 系统提示词）、house_do（自由  │
│     活动以外只能看；主人请她做事时接管角色）/ end_free_time /                 │
│     end_of_current_operation / house_render / phone_message；                │
│     全局工具 deny + tools.guard 白名单                                        │
│   · diary-scope.js：diary_write / diary_edit / diary_read（醒着时随时可用）     │
│   · compaction                                                              │
└───────────────┬────────────────────────────────────────────────────────────┘
                │ HTTP 127.0.0.1 + X-House-Token
                │ /look /do /news /events /state /screenshot /window /shutdown
┌───────────────▼────────────────────────────────────────────────────────────┐
│ 小屋进程（house/，Python ≥3.10；世界只用标准库，画面用 pygame-ce）            │
│  tasks.py    实时执行器：动作按游戏时钟一步步播放（走路、做饭……），可打断       │
│  content.py  内容表：地点、物品、作物、菜谱、鱼、天气、价格、信、随机事件         │
│  world.py    世界状态与被动模拟（按小时步进补算，最多 14 天）、存档 v3 + 迁移     │
│  actions.py  伪代码动作（做饭、种菜、钓鱼、买卖、猫……）+ 每个动作的动画节拍      │
│  script.py   伪代码解析与执行（不 eval；遇错即停）                              │
│  server.py   HTTP 线程 + 主线程上的窗口；发现文件 world/house.json              │
│  scene.py    瓦片布局、门口路点、站位      anim.py  此刻的姿态（走路 / 做事 / 日常）│
│  render.py   像素画渲染器（LPC 素材 + 代码绘制） display.py 只读窗口               │
└────────────────────────────────────────────────────────────────────────────┘
```

要点：

- **她只能用伪代码生活。** 生活会话里看不到 shell、文件、网络等任何 DSH 自带工具（fail-closed），
  只有 `house_*` 和 `diary_*`。伪代码一次可以写多步，省 token：`goto(庭院); open(包裹); plant(萝卜种子); water()`。
- **做事要花时间。** 走路按路程（和画面上一样），炒菜要一直守着，炖汤先忙一分半钟、再自己炖三分钟，
  打扫一半走开下次接着扫；`house_do` 等这一串做完才给出结果。一圈想做的事大约二十分钟。
- **世界会自己运转。** 时间与现实 1:1；她会饿会累，植物会干，房间会落灰，团子会饿、脾气每天不同，
  开拓署每周一送补给，快递员阿陆每天送货、傍晚收走寄售箱。很多结果带随机性
  （打扫时的发现、做饭失手、收成浮动、每天的小事件）。
- **画面是只读的，渲染只有一个进程。** 画的就是此刻的真实状态（走到半路、在灶台边、窝在沙发上看书）。
  `house_render` 只渲染一帧给她看（约 600 token）；
  `view.bat` 让同一个小屋进程打开动画窗口，关掉就停止渲染。
- **日记。** 醒着的时候随时能写、改、翻以前的；结束自由活动时会问她要不要写。每天一个 Markdown 文件（`~/.dsh/little-house/diary/`），每段标注时间和时段。
- **夜空。** 天黑后可以在院子或沙滩看星星：月相按真实日期算，偶尔有流星（真实的流星雨之夜会有很多），夏天有萤火虫和夜光藻。
- **记忆。** 每天换天后，一个不带人设的会话把前一天的会话全文和日记整理成「最近的日子 / 想做的事 / 记得的事（不能忘的） / 认识的人」，
  第二天的会话开头给她看；越久越模糊，想做的事忘得更快，很重要的事不会忘。
- **手机和 QQ。** 她背包里一直有一部手机：她醒着时你随时可以用 QQ 私聊她，她用手机回你（同一天的聊天和小屋生活在一个会话里）；
  你的朋友也可以私聊她。不在自由活动时，你（或朋友）请她在屋里做什么，她会接过角色去做，做完交还给日常。她看得懂图片，会用 QQ 表情，能拍小屋的照片发给你；
  睡着时消息不会打扰她。自由活动写完日记后，遇到有趣的事她可能主动给你发消息。
- **成本。** DeepSeek-V4.1-Flash 实测一次唤醒约 1.2～2 万 token，约八成是缓存命中。

更多：[伪代码与接口](docs/PROTOCOL.md) · [路线图与实测记录](docs/ROADMAP.md) · [交接文档](docs/HANDOFF.md)

## 自己去小屋里看看

```powershell
view.bat                                   # 只读动画窗口
cd house; python -m littlehouse --repl     # 在终端里用伪代码"过日子"（DSH 开着时自动连到同一个小屋）
```

## 开发

```bash
cd house && python -m unittest discover -s tests   # 91 个（无 pygame 时跳过渲染测试）
cd plugin && npm test                               # 作息表、唤醒消息、日记、QQ 消息格式、WebSocket
```

## 许可

Apache-2.0。设计参考了 [surfcore](https://github.com/Mieksido/surfcore)（MIT）和
[dsh-onebot](https://github.com/mario841859784/dsh-onebot)（BSD-3-Clause），见 [NOTICE](NOTICE)。
画面用的是 OpenGameArt 上的 LPC 像素素材（家具、灶台、草地、沙滩、海、树、礁石、作物、团子；她由 LPC 角色生成器的图层拼成，蓝发、呆毛、鲸尾和围裙上的小鲸鱼由代码画上去）。这些素材是 CC-BY-SA 3.0 / GPL 3.0 等许可，不属于 Apache-2.0，署名见 [house/littlehouse/assets/lpc/CREDITS.md](house/littlehouse/assets/lpc/CREDITS.md)；墙、地板、冰箱、邮箱和菠菜 / 葱 / 南瓜 / 草莓等由代码绘制。
