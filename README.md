# Little House of DeepSeek

让一个 [DeepSeek Harness（DSH）](https://github.com/deepseek-ai/deepseek-harness) agent **住进一间海边小屋**：
她会在随机的时间醒来，在屋子里和院子里自由活动——浇花、去沙滩捡贝壳、自言自语——然后写一句小记，回去休息。

> 当前进度：**M0（技术验证）已完成**。小屋还是纯文本的（没有画面），动作也只有几个。
> 完整路线见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 它由什么组成

```
┌──────────── DSH（桌面版 / Web） ────────────┐
│  dsh-little-house 插件（plugin/，纯 JS）      │
│   · 随机唤醒：安静时段、每日上限、每次行动上限  │
│   · 「小屋生活」会话：独立 agent preset，        │
│     只有 house_* 三个工具，没有 shell/文件/网络  │
│   · 人设注入（persona/*.md）                   │
└───────────────┬───────────────────────────┘
                │ HTTP（只监听 127.0.0.1，带令牌）
┌───────────────▼───────────────────────────┐
│  小屋进程（house/，Python 标准库）              │
│   · 世界模型：房间、物件、时间（与现实 1:1）、天气 │
│   · 伪代码解释器：goto(沙滩); pick(shell#1)     │
│   · 存档 + 事件日志（以后喂给记忆系统）           │
└───────────────────────────────────────────┘
```

- 每次醒来都发生在 DSH 里一个名为 **「小屋生活 · 日期」** 的会话中，你可以在 DSH 的会话列表里直接看她在做什么。
- 一次唤醒大约消耗 1.2 万 token，其中约八成是缓存命中（DeepSeek-V4.1-Flash 实测）。

## 安装（Windows）

见 [docs/INSTALL-WINDOWS.md](docs/INSTALL-WINDOWS.md)。简要步骤：

```powershell
git clone https://github.com/IonComan813/LittleHouseOfDeepSeek.git
cd LittleHouseOfDeepSeek
python scripts\install.py
```

然后完全退出并重新打开 DSH。

## 自己去小屋里看看

不用 DSH 也能在终端里"过日子"（DSH 在运行时，它会自动连到同一个小屋）：

```powershell
cd house
python -m littlehouse --repl
```

伪代码的写法见 [docs/PROTOCOL.md](docs/PROTOCOL.md)。

## 目录

| 路径 | 内容 |
| --- | --- |
| `plugin/` | DSH 插件（bundle）：`index.js` 唤醒与进程管理，`agent-scope.js` 生活会话的工具和提示词 |
| `plugin/persona/` | 人设文件（Markdown），可以自己写一份并在配置里指向它 |
| `house/` | 小屋世界（Python），`python -m unittest discover -s tests` 跑测试 |
| `scripts/install.py` | 把插件装进 DSH profile / 卸载 |
| `docs/` | 安装、协议、路线图 |

## 开发

```bash
cd house && python -m unittest discover -s tests   # 世界与伪代码
cd plugin && npm test                               # 唤醒调度
```

## 许可

Apache-2.0。参考了 [surfcore](https://github.com/Mieksido/surfcore)（MIT）和
[dsh-onebot](https://github.com/mario841859784/dsh-onebot)（BSD-3-Clause）的设计，见 [NOTICE](NOTICE)。
