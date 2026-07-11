# 桌面端更新记录 / Desktop Changelog

## v0.1.0

中文：

- **桌面端建立独立版本线**，从 `0.1.0` 开始，不再延续 CLI 已累计的版本号；安装包名称改为 `DeepSeekFathom-0.1.0-Setup.exe`。
- **软件名称、窗口标题、安装目录、桌面入口、开始菜单和卸载项统一为 `DeepSeekFathom`**。
- **采用透明背景蓝色鲸鱼图标**，EXE、桌面入口和应用内图标保持一致；桌面入口使用标准 Windows `.lnk`。
- **提供简体中文 Windows 安装程序**，按当前用户安装到 `%LOCALAPPDATA%\Programs\DeepSeekFathom`，无需管理员权限。
- **修复上下文占用显示**，优先采用上游输入 token 并按当前会话增量校正，改进中文和图片估算。
- **自动与手动上下文压缩会原子写回 JSONL**，重启或切换会话后保持压缩结果。
- **仓库和支持链接改为 `ffffff233/DeepSeekFathom`**；桌面发布使用独立标签 `desktop-vX.Y.Z`。

English:

- **Started an independent desktop version line at `0.1.0`**, separate from the accumulated CLI version. The installer is now named `DeepSeekFathom-0.1.0-Setup.exe`.
- **Unified the product name** across the window title, install directory, desktop entry, Start menu, and uninstall entry as `DeepSeekFathom`.
- **Added the transparent blue whale icon** consistently to the EXE, desktop entry, and app UI. The desktop entry remains a standard Windows `.lnk`.
- **Added a Simplified Chinese per-user Windows installer** targeting `%LOCALAPPDATA%\Programs\DeepSeekFathom` without requiring administrator privileges.
- **Fixed context usage reporting** using upstream input tokens plus the current-session delta, with better CJK and image estimates.
- **Persisted automatic and manual compaction atomically to JSONL**, so compacted history survives restarts and session switches.
- **Updated repository and support links to `ffffff233/DeepSeekFathom`**. Desktop releases now use independent `desktop-vX.Y.Z` tags.

桌面端在独立版本线之前的开发记录保留在 [历史联合更新记录](CHANGELOG-LEGACY.md) 中，其中桌面入口最早加入于原联合版本 `v0.1.33`。

Desktop development before this independent version line remains in the [legacy combined changelog](CHANGELOG-LEGACY.md), where the desktop entrypoint first appeared in combined release `v0.1.33`.
