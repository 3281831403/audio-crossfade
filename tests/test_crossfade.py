"""15 个红灯测试：每个测试都直接调用尚未实现的桩函数。

测试只验证公开契约，不修改实现。浮点比较统一使用 1e-6 绝对容差。
"""

import math

import pytest

from playlist.crossfade import (
    PlaylistError,
    crossfade,
    equal_power_gains,
    gapless_join,
    normalize_peaks,
    playlist_batch,
    resample_if_needed,
    total_duration,
    trim_silence,
)


def _track(samples, rate=44100):
    """构造曲目字典，避免每个测试重复写字面量。"""
    return {"samples": list(samples), "rate": rate}


def test_equal_power_midpoint_has_no_3db_drop():
    """缺陷 1：等功率曲线中点不能掉到 0.5（-3 dB）。"""
    n = 101
    fade_in, fade_out = equal_power_gains(n, "equal_power")
    mid = n // 2

    assert len(fade_in) == n
    assert len(fade_out) == n
    assert abs(fade_in[mid] - 1.0 / math.sqrt(2.0)) <= 1e-6
    assert abs(fade_out[mid] - 1.0 / math.sqrt(2.0)) <= 1e-6
    assert abs(fade_in[mid] ** 2 + fade_out[mid] ** 2 - 1.0) <= 1e-6


def test_crossfade_overlap_length_is_exact_sample_count():
    """缺陷 2：重叠区必须恰好为 duration_samples 个采样。"""
    a = [0.1, 0.2, 0.3, 0.4, 0.5]
    b = [-0.1, -0.2, -0.3, -0.4, -0.5]

    out = crossfade(a, b, 3, "linear")

    assert len(out) == len(a) + len(b) - 3
    assert out[0] == pytest.approx(a[0])
    assert out[1] == pytest.approx(a[1])
    assert out[-1] == pytest.approx(b[-1])


def test_trim_silence_keeps_interior_silence():
    """缺陷 3：只裁首尾静音，内部停顿必须保留。"""
    samples = (
        [0.0] * 50
        + [0.25] * 40
        + [0.0] * 30
        + [0.5] * 40
        + [0.0] * 50
    )

    out = trim_silence(samples, threshold=1e-6, min_gap=10)

    assert len(out) == 40 + 30 + 40
    assert out[:40] == [0.25] * 40
    assert out[40:70] == [0.0] * 30
    assert out[70:] == [0.5] * 40


def test_resample_when_rate_differs():
    """缺陷 4：采样率不同必须重采样，不能原样返回。"""
    track = _track([0.0] * 44100, rate=44100)

    out = resample_if_needed(track, 48000)

    assert len(out) == 48000
    assert all(abs(x) <= 1e-6 for x in out)
    assert len(resample_if_needed(track, 44100)) == 44100


def test_gapless_join_interpolates_boundary():
    """缺陷 5：拼接边界要插值过渡，不能直接跳变爆音。"""
    a = _track([0.2] * 5 + [0.8])
    b = _track([-0.6] + [-0.2] * 5)

    out = gapless_join([a, b], gap_samples=4)

    assert len(out) == 6 + 6 + 4
    assert out[0] == pytest.approx(0.2)
    assert out[5] == pytest.approx(0.8)
    assert out[-1] == pytest.approx(-0.2)
    steps = [abs(out[i + 1] - out[i]) for i in range(len(out) - 1)]
    assert max(steps) <= 0.5


def test_total_duration_subtracts_crossfade():
    """缺陷 6：总时长必须扣除每处交叉重叠。"""
    tracks = [_track([0.0] * 100) for _ in range(3)]

    assert total_duration(tracks, 20) == 260
    assert total_duration(tracks, 0) == 300
    assert total_duration([], 20) == 0


def test_normalize_peaks_does_not_amplify_silence():
    """缺陷 7：整条静音不能被归一化成噪声。"""
    silent = [0.0] * 32

    out = normalize_peaks(silent, 0.9)

    assert out == silent
    assert max(abs(x) for x in out) <= 1e-12

    quiet = [0.0, 0.2, -0.4, 0.1]
    normalized = normalize_peaks(quiet, 0.8)
    assert max(abs(x) for x in normalized) == pytest.approx(0.8)


