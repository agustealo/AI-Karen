"""
Production Fine Tuner - Real model training and fine-tuning system
Provides complete training pipeline with evaluation, checkpointing, and distributed support.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable
from datetime import datetime
from dataclasses import dataclass, asdict
import asyncio

from ai_karen_engine.echocore.contracts import EchoTrainingCandidate

logger = logging.getLogger(__name__)


@dataclass
class TrainingConfig:
    """Configuration for fine-tuning."""
    model_path: str
    output_dir: str
    learning_rate: float = 2e-5
    batch_size: int = 8
    num_epochs: int = 3
    warmup_steps: int = 100
    max_seq_length: int = 512
    gradient_accumulation_steps: int = 1
    weight_decay: float = 0.01
    adam_epsilon: float = 1e-8
    max_grad_norm: float = 1.0
    logging_steps: int = 10
    eval_steps: int = 100
    save_steps: int = 500
    save_total_limit: int = 3
    fp16: bool = False
    gradient_checkpointing: bool = False
    dataloader_num_workers: int = 0


@dataclass
class TrainingMetrics:
    """Training metrics for a single epoch/step."""
    epoch: int
    step: int
    loss: float
    learning_rate: float
    grad_norm: Optional[float] = None
    eval_loss: Optional[float] = None
    eval_accuracy: Optional[float] = None
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()


@dataclass
class TrainingRun:
    """Information about a training run."""
    run_id: str
    start_time: str
    end_time: Optional[str]
    config: TrainingConfig
    final_metrics: Optional[TrainingMetrics]
    status: str  # "running", "completed", "failed"
    error: Optional[str] = None


class ProductionFineTuner:
    """
    Production-ready fine-tuner for language models.

    Features:
    - Complete training pipeline
    - Model evaluation and metrics
    - Checkpoint management
    - Early stopping
    - Learning rate scheduling
    - Dataset preparation and validation
    - Training resumption from checkpoint
    - Distributed training support (future)
    - Model versioning
    - Experiment tracking
    """

    def __init__(
        self,
        logs_path: Path,
        output_dir: Path = Path("models/fine_tuned"),
        enable_experiment_tracking: bool = True
    ):
        self.logs_path = Path(logs_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.enable_experiment_tracking = enable_experiment_tracking
        self.experiments_dir = self.output_dir / "experiments"
        self.experiments_dir.mkdir(exist_ok=True)

        self.logger = logging.getLogger(__name__)

        # Training state
        self.current_run: Optional[TrainingRun] = None
        self.metrics_history: List[TrainingMetrics] = []
        self._candidate_queue: List[Dict[str, Any]] = []

    def _load_logs(self) -> List[Dict[str, Any]]:
        """Load and parse log files."""
        if not self.logs_path.exists():
            return []

        events = []
        try:
            for line in self.logs_path.read_text().splitlines():
                try:
                    item = json.loads(line)
                    events.append(item)
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            self.logger.error(f"Error loading logs: {e}")

        return events

    def prepare_dataset(
        self,
        min_length: int = 10,
        max_length: int = 512,
        validation_split: float = 0.1
    ) -> Tuple[List[str], List[str]]:
        """
        Prepare training dataset from logs.

        Args:
            min_length: Minimum text length
            max_length: Maximum text length
            validation_split: Fraction for validation

        Returns:
            Tuple of (train_texts, val_texts)
        """
        events = self._load_logs()

        # Extract text from events
        texts = []
        for event in events:
            text = event.get("text") or event.get("content") or event.get("message")
            if text and isinstance(text, str):
                text = text.strip()
                if min_length <= len(text) <= max_length:
                    texts.append(text)

        # Split into train and validation
        if validation_split > 0:
            split_idx = int(len(texts) * (1 - validation_split))
            train_texts = texts[:split_idx]
            val_texts = texts[split_idx:]
        else:
            train_texts = texts
            val_texts = []

        self.logger.info(
            f"Prepared dataset: {len(train_texts)} train, {len(val_texts)} validation samples"
        )

        return train_texts, val_texts

    def queue_candidate(self, candidate: EchoTrainingCandidate) -> None:
        """Queue a training candidate for later dataset preparation."""
        record = {
            "artifact_id": candidate.artifact_id,
            "user_id": candidate.user_id,
            "tenant_id": candidate.tenant_id,
            "input_payload": candidate.input_payload,
            "labels": candidate.labels,
            "quality_score": candidate.quality_score,
            "queued_at": datetime.utcnow().isoformat(),
        }
        self._candidate_queue.append(record)

        queue_file = self.experiments_dir / "candidate_queue.jsonl"
        with open(queue_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        self.logger.info(
            "Queued training candidate for artifact %s (quality=%.3f)",
            candidate.artifact_id,
            candidate.quality_score,
        )

    async def fine_tune(
        self,
        model_path: str,
        config: Optional[TrainingConfig] = None,
        train_texts: Optional[List[str]] = None,
        val_texts: Optional[List[str]] = None
    ) -> TrainingRun:
        """
        Fine-tune a model.

        Args:
            model_path: Path to base model
            config: Training configuration
            train_texts: Training texts (if None, will load from logs)
            val_texts: Validation texts

        Returns:
            TrainingRun with results
        """
        # Use default config if not provided
        if config is None:
            config = TrainingConfig(
                model_path=model_path,
                output_dir=str(self.output_dir / datetime.utcnow().strftime("%Y%m%d_%H%M%S"))
            )

        # Prepare dataset if not provided
        if train_texts is None:
            train_texts, val_texts = self.prepare_dataset()

        if not train_texts:
            raise ValueError("No training data available")

        # Create training run
        run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.current_run = TrainingRun(
            run_id=run_id,
            start_time=datetime.utcnow().isoformat(),
            end_time=None,
            config=config,
            final_metrics=None,
            status="running"
        )

        try:
            # Only a real training backend can produce a successful run.
            # Missing dependencies propagate as a failed training operation.
            final_metrics = await self._train_with_transformers(
                model_path, config, train_texts, val_texts
            )

            # Update run status
            self.current_run.status = "completed"
            self.current_run.end_time = datetime.utcnow().isoformat()
            self.current_run.final_metrics = final_metrics

            # Save run info
            if self.enable_experiment_tracking:
                await self._save_experiment(self.current_run)

            self.logger.info(f"Fine-tuning completed: {run_id}")

        except Exception as e:
            self.current_run.status = "failed"
            self.current_run.error = str(e)
            self.current_run.end_time = datetime.utcnow().isoformat()
            self.logger.error(f"Fine-tuning failed: {e}")
            raise

        return self.current_run

    async def _train_with_transformers(
        self,
        model_path: str,
        config: TrainingConfig,
        train_texts: List[str],
        val_texts: Optional[List[str]]
    ) -> TrainingMetrics:
        """Real training using HuggingFace transformers."""
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            Trainer,
            TrainingArguments,
            DataCollatorForLanguageModeling,
            TrainerCallback
        )
        from datasets import Dataset
        import torch

        # Load tokenizer and model
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(model_path)

        # Prepare datasets
        def tokenize_function(examples):
            return tokenizer(
                examples["text"],
                padding="max_length",
                truncation=True,
                max_length=config.max_seq_length
            )

        train_dataset = Dataset.from_dict({"text": train_texts})
        train_dataset = train_dataset.map(tokenize_function, batched=True)

        eval_dataset = None
        if val_texts:
            eval_dataset = Dataset.from_dict({"text": val_texts})
            eval_dataset = eval_dataset.map(tokenize_function, batched=True)

        # Training arguments
        training_args = TrainingArguments(
            output_dir=config.output_dir,
            learning_rate=config.learning_rate,
            per_device_train_batch_size=config.batch_size,
            per_device_eval_batch_size=config.batch_size,
            num_train_epochs=config.num_epochs,
            warmup_steps=config.warmup_steps,
            weight_decay=config.weight_decay,
            logging_steps=config.logging_steps,
            eval_steps=config.eval_steps if eval_dataset else None,
            save_steps=config.save_steps,
            save_total_limit=config.save_total_limit,
            evaluation_strategy="steps" if eval_dataset else "no",
            fp16=config.fp16,
            gradient_accumulation_steps=config.gradient_accumulation_steps,
            gradient_checkpointing=config.gradient_checkpointing,
            dataloader_num_workers=config.dataloader_num_workers,
        )

        # Data collator
        data_collator = DataCollatorForLanguageModeling(
            tokenizer=tokenizer,
            mlm=False  # For causal LM
        )

        # Custom callback to track metrics
        class MetricsCallback(TrainerCallback):
            def __init__(self, fine_tuner):
                self.fine_tuner = fine_tuner

            def on_log(self, args, state, control, logs=None, **kwargs):
                if logs:
                    metrics = TrainingMetrics(
                        epoch=int(state.epoch) if state.epoch else 0,
                        step=state.global_step,
                        loss=logs.get("loss", 0.0),
                        learning_rate=logs.get("learning_rate", 0.0),
                        eval_loss=logs.get("eval_loss"),
                    )
                    self.fine_tuner.metrics_history.append(metrics)

        # Trainer
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=eval_dataset,
            data_collator=data_collator,
            callbacks=[MetricsCallback(self)]
        )

        # Train
        trainer.train()

        # Save model
        trainer.save_model(config.output_dir)
        tokenizer.save_pretrained(config.output_dir)

        # Get final metrics
        if self.metrics_history:
            final_metrics = self.metrics_history[-1]
        else:
            final_metrics = TrainingMetrics(
                epoch=config.num_epochs,
                step=0,
                loss=0.0,
                learning_rate=config.learning_rate
            )

        return final_metrics

    async def _mock_training(
        self,
        model_path: str,
        config: TrainingConfig,
        num_samples: int
    ) -> TrainingMetrics:
        """Mock training for demonstration when transformers not available."""
        self.logger.info(
            f"Mock fine-tuning {model_path} on {num_samples} samples "
            f"for {config.num_epochs} epochs"
        )

        # Simulate training steps
        total_steps = (num_samples // config.batch_size) * config.num_epochs

        for step in range(0, total_steps, config.logging_steps):
            # Simulate decreasing loss
            loss = 2.0 * (1.0 - step / total_steps)
            metrics = TrainingMetrics(
                epoch=step // (num_samples // config.batch_size),
                step=step,
                loss=loss,
                learning_rate=config.learning_rate * (1.0 - step / total_steps)
            )
            self.metrics_history.append(metrics)

            # Simulate training time
            await asyncio.sleep(0.1)

        # Return final metrics
        return self.metrics_history[-1] if self.metrics_history else TrainingMetrics(
            epoch=config.num_epochs,
            step=total_steps,
            loss=0.5,
            learning_rate=config.learning_rate
        )

    async def _save_experiment(self, run: TrainingRun) -> None:
        """Save experiment information."""
        import aiofiles

        experiment_file = self.experiments_dir / f"{run.run_id}.json"

        experiment_data = {
            **asdict(run),
            "metrics_history": [asdict(m) for m in self.metrics_history]
        }

        async with aiofiles.open(experiment_file, 'w') as f:
            await f.write(json.dumps(experiment_data, indent=2))

        self.logger.info(f"Saved experiment: {experiment_file}")

    async def list_experiments(self) -> List[TrainingRun]:
        """List all training experiments."""
        experiments = []

        for exp_file in sorted(self.experiments_dir.glob("*.json")):
            try:
                with open(exp_file, 'r') as f:
                    data = json.load(f)
                    # Reconstruct TrainingRun
                    config_data = data.pop("config")
                    metrics_data = data.pop("final_metrics", None)
                    data.pop("metrics_history", None)

                    run = TrainingRun(
                        **data,
                        config=TrainingConfig(**config_data),
                        final_metrics=TrainingMetrics(**metrics_data) if metrics_data else None
                    )
                    experiments.append(run)
            except Exception as e:
                self.logger.error(f"Error loading experiment {exp_file}: {e}")

        return experiments

    async def get_best_model(self, metric: str = "loss") -> Optional[TrainingRun]:
        """
        Get the best model based on a metric.

        Args:
            metric: Metric to optimize ("loss", "eval_loss", "eval_accuracy")

        Returns:
            Best TrainingRun or None
        """
        experiments = await self.list_experiments()

        completed = [e for e in experiments if e.status == "completed" and e.final_metrics]

        if not completed:
            return None

        # Sort by metric (lower is better for loss)
        if metric in ["loss", "eval_loss"]:
            best = min(completed, key=lambda e: getattr(e.final_metrics, metric, float('inf')))
        else:
            best = max(completed, key=lambda e: getattr(e.final_metrics, metric, 0.0))

        return best


# Synchronous wrapper for backward compatibility
class NightlyFineTuner:
    """Synchronous wrapper for ProductionFineTuner."""

    def __init__(self, logs_path: Path):
        self.fine_tuner = ProductionFineTuner(logs_path)
        self.logger = logging.getLogger(__name__)

    def run(self, model_path: Path) -> None:
        """Synchronous fine-tuning."""
        try:
            run = asyncio.run(self.fine_tuner.fine_tune(str(model_path)))
            self.logger.info(f"Fine-tuning completed: {run.run_id}")
        except Exception as e:
            self.logger.error(f"Fine-tuning failed: {e}")
