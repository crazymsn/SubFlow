"""Prepare replacement model state without mutating a serving instance."""
import copy
import os
import tempfile
import uuid
from functools import wraps
from pathlib import Path


def clone_config(config):
    candidate = copy.copy(config)
    # Tensor attributes are read-only derived values and may carry autograd
    # history. Do not deepcopy tensors or entire models merely to stage config.
    candidate.__dict__ = {key: copy.deepcopy(value) if isinstance(value, (dict, list, tuple, set)) else value
                          for key, value in vars(config).items()}
    return candidate


def atomic_config_write(path, text):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".subflow-config-", suffix=".tmp", dir=destination.parent)
    pending = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(destination)
    finally:
        pending.unlink(missing_ok=True)


def model_update(operation):
    @wraps(operation)
    def update(model, *args, **kwargs):
        if getattr(model, "_model_update_in_progress", False):
            return operation(model, *args, **kwargs)
        candidate = copy.copy(model)
        candidate.configs = clone_config(model.configs)
        candidate.configs._defer_save = True
        candidate._model_update_in_progress = True
        if hasattr(model, "vocoder_configs"):
            candidate.vocoder_configs = copy.deepcopy(model.vocoder_configs)
        if hasattr(model, "prompt_cache"):
            candidate.prompt_cache = {key: list(value) if isinstance(value, list) else value
                                      for key, value in model.prompt_cache.items()}
        result = operation(candidate, *args, **kwargs)
        candidate.configs._defer_save = False
        candidate.model_revision = uuid.uuid4().hex
        if kwargs.get("save", True):
            candidate.configs.save_configs()
        candidate.__dict__.pop("_model_update_in_progress", None)
        # Model operations are serialized by the service; publish all fields in
        # one assignment, retaining the public pipeline object's identity.
        model.__dict__ = candidate.__dict__
        return result
    return update
