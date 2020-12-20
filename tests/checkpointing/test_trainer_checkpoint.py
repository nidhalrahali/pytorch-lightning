# Copyright The PyTorch Lightning team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from argparse import Namespace
from copy import deepcopy
import os
from pathlib import Path
import pickle
import platform
import re
from unittest import mock
from unittest.mock import Mock

import cloudpickle
from omegaconf import Container, OmegaConf
import pytest
import torch
import yaml

import pytorch_lightning as pl
from pytorch_lightning import seed_everything, Trainer
from pytorch_lightning.callbacks import Callback, ModelCheckpoint
from pytorch_lightning.loggers import TensorBoardLogger
from pytorch_lightning.utilities.cloud_io import load as pl_load
from pytorch_lightning.utilities.exceptions import MisconfigurationException
from tests.base import BoringModel
import tests.base.develop_utils as tutils


def test_finetunning_with_resume_from_checkpoint(tmpdir):
    """
    This test validates that generated ModelCheckpoint is pointing to the right best_model_path during test
    """

    seed_everything(3)

    checkpoint_callback = ModelCheckpoint(monitor='val_loss', dirpath=tmpdir, filename="{epoch:02d}", save_top_k=-1)

    class ExtendedBoringModel(BoringModel):

        def configure_optimizers(self):
            optimizer = torch.optim.SGD(self.layer.parameters(), lr=0.001)
            lr_scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=1)
            return [optimizer], [lr_scheduler]

        def validation_step(self, batch, batch_idx):
            output = self.layer(batch)
            loss = self.loss(batch, output)
            self.log("val_loss", loss, on_epoch=True, prog_bar=True)

    model = ExtendedBoringModel()
    model.validation_epoch_end = None
    trainer = Trainer(
        default_root_dir=tmpdir,
        max_epochs=1,
        limit_train_batches=12,
        limit_val_batches=6,
        limit_test_batches=12,
        callbacks=[checkpoint_callback],
    )
    trainer.fit(model)
    assert os.listdir(tmpdir) == ['epoch=00.ckpt', 'lightning_logs']

    best_model_paths = [deepcopy(checkpoint_callback.best_model_path)]
    results = []

    for idx in range(3, 6):
        # load from checkpoint
        trainer = pl.Trainer(
            default_root_dir=tmpdir,
            max_epochs=idx,
            limit_train_batches=12,
            limit_val_batches=12,
            limit_test_batches=12,
            resume_from_checkpoint=best_model_paths[-1],
            progress_bar_refresh_rate=0,
        )
        trainer.fit(model)
        results.append(trainer.test()[0])
        best_model_paths.append(deepcopy(trainer.callbacks[0].best_model_path))

    for idx in range(len(results) - 1):
        assert results[idx]["val_loss"] > results[idx + 1]["val_loss"]

    for idx, best_model_path in enumerate(best_model_paths[1:]):
        assert f"epoch={idx + 2}" in best_model_path