def test_curve_endpoints_close_at_zero_and_one():
    """缺陷 8：每条曲线的端点和起止状态必须是 0/1。"""
    for curve in ("linear", "equal_power", "s_curve"):
        fade_in, fade_out = equal_power_gains(64, curve)

        assert abs(fade_in[0]) <= 1e-6
        assert abs(fade_in[-1] - 1.0) <= 1e-6
        assert abs(fade_out[0] - 1.0) <= 1e-6
        assert abs(fade_out[-1]) <= 1e-6
        assert all(
            fade_in[i] <= fade_in[i + 1] + 1e-9 for i in range(len(fade_in) - 1)
        )
        assert all(
            fade_out[i] >= fade_out[i + 1] - 1e-9
            for i in range(len(fade_out) - 1)
        )


def test_playlist_batch_rolls_back_on_invalid_track():
    """缺陷 9：任一曲目非法时整批失败，不能跳过缺曲。"""
    playlists = {
        "good": [_track([0.0, 0.1, 0.0])],
        "bad": [_track([0.0, 0.2]), _track([0.0, 1.5, 0.0])],
    }

    with pytest.raises(PlaylistError):
        playlist_batch(playlists, {"crossfade_samples": 1, "curve": "equal_power"})


def test_resample_uses_integer_rounding_no_drift():
    """缺陷 10：44100→48000 用整数换算，不能每秒漂 1 个采样。"""
    one_second = _track([0.0] * 44100)
    assert len(resample_if_needed(one_second, 48000)) == 48000

    odd = _track([0.0] * 44101)
    expected = (44101 * 48000 + 44100 // 2) // 44100
    assert expected == 48001
    assert len(resample_if_needed(odd, 48000)) == expected

    two_seconds = _track([0.0] * 88200)
    assert len(resample_if_needed(two_seconds, 48000)) == 96000


def test_curve_with_two_samples_has_exact_endpoints():
    """组合：n=2 时三条曲线的端点都必须精确落在 0 和 1。"""
    for curve in ("linear", "equal_power", "s_curve"):
        fade_in, fade_out = equal_power_gains(2, curve)

        assert len(fade_in) == 2
        assert len(fade_out) == 2
        assert abs(fade_in[0]) <= 1e-6
        assert abs(fade_in[1] - 1.0) <= 1e-6
        assert abs(fade_out[0] - 1.0) <= 1e-6
        assert abs(fade_out[1]) <= 1e-6


def test_crossfade_zero_duration_returns_a_copy():
    """组合：duration_samples=0 返回 a 的原样副本。"""
    a = [0.1, -0.2, 0.3]
    b = [0.9, 0.8]

    out = crossfade(a, b, 0, "s_curve")

    assert out == a
    assert out is not a


def test_normalize_peaks_target_zero_is_noop():
    """组合：target=0 表示不归一，不放大也不衰减。"""
    samples = [0.25, -0.5, 0.1]

    out = normalize_peaks(samples, 0.0)

    assert out == samples
    assert out is not samples


def test_empty_lists_return_empty():
    """组合：所有入口的空列表都返回空结果。"""
    assert equal_power_gains(0, "equal_power") == ((), ())
    assert crossfade([], [], 0, "linear") == []
    assert trim_silence([], 0.0, 1) == []
    assert resample_if_needed(_track([], 44100), 48000) == []
    assert gapless_join([], 4) == []
    assert total_duration([], 10) == 0
    assert normalize_peaks([], 1.0) == []
    assert playlist_batch({}, {}) == {}


def test_playlist_batch_preserves_order_on_success():
    """组合：批量全部成功时歌单顺序、长度与峰值都符合预期。"""
    playlists = {
        "first": [_track([0.1, 0.2, 0.3, 0.4])],
        "second": [_track([-0.1, -0.2, -0.3, -0.4]), _track([0.0] * 4)],
    }

    out = playlist_batch(
        playlists,
        {"crossfade_samples": 2, "curve": "equal_power", "target_peak": 0.5},
    )

    assert list(out) == ["first", "second"]
    assert len(out["first"]) == 4
    assert len(out["second"]) == 4 + 4 - 2
    assert max(abs(x) for x in out["second"]) == pytest.approx(0.5)
