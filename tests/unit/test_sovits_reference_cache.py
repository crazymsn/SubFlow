import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def cache():
    path = Path(__file__).resolve().parents[2] / "third_party/GPT-SoVITS/GPT_SoVITS/TTS_infer_pack/reference_cache.py"
    spec = importlib.util.spec_from_file_location("sovits_reference_cache_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def model(cache):
    calls = []
    model = SimpleNamespace(prompt_cache=cache.empty_prompt_cache(), is_v2pro=False,
                            configs=SimpleNamespace(version="v2"), calls=calls)
    def semantic(path):
        calls.append(("semantic", str(path)))
        model.prompt_cache["prompt_semantic"] = Path(path).read_bytes()
    def spec(path):
        calls.append(("spectrum", str(path)))
        content = Path(path).read_bytes()
        model.prompt_cache.update(raw_audio=content, raw_sr=16000)
        return content, "speaker"
    def set_spec(path):
        model.prompt_cache["refer_spec"] = [spec(path)]
    model._set_prompt_semantic = semantic
    model._get_ref_spec = spec
    model._set_ref_spec = set_spec
    model.set_ref_audio = lambda path: cache.set_reference(model, path)
    def prompt(text, lang, version):
        calls.append(("prompt", text, lang, version))
        return [lang], object(), text
    model.text_preprocessor = SimpleNamespace(segment_and_extract_feature_for_text=prompt)
    return model


@pytest.fixture
def refs(tmp_path):
    paths = [tmp_path / name for name in ("primary.wav", "aux1.wav", "aux2.wav")]
    for path in paths:
        path.write_bytes(path.name.encode())
    return paths


def test_primary_contents_replaced_with_same_metadata(cache, model, refs):
    path = refs[0]
    cache.prepare_references(model, path, [])
    cache.prepare_references(model, path, [])
    assert len(model.calls) == 2
    old = path.stat()
    path.write_bytes(b"x" * old.st_size)
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    cache.prepare_references(model, path, [])
    assert len(model.calls) == 4
    assert model.prompt_cache["prompt_semantic"] == b"x" * old.st_size


def test_auxiliary_order_contents_and_removal_refresh_cache(cache, model, refs):
    primary, first, second = refs
    cache.prepare_references(model, primary, [first, second])
    initial = len(model.calls)
    cache.prepare_references(model, primary, [first, second])
    assert len(model.calls) == initial
    cache.prepare_references(model, primary, [second, first])
    assert [entry[0] for entry in model.prompt_cache["refer_spec"]] == [p.read_bytes() for p in (primary, second, first)]
    first.write_bytes(b"changed")
    cache.prepare_references(model, primary, [second, first])
    assert model.prompt_cache["refer_spec"][-1][0] == b"changed"
    assert model.prompt_cache["raw_audio"] == primary.read_bytes()
    cache.prepare_references(model, primary, [])
    assert len(model.prompt_cache["refer_spec"]) == 1


@pytest.mark.parametrize("failure", ["semantic", "spectrum", "changed"])
def test_failed_primary_preprocessing_retains_complete_previous_cache(cache, model, refs, failure):
    cache.prepare_references(model, refs[0], [refs[2]])
    previous = model.prompt_cache
    if failure == "semantic":
        def fail(path):
            model.prompt_cache["prompt_semantic"] = b"incomplete"
            raise RuntimeError("failed semantic extraction")
        model._set_prompt_semantic = fail
    else:
        setter = model._set_ref_spec
        def fail(path):
            setter(path)
            if failure == "changed":
                Path(path).write_bytes(b"changed during extraction")
            else:
                raise RuntimeError("failed spectrum extraction")
        model._set_ref_spec = fail
    with pytest.raises((RuntimeError, OSError)):
        cache.prepare_references(model, refs[1], [])
    assert model.prompt_cache is previous
    assert previous["prompt_semantic"] == refs[0].read_bytes()
    assert previous["raw_audio"] == refs[0].read_bytes()
    assert len(previous["refer_spec"]) == 2


def test_failed_auxiliary_rolls_back_primary_and_auxiliary_update(cache, model, refs):
    cache.prepare_references(model, refs[0], [])
    previous = model.prompt_cache
    with pytest.raises(FileNotFoundError):
        cache.prepare_references(model, refs[1], [refs[2].with_name("missing.wav")])
    assert model.prompt_cache is previous


def test_auxiliary_failure_does_not_poison_next_retry(cache, model, refs):
    cache.prepare_references(model, refs[0], [])
    previous = model.prompt_cache
    original = model._get_ref_spec
    def failing(path):
        result = original(path)
        if path == refs[2]:
            raise OSError("auxiliary unavailable")
        return result
    model._get_ref_spec = failing
    with pytest.raises(OSError):
        cache.prepare_references(model, refs[0], refs[1:])
    assert model.prompt_cache is previous
    model._get_ref_spec = original
    cache.prepare_references(model, refs[0], refs[1:])
    assert len(model.prompt_cache["refer_spec"]) == 3
    assert model.prompt_cache["raw_audio"] == refs[0].read_bytes()


@pytest.mark.parametrize("changed", [0, 1])
def test_content_change_during_auxiliary_preprocessing_rejected(cache, model, refs, changed):
    cache.prepare_references(model, refs[0], [])
    previous = model.prompt_cache
    original = model._get_ref_spec
    def mutate(path):
        value = original(path)
        refs[changed].write_bytes(b"modified during extraction")
        return value
    model._get_ref_spec = mutate
    with pytest.raises(OSError, match="changed"):
        cache.prepare_references(model, refs[0], [refs[1]])
    assert model.prompt_cache is previous


def test_prompt_language_and_version_are_part_of_identity(cache, model):
    for lang, version in [("en", "v2"), ("en", "v2"), ("zh", "v2"), ("zh", "v1")]:
        model.configs.version = version
        cache.prepare_prompt(model, "test.", lang, {"."})
    assert model.calls == [("prompt", "test.", "en", "v2"), ("prompt", "test.", "zh", "v2"),
                           ("prompt", "test.", "zh", "v1")]


def test_blank_and_failed_prompt_do_not_corrupt_cache(cache, model):
    cache.prepare_prompt(model, "\n ", "en", {"."})
    assert not model.calls
    cache.prepare_prompt(model, " hello ", "en", {"."})
    previous = dict(model.prompt_cache)
    def fail(*args):
        raise RuntimeError("BERT failed")
    model.text_preprocessor.segment_and_extract_feature_for_text = fail
    with pytest.raises(RuntimeError):
        cache.prepare_prompt(model, "hello", "zh", {"."})
    assert model.prompt_cache == previous


def test_model_invalidation_drops_all_tensor_features(cache, model, refs):
    cache.prepare_references(model, refs[0], refs[1:])
    cache.prepare_prompt(model, "hello", "en", {"."})
    cache.invalidate_prompt_cache(model)
    assert model.prompt_cache == cache.empty_prompt_cache()
    with pytest.raises(ValueError, match="reference"):
        cache.prepare_references(model, None, [])
    cache.prepare_references(model, refs[0], [])
    assert model.prompt_cache["prompt_semantic"] is not None
