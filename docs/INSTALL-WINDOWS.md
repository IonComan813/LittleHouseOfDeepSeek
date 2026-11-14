# 在 Windows（Server 2025）上安装

适用：DSH 桌面版 0.2.2-rc.2（或 0.2.x 的更新版本）。

## 1. 准备 Python

需要 **Python 3.10 或更新**（推荐 3.12/3.13），从 python.org 下载安装，安装时勾选 **Add python.exe to PATH**。

打开一个**新的** PowerShell 确认：

```powershell
python --version
```

> Windows Server 上没有应用商店版 Python 的"假 python"问题；如果提示找不到命令，就是 PATH 没加上。

然后装画面需要的 pygame-ce（不装也能运行，只是没有像素画面，她也不能 house_render）：

```powershell
python -m pip install pygame-ce
```

## 2. 获取代码

```powershell
git clone https://github.com/IonComan813/LittleHouseOfDeepSeek.git
cd LittleHouseOfDeepSeek
```

放在一个以后不会移动的位置：插件是以链接的方式装进 DSH 的，移动目录后需要重新运行安装脚本。

## 3. 装进 DSH

```powershell
python scripts\install.py
```

脚本会自动判断 profile：优先 `desktop`，其次 `web`。想指定的话用 `--profile 名字`。
profile 都在 `%USERPROFILE%\.dsh\profiles\` 下面。

脚本只做两件事：
1. 建一个目录联接：`profiles\<profile>\node_modules\dsh-little-house` → 仓库里的 `plugin\`；
2. 在 `profiles\<profile>\package.json` 里登记这个 bundle（改之前会备份成 `package.json.bak-时间`）。

## 4. 重启 DSH 并等她醒来

完全退出 DSH（确认任务管理器里没有残留的 DSH 进程），再打开。

- 小屋进程会在后台自动启动（`python -m littlehouse`，端口 8770，只监听本机）。
- 每天早上、中午、傍晚、晚上各有一段 40 分钟的**自由活动**，开始时间在时段内随机（早上 7:30–8:30、中午 11:30–12:30、傍晚 17:30–18:30、晚上 21:30–22:30）。
  她早上醒来就是第一段自由活动；23:30–24:00 睡觉（睡前整理当天的日记），睡着时 QQ 消息不会交给她。
  到点后会话列表里出现 **「小屋生活 · 日期」**（每天一个），点进去就能看到她做了什么。
- 自由活动以外她自己过平淡的日常（看书、发呆、睡觉……），画面上看得到。

她的日记写在 `%USERPROFILE%\.dsh\little-house\diary\日期.md`（每天一个文件）。

## 看看小屋（只读画面）

在 RDP 桌面上双击仓库根目录的 **`view.bat`**：

- 小屋已经在运行（DSH 开着）：它只是让**同一个小屋进程**打开动画窗口，不会再起一个渲染进程；
- 小屋没在运行：直接启动小屋并打开窗口（之后 DSH 启动时会连上这个小屋）。

窗口是**只读**的：能看她走来走去、浇水、钓鱼、摸猫，但不接受任何键鼠操作；**关掉窗口不影响小屋**，她照样生活。
窗口太大可以用 `view.bat --scale 1`。只有窗口开着时才持续渲染；关着时不画任何东西（她 `house_render` 时只渲染一帧）。

想让 DSH 一启动就把窗口打开，在配置里把 `house.window` 设为 `true`。

底栏从左到右：日期、时间、天气、季节、贝币；右边橙色那条是她的饱腹，粉色那条是团子的亲密度。

## 5. 改配置（可选）

在 `%USERPROFILE%\.dsh\profiles\<profile>\cordis.patch.yml` 末尾加一段（**patch 会整体替换 config，想保留的键都要写上**）。

> ⚠️ 新 profile 的这个文件里通常只有注释和一行 `[]`（空列表）。**先删掉 `[]` 那一行**再追加，
> 否则 YAML 解析失败，DSH 会启动不了。

```yaml
- id: little-house
  config:
    personaFile: 'C:\Users\你\Documents\my-persona.md'   # 自己的人设
    house:
      python: 'python'          # 找不到 python 时，写 python.exe 的完整路径
      port: 8770
      autoStart: true
      window: false             # true = DSH 启动时打开只读动画窗口
    wake:
      slots:                    # 每天的自由活动时段：from–to 之间随机开始，持续 minutes 分钟
        - { name: 早上, from: '07:30', to: '08:30', minutes: 40 }
        - { name: 中午, from: '11:30', to: '12:30', minutes: 40 }
        - { name: 傍晚, from: '17:30', to: '18:30', minutes: 40 }
        - { name: 晚上, from: '21:30', to: '22:30', minutes: 40 }
    sleep: { from: '23:30', to: '23:59' }   # 几点睡觉（第一段自由活动开始时醒来）
    qq:                         # 见第 6 节
      enabled: false
