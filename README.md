# 主题图标批量处理 → macOS .app

`app/main.py`（1686 行，PyQt6 + Pillow）已经是可打包状态，`app/1.ico` 会在构建时自动转成 macOS 的 `.icns`。

**路径**：Windows 上写代码 → push 到 GitHub → GitHub 的 macOS 机器编译 → 下载 `.app`。

> 为什么不能在本机打：`.app` 里 `Contents/MacOS/IconStudio` 是 Mach-O 二进制，PyInstaller 只能产出当前系统的包。这台 Windows 上没有 macOS 可执行文件格式的工具链。

---

## 一、三步走

```bash
cd F:\09-DSH\macapp-kit
git init -b main
git add .
git commit -m "init: 主题图标批量处理 macOS 打包"
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

然后打开仓库 → **Actions** → 左侧 `Build macOS .app` → 右上 **Run workflow**，等 5～10 分钟（PyQt6 比 tkinter 慢些），在运行页底部 **Artifacts** 下载：

| 产物 | 给谁用 |
| --- | --- |
| `IconStudio-arm64.zip` | Apple 芯片 Mac（M1/M2/M3/M4） |
| `IconStudio-x86_64.zip` | Intel Mac |

> 私有仓库的 macOS 分钟数按 ×10 计费（免费额度 2000 分钟/月，约等于 macOS 200 分钟）。公开仓库不限量。自己用建议建 Private、别频繁触发。

## 二、装到 Mac 上

1. 解压 → 把 `IconStudio.app` 拖进「应用程序」
2. 第一次打开会被拦（"无法验证开发者"）：**右键 → 打开 → 再点「打开」**；或终端 `xattr -dr com.apple.quarantine /Applications/IconStudio.app`
3. 之后双击就能用；Dock 里显示的名字是「主题图标批量处理」，图标是你的绿底 `i`

解压请用双击（归档工具）或 `ditto -x -k`，别用会丢可执行位的第三方解压工具，否则报"已损坏"。

## 三、这次为 macOS 改了什么

代码本身已经跨平台（`pathlib`、无 Windows API），只补了 4 处会导致 macOS 上直接失败的地方：

| 位置 | 原来 | 改成 | 不改会怎样 |
| --- | --- | --- | --- |
| `main.py` 第 86 行 | `DEFAULT_SRC = Path(__file__).parent / ...` | 打包后改用 `~/Documents` | 默认目录落在 `.app` 内部（只读），选不中、写不出 |
| `main.py` 第 75 行 | 直接 `print` | `sys.stdout is None` 时接 `/dev/null` | `console=False` 下没有控制台，任何 `print` 抛异常 |
| `main.py` QSS/字体 | 微软雅黑、Consolas | 按平台用苹方、Menlo | macOS 没这些字体，界面字体回退错乱 |
| `run_gui()` | — | 设应用名、`raise_()` 抢前台 | 从 Finder 启动时窗口可能躲在后面 |

新增两个文件：

- `build/make_icns.py` —— 把 `1.ico`（256px）生成 10 个尺寸的 `.icns`（16→1024）。`iconutil` 只有 Mac 有，所以这里直接按公开格式写 PNG 型 icns 条目，Finder/Dock 都认。
- `resources/icon.icns` —— 构建时生成，**不进仓库**（`.gitignore` 已排除，可复现）。

## 四、目录

```
macapp-kit/
├── app/
│   ├── main.py            # 你的程序（PyQt6 GUI + 命令行）
│   └── 1.ico              # 图标源文件，构建时转 .icns
├── build/
│   ├── app.spec           # PyInstaller 配置：APP_NAME / BUNDLE_ID / 显示名 / 图标
│   ├── build-macos.sh     # 构建入口：装依赖 → 生成 icns → PyInstaller → 签名
│   ├── make_icns.py       # ico → icns 转换 + 结构自检
│   └── entitlements.plist # 正式签名/公证的权限声明（JIT 等）
├── requirements.txt       # pyinstaller + pillow + pyqt6
├── .github/workflows/build-macos.yml
├── .gitattributes         # 锁 LF：防止脚本被转成 CRLF 后在 macOS 上报 $'\r'
└── .gitignore
```

## 五、本机已经验证过的 / 没验证的

在 Windows 上实测（真跑，不是静态检查）：

- ✅ `main.py` 语法、1686 行
- ✅ CLI 逻辑：造了 6 个假图标跑 `--dry-run`，分类/映射/未识别清单输出正常，返回码 0
- ✅ GUI 真实启动：960×860 窗口、深色主题渲染正常，控件布局无错位
- ✅ `1.ico` → `.icns`：10 个尺寸、结构回读 + Pillow 独立解码，191 KB
- ✅ `APP_NAME` 在 spec / workflow / 脚本三处一致

本地**没法**验证的（只有 macOS 能验）：PyInstaller 打出来的 `.app` 能否启动、Qt 插件是否齐、签名是否通过。第一次 Actions 跑完看一眼日志就知道 —— 挂了把日志发我。

## 六、常见坑（PyQt6 + macOS）

| 现象 | 处理 |
| --- | --- |
| 双击闪退、无提示 | 终端跑 `./IconStudio.app/Contents/MacOS/IconStudio` 看报错；或临时把 spec 里 `console=False` 改 `True` 重打 |
| `Could not find the Qt platform plugin "cocoa"` | spec 的 `datas` 补 `("../build/../<site-packages>/PyQt6/Qt6/plugins", "PyQt6/Qt6/plugins")`；多数情况 PyInstaller 的 PyQt6 hook 已处理 |
| 启动后界面字体发虚/错位 | 已在 QSS 里用苹方；若仍有问题，`QFont` 换成 `QFont("PingFang SC")` |
| 产物特别大（200～300MB） | PyQt6 自带整套 Qt 运行时，正常。想在另一台 Mac 用才需要这么大 |
| 想用命令行参数 | `.app` 是 `console=False`，终端里没有输出。CLI 还是用源码跑：`python3 app/main.py --dry-run --src ...` |
| 结果文件夹找不到 | 打包后默认是 `~/Documents/输出_192x192`（可以在界面里改） |
| 第一次操作时弹「想访问「文稿」文件夹」 | macOS 隐私保护，点允许即可。不想授权就把 `DATA_ROOT` 改成 `Path.home() / "Desktop"` |
| CI 报 `$'\r': command not found` | 脚本行尾被转成 CRLF。`.gitattributes` 已锁 LF，别用记事本改脚本 |
| Intel 版构建报 runner 不存在 | GitHub 轮换标签，本配置用 `macos-15-intel`；真没了就删掉矩阵里那条 |

## 七、发给别人（可选）

现在是 **ad-hoc 签名**：自己电脑装没问题，别人装会弹"无法验证开发者"。要消掉得买 Apple Developer Program（$99/年），然后：

1. 钥匙串导出 `Developer ID Application` 证书为 `.p12` → base64 存进仓库 Secrets：`MACOS_CERT_P12`、`MACOS_CERT_PASSWORD`，再加 `APPLE_ID`、`APPLE_TEAM_ID`、`APPLE_APP_PASSWORD`
2. 解开 `build-macos.yml` 末尾那段注释，重新跑

流程：`codesign --options runtime` → `notarytool submit --wait` → `stapler staple`。`entitlements.plist` 里那三项（JIT / 无签名可执行内存 / 库校验）是 PyInstaller 程序过公证的关键，别删。
