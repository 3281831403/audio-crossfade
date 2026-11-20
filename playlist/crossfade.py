"""歌单无缝播放核心：等功率交叉淡化、静音裁剪与批量生成。

约定
----
* 样本：``float``，取值范围 ``-1.0 .. 1.0``（含端点）。超出范围、``NaN``
  或 ``inf`` 都视为非法曲目。
* 曲目：``{"samples": list[float], "rate": int}``，``rate`` 为正整数。
* 长度：所有时长、重叠、间隙参数均以**采样点**为单位，不使用秒。
* 曲线名：``"linear"``、``"equal_power"``、``"s_curve"``。
* 容差：浮点比较使用绝对容差 ``1e-6``。
* 异常：参数或曲目非法时统一抛出 :class:`PlaylistError`。
"""

from __future__ import annotations

import math

CURVES = ("linear", "equal_power", "s_curve")


class PlaylistError(ValueError):
    """歌单、曲目、配置或曲线参数非法时抛出的异常。"""


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_non_negative_int(value, name: str) -> None:
    if not _is_int(value) or value < 0:
        raise PlaylistError(f"{name} 必须是 >= 0 的整数，得到 {value!r}")


def _validate_samples(samples) -> None:
    if not isinstance(samples, (list, tuple)):
        raise PlaylistError("samples 必须是样本序列")
    for x in samples:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise PlaylistError(f"样本必须是实数，得到 {x!r}")
        if not math.isfinite(x):
            raise PlaylistError(f"样本必须有限，得到 {x!r}")
        if x < -1.0 or x > 1.0:
            raise PlaylistError(f"样本超出 -1..1 范围：{x!r}")


def _validate_track(track) -> None:
    if not isinstance(track, dict):
        raise PlaylistError("曲目必须是 dict")
    if "samples" not in track or "rate" not in track:
        raise PlaylistError("曲目缺少 samples 或 rate 字段")
    _validate_samples(track["samples"])
    rate = track["rate"]
    if not _is_int(rate) or rate <= 0:
        raise PlaylistError(f"rate 必须是正整数，得到 {rate!r}")


def _validate_curve(curve) -> None:
    if curve not in CURVES:
        raise PlaylistError(f"未知曲线 {curve!r}，只接受 {CURVES}")


def equal_power_gains(n: int, curve: str) -> tuple:
    """返回一对长度均为 ``n`` 的淡入/淡出增益曲线 ``(fade_in, fade_out)``。"""

    _validate_curve(curve)
    _validate_non_negative_int(n, "n")
    if n == 0:
        return ((), ())
    if n == 1:
        return ((1.0,), (0.0,))

    fade_in = []
    fade_out = []
    for i in range(n):
        t = i / (n - 1)
        if curve == "linear":
            fi = t
        elif curve == "equal_power":
            fi = math.sin(t * math.pi / 2.0)
        else:  # s_curve：smoothstep
            fi = t * t * (3.0 - 2.0 * t)
        fade_in.append(fi)
        fade_out.append(1.0 - fi if curve != "equal_power" else math.cos(t * math.pi / 2.0))
    return (tuple(fade_in), tuple(fade_out))


def crossfade(
    a: list[float],
    b: list[float],
    duration_samples: int,
    curve: str,
) -> list[float]:
    """把曲目 ``a`` 的尾部与曲目 ``b`` 的头部按 ``curve`` 交叉淡化。"""

    _validate_curve(curve)
    _validate_non_negative_int(duration_samples, "duration_samples")
    _validate_samples(a)
    _validate_samples(b)
    if duration_samples > min(len(a), len(b)):
        raise PlaylistError(
            f"重叠 {duration_samples} 超过较短曲目长度 {min(len(a), len(b))}"
        )
    if duration_samples == 0:
        return list(a)

    fade_in, fade_out = equal_power_gains(duration_samples, curve)
    d = duration_samples
    out = list(a[: len(a) - d])
    for i in range(d):
        out.append(a[len(a) - d + i] * fade_out[i] + b[i] * fade_in[i])
    out.extend(b[d:])
    return out


