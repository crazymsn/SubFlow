"""Run with the inference runtime as well as CI when torch is available."""
import pytest

torch = pytest.importorskip('torch')

from bilingual_sub._data.bootstrap.qwen_mps import (  # noqa: E402
    bounded_conv1d,
    bounded_conv_transpose1d,
    install_convolutions,
    stable_mps_sampling,
)


@pytest.mark.parametrize('stride,dilation,groups,padding,mode', [
    (1, 1, 1, 0, 'zeros'), (2, 3, 2, 4, 'zeros'),
    (3, 2, 4, 3, 'reflect'), (1, 1, 1, 'same', 'zeros'),
])
def test_tiled_convolution_preserves_boundaries(stride, dilation, groups, padding, mode):
    torch.manual_seed(8)
    layer = torch.nn.Conv1d(4, 8, 5, stride=stride, dilation=dilation,
                            groups=groups, padding=padding, padding_mode=mode)
    value = torch.randn(2, 4, 513)
    with torch.inference_mode():
        expected = layer(value)
        actual = bounded_conv1d(layer, value, max_output=31)
    torch.testing.assert_close(actual, expected)


@pytest.mark.skipif(not torch.backends.mps.is_available(), reason='Requires an actual Apple GPU')
def test_long_audio_convolution_runs_on_mps_and_matches_cpu():
    torch.manual_seed(8)
    layer = torch.nn.Conv1d(4, 8, 7, dilation=3)
    value = torch.randn(1, 4, 240007)
    with torch.inference_mode():
        expected = layer(value)
        actual = bounded_conv1d(layer.to('mps'), value.to('mps'))
        assert actual.device.type == 'mps'
        torch.testing.assert_close(actual.cpu(), expected, atol=2e-5, rtol=2e-5)


@pytest.mark.parametrize('stride,dilation,groups,padding,output_padding', [
    (1, 1, 1, 0, 0), (2, 3, 2, 4, 1), (3, 2, 4, 3, 2), (8, 1, 1, 0, 0),
])
def test_tiled_transposed_convolution_preserves_overlap_and_bias(stride, dilation, groups, padding, output_padding):
    torch.manual_seed(8)
    layer = torch.nn.ConvTranspose1d(4, 8, 7, stride=stride, dilation=dilation,
                                     groups=groups, padding=padding, output_padding=output_padding)
    value = torch.randn(2, 4, 513)
    with torch.inference_mode():
        expected = layer(value)
        actual = bounded_conv_transpose1d(layer, value, max_output=37)
    torch.testing.assert_close(actual, expected)


@pytest.mark.skipif(not torch.backends.mps.is_available(), reason='Requires an actual Apple GPU')
def test_long_audio_transposed_convolution_runs_on_mps_and_matches_cpu():
    torch.manual_seed(8)
    layer = torch.nn.ConvTranspose1d(4, 8, 16, stride=8, padding=3, output_padding=2)
    value = torch.randn(1, 4, 30000)
    with torch.inference_mode():
        expected = layer(value)
        actual = bounded_conv_transpose1d(layer.to('mps'), value.to('mps'))
        assert actual.device.type == 'mps'
        torch.testing.assert_close(actual.cpu(), expected, atol=2e-5, rtol=2e-5)


def test_scoped_install_is_idempotent_and_preserves_cpu_forward():
    from unittest.mock import Mock

    layer = torch.nn.Conv1d(4, 8, 7)
    original = Mock(wraps=layer.forward)
    layer.forward = original
    install_convolutions(layer)
    wrapped = layer.forward
    install_convolutions(layer)
    assert layer.forward is wrapped
    value = torch.randn(1, 4, 99)
    layer(value)
    original.assert_called_once_with(value)


def test_sampling_restores_torch_after_failure_and_leaves_cpu_draws_unchanged():
    original = torch.multinomial
    probabilities = torch.tensor([0., .3, .7])
    torch.manual_seed(42)
    expected = original(probabilities, 20, replacement=True)
    with pytest.raises(RuntimeError, match='cancel'):
        with stable_mps_sampling():
            torch.manual_seed(42)
            assert torch.equal(torch.multinomial(probabilities, 20, replacement=True), expected)
            raise RuntimeError('cancel')
    assert torch.multinomial is original


@pytest.mark.skipif(not torch.backends.mps.is_available(), reason='Requires an actual Apple GPU')
def test_mps_sampling_uses_cpu_draws_and_returns_indices_on_mps():
    probabilities = torch.softmax(torch.arange(32, dtype=torch.float32) / 8, dim=0)
    torch.manual_seed(42)
    expected = torch.multinomial(probabilities, 100, replacement=True)
    with stable_mps_sampling():
        torch.manual_seed(42)
        actual = torch.multinomial(probabilities.to('mps'), 100, replacement=True)
    assert actual.device.type == 'mps'
    assert torch.equal(actual.cpu(), expected)
