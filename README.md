# Little House of DeepSeek

让一个 [DeepSeek Harness（DSH）](https://github.com/deepseek-ai/deepseek-harness) agent **住进一间海边小屋**：
她会在随机的时间醒来，看看自己不在时发生了什么，然后自由安排——做饭、种菜、钓鱼、捡贝壳、
把收获卖给开拓署换贝币、买家具布置房间、陪猫——想写日记的时候就写几句，然后回去休息。

![白天的小屋](docs/screenshot-day.png)

<details><summary>晚上 / 走路动画</summary>

![晚上的小屋](docs/screenshot-night.png)
![从客厅走到沙滩](docs/animation-strip.png)

</details>

> 当前进度：**M0 → M2.5 完成**（世界、经济、日记、会动的只读像素画面）。下一步是记忆（M4）和 QQ（M5）。
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
│   · 随机唤醒：安静时段、每日上限；每天一个「小屋生活 · 日期」会话               │
│     （sessionController.create + resolveAgent + agent.followup，同 dsh-schedule）│
│   · 唤醒消息 = 离开多久 + 「上次醒着的时候你…」+ 最近一段日记                    │
│              + 「你不在的时候…」+ look                                       │
│   · plugin.log                                                              │
│                                                                            │
│  preset `little-house`（cordis.patch.yml）— 生活会话只挂这些行：             │
│   · agent-scope.js：人设 + 小屋规则（complete 系统提示词）、house_look /       │
│     house_do / house_rest / house_glance；全局工具 deny + tools.guard 白名单   │
│   · diary-scope.js：diary_write / diary_read（独立行，M5 直接挂进 QQ preset）  │
│   · compaction                                                              │
└───────────────┬────────────────────────────────────────────────────────────┘
                │ HTTP 127.0.0.1 + X-House-Token
                │ /look /do /news /events /state /screenshot /window /shutdown
┌───────────────▼────────────────────────────────────────────────────────────┐
│ 小屋进程（house/，Python ≥3.10；世界只用标准库，画面用 pygame-ce）            │
│  content.py  内容表：地点、物品、作物、菜谱、鱼、天气、价格、信、随机事件         │
│  world.py    世界状态与被动模拟（按小时步进补算，最多 14 天）、存档 v3 + 迁移     │
│  actions.py  伪代码动作（做饭、种菜、钓鱼、买卖、猫……）+ 每个动作的动画节拍      │
│  script.py   伪代码解析与执行（不 eval；遇错即停）                              │
│  server.py   HTTP 线程 + 主线程上的窗口；发现文件 world/house.json              │
│  scene.py    瓦片布局、门口路点、站位      anim.py  节拍 → 姿态（静态 / 动画）   │
│  render.py   程序化像素画渲染器          display.py 只在打开时运行的只读窗口       │
└────────────────────────────────────────────────────────────────────────────┘
```

要点：

- **她只能用伪代码生活。** 生活会话里看不到 shell、文件、网络等任何 DSH 自带工具（fail-closed），
  只有 `house_*` 和 `diary_*`。伪代码一次可以写多步，省 token：`goto(庭院); open(包裹); plant(萝卜种子); water()`。
- **世界会自己运转。** 时间与现实 1:1；她会饿会累，植物会干，房间会落灰，团子会饿、脾气每天不同，
  开拓署每周一送补给，快递员阿陆每天送货、傍晚收走寄售箱。很多结果带随机性
  （打扫时的发现、做饭失手、收成浮动、每天的小事件）。
- **画面是只读的，渲染只有一个进程。** `house_glance` 只渲染一帧给她看（约 600 token，定格最近的动作）；
  `view.bat` 让同一个小屋进程打开动画窗口，关掉就停止渲染。
- **日记由她自己决定。** 每天一个 Markdown 文件（`~/.dsh/little-house/diary/`），标注来源（小屋 / 以后的 QQ）。
- **成本。** DeepSeek-V4.1-Flash 实测一次唤醒约 1.2～2 万 token，约八成是缓存命中。

更多：[伪代码与接口](docs/PROTOCOL.md) · [路线图与实测记录](docs/ROADMAP.md) · [交接文档](docs/HANDOFF.md)

## 自己去小屋里看看

```powershell
view.bat                                   # 只读动画窗口
cd house; python -m littlehouse --repl     # 在终端里用伪代码"过日子"（DSH 开着时自动连到同一个小屋）
```

## 开发

```bash
cd house && python -m unittest discover -s tests   # 59 个（无 pygame 时跳过 3 个渲染测试）
cd plugin && npm test                               # 唤醒调度、日记
```

## 许可

Apache-2.0。设计参考了 [surfcore](https://github.com/Mieksido/surfcore)（MIT）和
[dsh-onebot](https://github.com/mario841859784/dsh-onebot)（BSD-3-Clause），见 [NOTICE](NOTICE)。
画面全部由代码绘制，没有使用第三方美术素材。
