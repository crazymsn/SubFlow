"""Exact temporal tiling for long MPS audio convolutions in the voice engines.

macOS < 15.1 limits every convolution output dimension to 65536, including
audio samples (pytorch/pytorch#134416). Split individual convolutions with
their full receptive field, preserving codec context and keeping weights and
computation on MPS. Do not shorten the codec's transformer decoding window.
"""
from contextlib import contextmanager
from functools import partial
from threading import RLock

import torch
import torch.nn.functional as F

_sampling_lock = RLock()


@contextmanager
def stable_mps_sampling():
    """Use CPU categorical draws for the serialized native-voice request.

    The model and codec remain on MPS. Sampling on CPU removed unwanted spoken
    prefixes in our M1/torch 2.5.1 native-voice comparisons. Keep the original
    temperature/top-k distribution rather than switching to greedy decoding.
    Explicit generators/output buffers keep their original torch semantics.
    """
    with _sampling_lock:
        original = torch.multinomial

        def sample(value, *args, **kwargs):
            if value.device.type == 'mps' and kwargs.get('generator') is None and kwargs.get('out') is None:
                return original(value.float().cpu(), *args, **kwargs).to(value.device)
            return original(value, *args, **kwargs)

        torch.multinomial = sample
        try:
            yield
        finally:
            torch.multinomial = original


def bounded_conv1d(layer, value, *, max_output=65536):
    """Evaluate Conv1d in output tiles, with exactly the original padding."""
    padding = layer._reversed_padding_repeated_twice
    stride = layer.stride[0]
    receptive = layer.dilation[0] * (layer.kernel_size[0] - 1) + 1
    length = (value.shape[-1] + sum(padding) - receptive) // stride + 1
    if length <= max_output:
        return layer._conv_forward(value, layer.weight, layer.bias)
    if any(padding):
        mode = 'constant' if layer.padding_mode == 'zeros' else layer.padding_mode
        value = F.pad(value, padding, mode=mode)
    pieces = []
    for start in range(0, length, max_output):
        end = min(start + max_output, length)
        section = value[..., start * stride:(end - 1) * stride + receptive].contiguous()
        pieces.append(F.conv1d(section, layer.weight, layer.bias, layer.stride,
                               0, layer.dilation, layer.groups))
    return torch.cat(pieces, dim=-1)


def install_audio_convolutions(model):
    """Scope the compatibility path to this loaded Qwen speech tokenizer."""
    install_convolutions(model.model.speech_tokenizer.model)


def _mps_forward(value, *, layer, original, operation):
    if value.device.type == 'mps':
        return operation(layer, value)
    return original(value)


def install_convolutions(module):
    """Patch only this module's audio layers; CPU/CUDA retain their forwards."""
    for layer in module.modules():
        if getattr(layer, '_subflow_mps_audio', False):
            continue
        if isinstance(layer, torch.nn.Conv1d):
            operation = bounded_conv1d
        elif isinstance(layer, torch.nn.ConvTranspose1d):
            operation = bounded_conv_transpose1d
        else:
            continue
        layer.forward = partial(_mps_forward, layer=layer, original=layer.forward, operation=operation)
        layer._subflow_mps_audio = True


def bounded_conv_transpose1d(layer, value, *, max_output=65536):
    """Overlap-add transposed convolution tiles before cropping global padding."""
    stride, padding = layer.stride[0], layer.padding[0]
    receptive = layer.dilation[0] * (layer.kernel_size[0] - 1) + 1
    full_length = (value.shape[-1] - 1) * stride + receptive + layer.output_padding[0]
    if full_length - 2 * padding <= max_output:
        return F.conv_transpose1d(value, layer.weight, layer.bias, layer.stride,
                                  layer.padding, layer.output_padding, layer.groups, layer.dilation)
    tile = max(1, (max_output - receptive) // stride + 1)
    output = value.new_zeros((*value.shape[:-2], layer.out_channels, full_length))
    for start in range(0, value.shape[-1], tile):
        section = value[..., start:start + tile].contiguous()
        piece = F.conv_transpose1d(section, layer.weight, None, layer.stride,
                                   0, 0, layer.groups, layer.dilation)
        offset = start * stride
        output[..., offset:offset + piece.shape[-1]] += piece
    output = output[..., padding:full_length - padding]
    if layer.bias is not None:
        output = output + layer.bias[:, None]
    return output