```

保存即可，**不需要重启 DSH**：几秒内插件会自动重载（小屋进程也会随之重启），新配置立刻生效。
改插件的 JS 代码则需要完全重启 DSH。

## 6. 接上 QQ（NapCat）

她背包里有一部手机：你随时可以用 QQ 私聊她，她用手机回你；自由活动写完日记后，遇到有趣或重要的事，她可能主动给你发消息。
插件**直接连 NapCat**，不需要再装别的 QQ 插件（如果之前装过 dsh-onebot，别让它和这里连同一个 NapCat 账号，不然会两边都回）。

**NapCat 这边**：网页控制台 → 网络配置 → 新建 **「WebSocket 服务端」**：
- 主机 `127.0.0.1`，端口 `3001`（或别的，下面对应改）；
- token 随便设一串（下面填同一串）；
- 消息格式选 **array**（数组）。保存并启用。

**插件这边**（第 5 节那段配置里的 `qq`）：

```yaml
    qq:
      enabled: true
      url: 'ws://127.0.0.1:3001'
      accessToken: '和 NapCat 里一样的 token'
      ownerQQ: '你的 QQ 号'
      ownerName: '主人'          # 她怎么称呼你
      friends: []               # 除了你，还接受谁的私聊（QQ 号）
      sleepReply: '（睡着了……zzZ）'  # 她睡着时自动回的话（留空 = 不回）
```

- 你的消息会进她当天的「小屋生活 · 日期」会话（和自由活动是同一个会话，0 点换新的一天），她用手机（`phone_message`）回复。
  不在自由活动时间时，她会知道角色此刻在做什么；**你请她在屋里做什么事**（浇花、做饭……），她会接过角色去做，做完把角色交还给日常。
- 她能看懂你发的图片和 QQ 表情，也会用 QQ 表情；可以拍一张小屋的照片发给你。**语音、视频、文件不会转给她**。
- 她睡着的时候（23:30 前后到第二天早上第一段自由活动），消息不会交给她，自动回一句「睡着了」（同一个聊天半小时最多一次）。
- `friends` 是其他人的 QQ 号：他们私聊她也会进同一个会话，她用 `phone_message(to: 名字)` 回。
- 群聊暂时没有开放。
- 所有消息记在 `little-house\qq\日期.jsonl`，第二天整理进她的记忆（`little-house\memory\memory.md` 可以看）。
- 连接状态看 `plugin.log` 里的 `QQ: connected`。

## 卸载

```powershell
python scripts\install.py --uninstall
```

小屋存档（`%USERPROFILE%\.dsh\little-house\`）不会被删除。

## 排错

| 现象 | 处理 |
| --- | --- |
| 想知道插件在干什么 / 出了什么错 | 看 `%USERPROFILE%\.dsh\little-house\plugin.log` |
| 一直没有「小屋生活」会话 | 看 `%USERPROFILE%\.dsh\little-house\plugin-state.json` 是否生成；没有的话插件没加载，重新运行安装脚本并确认重启了 DSH |
| 有会话但她什么都没做 | 在会话里看报错；多半是小屋进程没起来（检查 `python --version`，或在配置里写 python 的完整路径） |
| 端口 8770 被占用 | 配置里把 `house.port` 改成别的 |
| 她的工具里没有 house_render | 小屋进程的 Python 里没装 pygame-ce，或 `house.python` 指向了另一个 Python |
| 想立刻看到一次自由活动 | 临时把 `wake.firstWakeDelaySeconds` 改成 `10`（`wake.testMinutes` 是这段多长）再重启 DSH |
| QQ 没反应 | `plugin.log` 里没有 `QQ: connected`：检查 NapCat 的 WebSocket 服务端是否启用、端口和 token 是否一致；有 connected 但不回：私聊要在 `ownerQQ` / `friends` 里 |
| DSH 关了但 python 还在跑 | 正常：DSH 被强制关闭时来不及通知小屋退出。下次 DSH 启动会直接连上它；想关掉就在任务管理器结束那个 python 进程（存档每次行动后都会写盘） |
