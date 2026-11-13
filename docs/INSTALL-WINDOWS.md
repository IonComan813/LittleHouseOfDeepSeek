# 在 Windows（Server 2025）上安装

适用：DSH 桌面版 0.2.2-rc.2（或 0.2.x 的更新版本）。

## 1. 准备 Python

需要 **Python 3.10 或更新**（推荐 3.12/3.13），从 python.org 下载安装，安装时勾选 **Add python.exe to PATH**。

打开一个**新的** PowerShell 确认：

```powershell
python --version
```

> Windows Server 上没有应用商店版 Python 的"假 python"问题；如果提示找不到命令，就是 PATH 没加上。

然后装画面需要的 pygame-ce（不装也能运行，只是没有像素画面，她也不能 house_glance）：

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
- 大约 **2 分钟**后，第一次唤醒发生：会话列表里出现 **「小屋生活 · 日期」**，点进去就能看到她做了什么。
- 之后每隔 90～240 分钟随机醒来一次，00:30～08:00 不打扰，每天最多 8 次。

她的小记写在 `%USERPROFILE%\.dsh\little-house\diary\日期.jsonl`。

## 看看小屋（只读画面）

在 RDP 桌面上双击仓库根目录的 **`view.bat`**：

- 小屋已经在运行（DSH 开着）：它只是让**同一个小屋进程**打开动画窗口，不会再起一个渲染进程；
- 小屋没在运行：直接启动小屋并打开窗口（之后 DSH 启动时会连上这个小屋）。

窗口是**只读**的：能看她走来走去、浇水、钓鱼、摸猫，但不接受任何键鼠操作；**关掉窗口不影响小屋**，她照样生活。
窗口太大可以用 `view.bat --scale 1`。只有窗口开着时才持续渲染；关着时不画任何东西（她 `house_glance` 时只渲染一帧）。

想让 DSH 一启动就把窗口打开，在配置里把 `house.window` 设为 `true`。

底栏从左到右：日期、时间、天气、季节、贝币；右边两条是她的饱腹和精力，粉色那条是团子的亲密度。

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
      minIntervalMinutes: 90
      maxIntervalMinutes: 240
      quietHours: '00:30-08:00'
      maxPerDay: 8
      firstWakeDelaySeconds: 120
      maxActionsPerWake: 12
```

保存即可，**不需要重启 DSH**：几秒内插件会自动重载（小屋进程也会随之重启），新配置立刻生效。
注意重载会重新开始「首次唤醒」倒计时；改插件的 JS 代码则需要完全重启 DSH。

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
| 她的工具里没有 house_glance | 小屋进程的 Python 里没装 pygame-ce，或 `house.python` 指向了另一个 Python |
| 想立刻看到一次唤醒 | 临时把 `firstWakeDelaySeconds` 改成 `10` 再重启 DSH |
| DSH 关了但 python 还在跑 | 正常：DSH 被强制关闭时来不及通知小屋退出。下次 DSH 启动会直接连上它；想关掉就在任务管理器结束那个 python 进程（存档每次行动后都会写盘） |
