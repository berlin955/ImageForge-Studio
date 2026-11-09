# 智图工坊 ImageForge Studio

电商出图的 Windows 桌面软件：AI 智能打码、批量主图（裁切 / 拼图 / 品牌角标），后续加入智能规格、智能详情、批量水印。

作者：**berlin955**

## 下载安装

到 [Releases](https://github.com/berlin955/ImageForge-Studio/releases/latest) 下载 `ImageForge-Studio-Setup-x.y.z.exe`，双击安装即可（不需要管理员权限）。
也提供免安装的 `Portable.zip`，解压后运行 `MaskForge.exe`。

软件每次启动会检查 GitHub 上有没有新版本，有的话提示「立即更新」，自动下载安装并重新打开。

## 使用流程

1. **批量处理** → 导入图片或文件夹（也可以直接拖进窗口）
2. 点「识别未处理的图片」，AI 自动找出部位并贴码
3. 在右侧看图审核，选中码可以拖动、缩放、旋转、倾斜；按 Enter 确认并跳到下一张
4. **导出** → 选择保存位置、尺寸、格式和文件名，点「批量导出」

不需要逐张审核的批次，直接用「一键打码并保存」。

### 常用快捷键

| 操作 | 按键 |
| --- | --- |
| 缩放码（等比） | 拖四个角（按住 Shift） |
| 旋转码 | 拖顶部圆点（Shift 每次 15°），或 Alt + 滚轮 |
| 缩放选中的码 | Shift + 滚轮 |
| 缩放 / 平移画面 | 滚轮 / 右键或中键拖动 |
| 看原图 | 按住空格 |
| 微调位置 | 方向键（Shift 加速） |
| 撤销 / 重做 | Ctrl+Z / Ctrl+Y |
| 复制 / 删除码 | Ctrl+D / Delete |
| 确认并下一张 | Enter |

### 设置

左下角「设置」里可以改：主题、自动更新、识别灵敏度、每个部位的默认样式（贴图 / 马赛克 / 模糊 / 色块）、默认贴图、码的大小倍数，以及管理自己上传的贴图。设置和贴图保存在 `%APPDATA%\MaskForge Studio`。

## 发布新版本（改完代码后）

1. 在 `CHANGELOG.md` 最上面加一节 `## v1.0.1`，写上这次改了什么，提交推送
2. 打开仓库的 **Actions → 构建与发布 → Run workflow**，版本号填 `1.0.1`，勾选「发布为正式版本」，点 Run
3. GitHub 会自动：自检 → 打包 exe → 制作安装程序 → 发布 Release（约 10 分钟）
4. 已安装的软件下次启动就会提示更新

（推送 `v1.0.1` 这样的标签也会自动发布。）

推送到 `main` 分支也会自动构建一次（不发布），安装包可以在 Actions 页面的 Artifacts 里下载试用。

## 本地开发

```
pip install -r requirements.txt -r requirements-build.txt
python tools/fetch_model.py      # 取出识别模型到 models/
python tools/make_icon.py        # 生成图标
python app/main.py               # 运行
python app/main.py --selftest    # 自检
```

## 说明

- 识别模型来自开源项目 [NudeNet](https://github.com/notAI-tech/NudeNet)，在本机运行，图片不会上传到任何地方。NudeNet 使用 AGPL-3.0 协议。
- 自动识别不保证 100% 准确，状态为「未检出」或「待审核」的图片建议看一眼再导出。
