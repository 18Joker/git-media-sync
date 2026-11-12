# Git 媒体下载器

把阿里云盘里 **git 未管理** 的图片/视频等媒体文件，按原目录层级、可勾选、覆盖式增量下载回本地 Git 项目。配合阿里云盘自带的「自动备份」上传整个项目文件夹，实现跨设备同步项目媒体素材。

- 只做下载，不做上传（清单生成是纯本地操作）。
- **清单驱动**：项目根维护 `media.gmsync` 清单，下载侧按清单精准定位，不再全盘扫描（云端空文件夹多时全量扫描极慢）。
- 跳过 git 已跟踪的文件和 `.git/`，**不会动你的源码**。
- 相同文件（按大小）跳过，不同则覆盖；**只增不删**，不删除本地任何文件。
- 单个 exe，拷到另一台电脑双击即用，无需安装 Python。

## 使用步骤

1. 双击 `GitMediaDownloader.exe`（建议放在可写目录，如 `D:\tools\`）。
2. 左侧「添加」项目：填名称（别名，默认取本地文件夹名）、云盘路径（如 `/备份/my-project`）、本地项目路径（如 `D:\code\my-project`）。「素材后缀」可选，逗号分隔，留空用默认（jpg png mp4 等）。可添加多个项目。
3. **设备 A（有素材的电脑）**：选中项目点「生成清单」——纯本地扫描、无需登录，在项目根生成 `media.gmsync`（只含 git 未跟踪、后缀命中的文件）。阿里云盘自动同步的**后缀白名单需加入 `gmsync`** 及各素材后缀，等待清单和素材上传。
4. 点「扫码登录」，用阿里云盘 App 扫描二维码授权（每台电脑首次需登录，之后自动免登）。
5. **设备 B**：选中项目点「列出文件」：优先读云盘根目录的 `media.gmsync`，按清单精准定位（日志显示清单文件数与生成时间）；无清单时回退递归全量扫描；清单损坏会明确报错；云端缺失或大小不符（同步未完成）的文件跳过并警告。随后跳过 git 已跟踪文件，按大小比对，生成**树形清单**。
   - 状态：`待下载`（本地没有）/ `将覆盖`（大小不同）/ `已相同`（跳过）。
   - 默认勾选「待下载 + 将覆盖」。
6. 自由勾选/取消（点文件夹可联动其下所有文件，支持三态），用「全选/全不选/反选」批量操作。
7. 点「下载选中(N)」开始下载，日志显示进度，可随时「取消」。

## 清单格式（media.gmsync）

UTF-8 JSON，位于项目根目录（云盘侧即云盘路径的根目录），由「生成清单」自动维护，也可自行生成：

```json
{
  "version": 1,
  "generated_at": "2026-11-12T21:30:00",
  "files": [
    { "path": "assets/cover.png", "size": 102400 },
    { "path": "assets/video/01.mp4", "size": 7340032 }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `version` | 格式版本，目前固定 `1` |
| `generated_at` | 生成时间（本地时间 ISO 格式），日志展示用 |
| `files[].path` | 相对项目根目录，正斜杠 `/`；不允许 `..`、绝对路径、反斜杠 |
| `files[].size` | 字节数；用于本地比对（相同跳过/不同覆盖）与云端同步完整性校验 |

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
downloader/manifest.py  清单生成 / 解析 / 校验 / 分组（纯逻辑）
downloader/storage.py   aligo 封装（登录 / 列目录 / 清单读取与精准定位 / 原子覆盖下载）
downloader/gui.py       Tkinter 界面
tests/                  单元测试
```