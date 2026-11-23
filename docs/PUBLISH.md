# 发布说明（Gitee 主仓 + GitHub 镜像）

## 0. 仓库信息

| 项 | 值 |
|----|----|
| 仓库名 | `ai-gesture-game` |
| Gitee | https://gitee.com/rainprayer/ai-gesture-game |
| GitHub | https://github.com/rainprayer/ai-gesture-game（镜像） |
| 默认分支 | `main` |
| 协议 | MIT |

## 1. 前置条件

1. 已安装 Git；
2. Gitee 已开启 **双因素认证**（未开启时无法创建仓库）。开启后 `git push` **不能再用登录密码**，需要使用「设置 → 安全设置 → 私人令牌」，勾选 `projects` 权限；
3. 本地已配置提交身份（脚本会在缺失时自动写入本仓库级配置）：

```bash
git config user.name  "Yecheng Hong"
git config user.email "rainprayer@users.noreply.gitee.com"
```

## 2. 在 Gitee 创建空仓库

打开 https://gitee.com/projects/new ：

- 仓库名称：`ai-gesture-game`
- 路径：`ai-gesture-game`
- **不要**勾选"使用 Readme 文件初始化这个仓库"（否则首次 push 会冲突）
- 开源 / 公开

创建完成后仓库地址为 `https://gitee.com/rainprayer/ai-gesture-game.git`。

## 3. 推送

仓库根目录已初始化 Git 并完成首次提交，直接执行：

```powershell
# 只推 Gitee
powershell -ExecutionPolicy Bypass -File scripts/publish.ps1 -Remote gitee

# 只推 GitHub
powershell -ExecutionPolicy Bypass -File scripts/publish.ps1 -Remote github -GitHubUser <你的GitHub用户名>

# 双仓都推
powershell -ExecutionPolicy Bypass -File scripts/publish.ps1 -Remote all -GitHubUser <你的GitHub用户名>
```

脚本会做这些事：检查工作区 → 提交未提交改动 → 配置远端 → `git push -u` → 用 `git ls-remote` 核验远端分支是否真的存在。

### 手动命令（等价）

```bash
git remote add gitee https://gitee.com/rainprayer/ai-gesture-game.git
git push -u gitee main

git remote add github https://github.com/<user>/ai-gesture-game.git
git push -u github main
```

首次推送时 Git 凭证管理器会弹窗要求账号 + **私人令牌**（不是登录密码），输入一次后会记住。

## 4. 关于 GitHub 镜像

GitHub 在国内可能无法直连。可选的传输方式：

- 使用代理 / 加速器后正常 `git push`；
- 先推 Gitee，再在能访问 GitHub 的网络环境执行 `git push github main`；
- 仅把 GitHub 当作备份，不必保证实时同步。

> 注意：`gh-proxy` 一类镜像只适合**下载**，不能用于 `git push`。

## 5. 安全约定

- **不要把私人令牌写进仓库、脚本、README 或提交历史**；
- 令牌只交给 Git 凭证管理器保存，泄露后立即在 Gitee 后台撤销；
- `.gitignore` 已忽略 `game/save.json`、`.dsh-meow/`、`__pycache__/` 等运行时文件；
- 仓库不包含任何第三方版权角色图片（详见 `NOTICE.md`）。

## 6. 发布后验收清单

- [ ] 仓库首页 README 正常渲染，5 张配图能显示（Gitee 对相对路径图片支持良好）；
- [ ] `git ls-remote --heads gitee` 能看到 `refs/heads/main`；
- [ ] 另找一台干净电脑（或新建 venv）clone 后按 README 能装依赖、跑起来；
- [ ] `python tools/smoke_test.py` 全部通过；
- [ ] LICENSE 在仓库首页被识别为 MIT；
- [ ] 仓库描述、Topics 已填写（见下）。

## 7. 仓库描述与 Topics 建议

**描述**：摄像头手势控制的横版平台游戏 | MediaPipe 21 关键点 + Pygame | 免训练手势识别

**Topics**：`python` `pygame` `mediapipe` `computer-vision` `hand-tracking` `gesture-recognition` `opencv` `game` `platformer` `education`

## 8. 后续维护

```bash
git add -A
git commit -m "feat: ..."
git push gitee main
```

发版时打 tag：

```bash
git tag -a v1.0.0 -m "AI Gesture Jump v1.0.0"
git push gitee v1.0.0
```

Gitee 的 Release 可以附上演示视频（体积较大的 mp4 建议放 Release 附件而不是仓库）。
