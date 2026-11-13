# 小屋协议

## 伪代码

agent 通过 `house_do` 工具提交一段伪代码，人类可以在 `python -m littlehouse --repl` 里用同样的写法。

```
goto(沙滩); look()
pick(shell#1)
goto(客厅)；water(绿萝)        // 全角分号、全角括号也可以
say("今天的海很安静")
```

- 语句：`动作(参数, ...)`，用 `;`、`；` 或换行分隔；无参数时括号可省略（`look`）。
- 参数：裸词（`厨房`、`pot#1`）、数字、或带引号的字符串（`"..."`、`「...」`、`“...”`）。
- `//` 之后是注释。
- **顺序执行，遇到第一个失败就停下**，返回已执行部分的结果，方便 agent 重新规划。
- 每段最多 20 条语句、2000 个字符。解释器不会 `eval` 任何东西。

结果格式（每步一行标题 + 缩进的描述）：

```
✓ goto(沙滩)
  你穿过庭院，来到了沙滩。
✗ pick(海星)
  这里没有「海星」。
```

### 当前动作（M0）

| 动作 | 说明 |
| --- | --- |
| `look()` | 时间、天气、位置、能看到的东西、可去的地方、背包 |
| `goto(地点)` | 自动寻路到目标房间 |
| `examine(东西)` | 仔细看 |
| `water(植物)` | 浇水 |
| `pick(东西)` | 捡起小东西（贝壳） |
| `inventory()` | 看背包 |
| `rest(地点)` | 在沙发 / 床上歇会儿 |
| `say(内容)` | 自言自语（进事件日志） |
| `help()` | 列出全部动作 |

物件可以用编号（`pot#1`）或名字（`绿萝`）指代。

## HTTP 接口

小屋进程只监听 `127.0.0.1`，启动时把 `{port, token, pid}` 写进 `<状态目录>/house.json`。
除 `/health` 外，所有请求都要带 `X-House-Token`；`Host` 必须是 `127.0.0.1` 或 `localhost`（防 DNS rebinding）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | `{ok, version, pid}`，无需令牌 |
| GET | `/look` | `{ok, text}` |
| GET | `/help` | `{ok, text}` |
| GET | `/events` | 最近 50 条事件 |
| POST | `/do` | body `{script}` → `{ok, text, results[]}`；执行后立即存档 |
| POST | `/shutdown` | 存档并退出 |

POST 需要 `Content-Type: application/json`，body 上限 16 KB。

## 文件

`~/.dsh/little-house/`（插件可配置 `stateDir`）：

| 文件 | 内容 |
| --- | --- |
| `world/world.json` | 世界存档 |
| `world/events.jsonl` | 事件日志（追加写），记忆系统的原料 |
| `world/house.json` | 运行中小屋的端口与令牌（退出时删除） |
| `diary/YYYY-MM-DD.jsonl` | `house_rest` 写下的小记 |
| `plugin-state.json` | 今天的生活会话 id、唤醒次数、上次唤醒时间 |
