# 第三方组件与素材说明

本仓库的**代码**以 MIT 协议开源（见 [LICENSE](LICENSE)）。以下组件/素材不属于本项目原创，按各自协议使用：

| 组件 | 位置 | 来源 | 协议 |
|------|------|------|------|
| MediaPipe Hand Landmarker 模型 `hand_landmarker.task` | `game/models/` | [Google MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker) 官方模型（float16 / v1） | Apache License 2.0 |
| MediaPipe / OpenCV / Pygame / NumPy | 运行时依赖 | 各自官方开源项目 | 各自开源协议 |
| 音效与背景音乐（7 个 WAV + 1 段 BGM） | `game/sounds/` | 由本项目 `tools/gen_sounds.py` 用 Python 标准库 `wave` + `math` **程序化合成**，无外部素材 | MIT（随本项目） |
| 皮肤贴图 `green/neon/ice/gold/neo.png` | `game/assets/` | 本项目自制像素风小图 | MIT（随本项目） |
| 界面字体 | 不随仓库分发 | 运行时读取系统中文字体（微软雅黑 / 苹方 / Noto Sans CJK 等） | 系统字体授权 |

> 玩家自定义贴图（`game/assets/<皮肤名>.png`）属于运行时可选扩展，仓库中不包含任何第三方版权图片；课堂演示版本里曾使用的第三方角色贴图已在开源版本中移除。

若你是权利人并认为仓库中有内容侵犯你的权益，请通过 Issue 联系删除。
