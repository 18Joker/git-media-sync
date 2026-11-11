# Git 媒体下载器

把阿里云盘里 **git 未管理** 的图片/视频等媒体文件，按原目录层级、可勾选、覆盖式增量下载回本地 Git 项目。配合阿里云盘自带的「自动备份」上传整个项目文件夹，实现跨设备同步项目媒体素材。

- 只做下载，不做上传。
- 跳过 git 已跟踪的文件和 `.git/`，**不会动你的源码**。
- 相同文件（按大小）跳过，不同则覆盖；**只增不删**，不删除本地任何文件。
- 单个 exe，拷到另一台电脑双击即用，无需安装 Python。

## 使用步骤

1. 双击 `GitMediaDownloader.exe`（建议放在可写目录，如 `D:\tools\`）。
2. 左侧「添加」项目：填名称（别名，默认取本地文件夹名）、云盘路径（如 `/备份/my-project`）、本地项目路径（如 `D:\code\my-project`）。可添加多个项目。
3. 点「扫码登录」，用阿里云盘 App 扫描二维码授权（每台电脑首次需登录，之后自动免登）。
4. 选中项目，点「列出文件」：工具递归扫描云盘，跳过 git 已跟踪文件，按大小比对，生成**树形清单**。
   - 状态：`待下载`（本地没有）/ `将覆盖`（大小不同）/ `已相同`（跳过）。
   - 默认勾选「待下载 + 将覆盖」。
5. 自由勾选/取消（点文件夹可联动其下所有文件，支持三态），用「全选/全不选/反选」批量操作。
6. 点「下载选中(N)」开始下载，日志显示进度，可随时「取消」。

## 备用登录：refresh_token

扫码不便时，可在登录弹窗粘贴 refresh_token：

1. 浏览器登录 [阿里云盘网页版](https://www.aliyundrive.com/)。
2. 按 `F12` → `Application`（应用）→ 左侧 `Local Storage` → 选中域名 → 找到 `token` 项。
3. 复制其中 `refresh_token` 的值，粘贴到登录框，点「用 token 登录」。

## 从源码运行 / 打包

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python main.py            # 直接运行
build.bat                                # 打包，产物 dist\GitMediaDownloader.exe
```

运行测试：`.venv\Scripts\python -m pytest`

## 注意

- exe 请放在**可写目录**：配置 `config.json` 与日志 `app.log` 写在 exe 旁。
- 登录 token 由 aligo 缓存于用户目录 `~/.aligo`，每台电脑各自登录。
- `config.json` 可拷到另一台电脑复用（云盘路径/名称相同，只需改本地路径）。
- 首次启动稍慢（单文件自解压）；个别杀毒软件可能误报，添加信任即可。
- 本地项目路径必须是 **git 仓库**且已安装 git，否则工具会报错停止（避免误下源码）。
- 云盘自动备份若把项目备份在「资源盘/备份盘」，云盘路径需指向实际备份位置。

## 结构

```
main.py                 入口（windowed 流重定向 + 启动）
downloader/config.py    项目配置（JSON）
downloader/core.py      git 过滤 / 大小比对 / 树模型（纯逻辑）
downloader/storage.py   aligo 封装（登录 / 列目录 / 原子覆盖下载）
downloader/gui.py       Tkinter 界面
tests/                  单元测试
```