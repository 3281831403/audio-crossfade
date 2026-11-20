# audio-crossfade

## 题面

歌单改成无缝播放后，交叉淡化处不是掉音量就是咔哒：淡入淡出都写成线性斜坡，等功率曲线在中点掉 3 dB；交叉淡化重叠长度按秒取整，样本数总是差 1；裁剪静音把中间静音一起删掉，语句被拦腰断开；采样率不同却不重采样，播放速度变调；无间隙拼接直接首尾累加，边界“啪”一声爆音；总时长不扣重叠，进度条多出一段交叉时间；峰值归一不判断静音，静音段被放大成噪声；淡化曲线终点不为 0，结束瞬间有咔哒声；批量生成遇到非法曲目只跳过，输出少曲；采样率换算用浮点四舍五入，44100→48000 时长度每秒偏 1 采样。playlist/crossfade.py 是核心，tests/test_crossfade.py 15个红。要修的是：把上述 10 个缺陷逐一修掉，保持样本在 -1..1、曲线端点归零、所有时长按采样精确计算，并让 15 个测试全部转绿。

## 运行方式

在仓库根目录执行：

```bash
python -m pytest tests -q
```

初始（未实现）状态下应恰好输出 `15 failed`，且没有 collection error、import error 或 syntax error：

```text
15 failed
```

每个测试都直接调用 `playlist/crossfade.py` 中的桩函数，因此当前失败原因是 `NotImplementedError`。实现完成后应变为 `15 passed`。

## 字段表

| 字段 | 取值 |
| --- | --- |
| 所属领域 | 游戏、图形与多媒体 |
| 子方向 | 音视频处理 |
| 任务类型 | Bugfix |
| 语言/框架 | Python 3, pytest |
| 环境可复现等级 | 无外部依赖 |

## 目录结构

```text
audio-crossfade/
├── README.md
├── conftest.py
├── .gitignore
├── playlist/
│   ├── __init__.py
│   └── crossfade.py
└── tests/
    └── test_crossfade.py
```

`conftest.py` 将仓库根加入 `sys.path`，因此测试无需安装包即可导入 `playlist`。实现只使用标准库 `math`，不联网、不使用随机数、不调用 `sleep`。

## 约束

- 曲目统一表示为 `{"samples": list[float], "rate": int}`，样本范围 `-1.0 .. 1.0`。
- 曲线名仅支持 `linear`、`equal_power`、`s_curve`；浮点比较容差为 `1e-6`。
- 异常统一使用 `playlist.crossfade.PlaylistError`。
- `tests/test_crossfade.py` 不可修改；只允许修改 `playlist/crossfade.py`（必要时可调整 `playlist/__init__.py` 的导出）。