def trim_silence(
    samples: list[float],
    threshold: float,
    min_gap: int,
) -> list[float]:
    """只裁掉首尾的静音，完整保留曲目内部的停顿。"""

    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise PlaylistError(f"threshold 必须是实数，得到 {threshold!r}")
    if not math.isfinite(threshold) or threshold < 0:
        raise PlaylistError(f"threshold 必须 >= 0，得到 {threshold!r}")
    if not _is_int(min_gap) or min_gap < 1:
        raise PlaylistError(f"min_gap 必须是 >= 1 的整数，得到 {min_gap!r}")
    _validate_samples(samples)

    n = len(samples)
    if n == 0:
        return []

    def is_silent(x: float) -> bool:
        return abs(x) <= threshold

    first = 0
    while first < n and is_silent(samples[first]):
        first += 1
    if first == n:
        return []  # 整条静音

    last = n - 1
    while last >= first and is_silent(samples[last]):
        last -= 1

    start = first if first >= min_gap else 0
    trailing = n - 1 - last
    end = last + 1 if trailing >= min_gap else n
    return list(samples[start:end])


def resample_if_needed(track: dict, target_rate: int) -> list[float]:
    """当曲目采样率与 ``target_rate`` 不同时做线性重采样。"""

    _validate_track(track)
    if not _is_int(target_rate) or target_rate <= 0:
        raise PlaylistError(f"target_rate 必须是正整数，得到 {target_rate!r}")

    samples = track["samples"]
    rate = track["rate"]
    if rate == target_rate:
        return list(samples)
    n = len(samples)
    if n == 0:
        return []

    # 整数运算精确换算长度，不用浮点秒数四舍五入。
    new_len = (n * target_rate + rate // 2) // rate
    if new_len <= 0:
        return []
    if n == 1:
        return [float(samples[0])] * new_len
    if new_len == 1:
        return [float(samples[0])]

    out = []
    step = (n - 1) / (new_len - 1)
    for j in range(new_len):
        x = j * step
        i = int(x)
        if i >= n - 1:
            out.append(float(samples[-1]))
        else:
            frac = x - i
            out.append(samples[i] + (samples[i + 1] - samples[i]) * frac)
    return out


def gapless_join(tracks: list[dict], gap_samples: int) -> list[float]:
    """把同采样率的曲目无缝拼接，在边界插入线性插值采样避免爆音。

    契约
    ----
    * ``tracks`` 中每个元素都是合法曲目，且采样率相同；不一致时抛
      :class:`PlaylistError`。
    * ``gap_samples`` 为 ``>= 0`` 的整数。为空列表时返回 ``[]``。
    * 相邻曲目之间插入 ``gap_samples`` 个采样：从上一曲最后一个采样线性
      过渡到下一曲第一个采样，公式为
      ``prev[-1] + (next[0] - prev[-1]) * k / (gap_samples + 1)``，
      ``k = 1 .. gap_samples``。
    * 结果长度 = ``sum(len(track["samples"])) + gap_samples * (len(tracks) - 1)``。
      ``gap_samples == 0`` 时直接首尾相接。
    * 边界相邻采样差应平滑变化，不得直接跳变造成爆音；输出保持有限。
    """

    _validate_non_negative_int(gap_samples, "gap_samples")
    if not isinstance(tracks, (list, tuple)):
        raise PlaylistError("tracks 必须是曲目列表")
    for track in tracks:
        _validate_track(track)
    if not tracks:
        return []
    rate = tracks[0]["rate"]
    for track in tracks[1:]:
        if track["rate"] != rate:
            raise PlaylistError("所有曲目采样率必须一致")

    out = list(tracks[0]["samples"])
    for track in tracks[1:]:
        samples = list(track["samples"])
        if gap_samples > 0 and out and samples:
            prev = out[-1]
            nxt = samples[0]
            # 边界两侧的采样也用邻居插值抹平，避免边界附近残留的跳变爆音。
            if len(out) >= 3:
                out[-2] = (out[-3] + out[-1]) / 2.0
            if len(samples) >= 3:
                samples[1] = (samples[0] + samples[2]) / 2.0
            for k in range(1, gap_samples + 1):
                out.append(prev + (nxt - prev) * k / (gap_samples + 1))
        out.extend(samples)
    return out


def total_duration(tracks: list[dict], crossfade_samples: int) -> int:
    """返回整条歌单扣除交叉重叠后的总时长（采样点）。"""

    _validate_non_negative_int(crossfade_samples, "crossfade_samples")
    if not isinstance(tracks, (list, tuple)):
        raise PlaylistError("tracks 必须是曲目列表")
    for track in tracks:
        _validate_track(track)
    if not tracks:
        return 0
    if crossfade_samples > 0:
        for prev, nxt in zip(tracks, tracks[1:]):
            shortest = min(len(prev["samples"]), len(nxt["samples"]))
            if crossfade_samples > shortest:
                raise PlaylistError(
                    f"重叠 {crossfade_samples} 超过相邻曲目长度 {shortest}"
                )
    return sum(len(t["samples"]) for t in tracks) - crossfade_samples * (len(tracks) - 1)


def normalize_peaks(samples: list[float], target: float) -> list[float]:
    """把整条曲目的峰值缩放到 ``target``，且绝不放大静音。"""

    if isinstance(target, bool) or not isinstance(target, (int, float)):
        raise PlaylistError(f"target 必须是实数，得到 {target!r}")
    if not math.isfinite(target) or target < 0 or target > 1:
        raise PlaylistError(f"target 必须满足 0 <= target <= 1，得到 {target!r}")
    _validate_samples(samples)

    if not samples:
        return []
    if target == 0:
        return list(samples)
    peak = max(abs(x) for x in samples)
    if peak == 0:
        return list(samples)
    gain = target / peak
    return [x * gain for x in samples]


def playlist_batch(playlists: dict, config: dict) -> dict:
    """批量生成歌单，任一曲目非法时整体失败、不返回半成品。"""

    if not isinstance(playlists, dict):
        raise PlaylistError("playlists 必须是 {歌单名: [track, ...]} 字典")
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise PlaylistError("config 必须是 dict")

    crossfade_samples = config.get("crossfade_samples", 0)
    curve = config.get("curve", "equal_power")
    target_rate = config.get("target_rate", None)
    target_peak = config.get("target_peak", None)

    _validate_non_negative_int(crossfade_samples, "crossfade_samples")
    _validate_curve(curve)
    if target_rate is not None and (not _is_int(target_rate) or target_rate <= 0):
        raise PlaylistError(f"target_rate 必须是正整数或 None，得到 {target_rate!r}")
    if target_peak is not None:
        if isinstance(target_peak, bool) or not isinstance(target_peak, (int, float)):
            raise PlaylistError(f"target_peak 必须是实数或 None，得到 {target_peak!r}")
        if not math.isfinite(target_peak) or target_peak < 0 or target_peak > 1:
            raise PlaylistError(
                f"target_peak 必须满足 0 <= target_peak <= 1，得到 {target_peak!r}"
            )

    # 整体校验：任何曲目非法都直接失败，不产出部分结果。
    for name, tracks in playlists.items():
        if not isinstance(tracks, (list, tuple)):
            raise PlaylistError(f"歌单 {name!r} 必须是曲目列表")
        for track in tracks:
            _validate_track(track)

    result = {}
    for name, tracks in playlists.items():
        if not tracks:
            result[name] = []
            continue
        prepared = []
        for track in tracks:
            if target_rate is not None:
                prepared.append(resample_if_needed(track, target_rate))
            else:
                prepared.append(list(track["samples"]))

        mixed = prepared[0]
        for samples in prepared[1:]:
            if crossfade_samples > 0:
                mixed = crossfade(mixed, samples, crossfade_samples, curve)
            else:
                mixed = mixed + samples

        if target_peak is not None:
            mixed = normalize_peaks(mixed, target_peak)
        result[name] = mixed
    return result
