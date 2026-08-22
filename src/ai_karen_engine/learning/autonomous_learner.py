"""
spaCy-based autonomous learning engine for the Response Core orchestrator.

This module implements an autonomous learning system that integrates with the existing
spaCy analyzer to continuously improve the system's understanding and responses based
on user interactions and curated data.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
from pathlib import Path
import json
import pickle
import tempfile
import shutil

from ai_karen_engine.core.cortex.analysis import SpacyAnalyzer
from ai_karen_engine.core.memory.signals.spacy_service import SpacyService, ParsedMessage
from ai_karen_engine.core.memory.memory_service import WebUIMemoryService
from ai_karen_engine.core.memory.unified_memory_service import MemoryCommitRequest, MemoryQueryRequest
from ai_karen_engine.core.runtime.resilience import get_feature_flags

logger = logging.getLogger(__name__)


async def _commit_learning_memory(
    *,
    memory_service: WebUIMemoryService,
    tenant_id: Union[str, uuid.UUID],
    user_id: str,
    org_id: Optional[str],
    text: str,
    tags: Optional[List[str]] = None,
    importance: int = 7,
    decay: str = "long",
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Persist learning metadata through the unified memory contract."""
    response = await memory_service.commit(
        tenant_id=tenant_id,
        request=MemoryCommitRequest(
            user_id=user_id,
            org_id=org_id,
            text=text,
            tags=tags or [],
            importance=importance,
            decay=decay,
            metadata=metadata or {},
        ),
    )
    return response.id if response.success else None


async def _query_learning_memories(
    *,
    memory_service: WebUIMemoryService,
    tenant_id: Union[str, uuid.UUID],
    user_id: str,
    org_id: Optional[str],
    query: str,
    top_k: int,
) -> List[Any]:
    """Read learning metadata through the unified memory contract."""
    response = await memory_service.query(
        tenant_id=tenant_id,
        request=MemoryQueryRequest(
            user_id=user_id,
            org_id=org_id,
            query=query,
            top_k=top_k,
            similarity_threshold=0.5,
        ),
    )
    return list(response.hits)


class LearningDataType(str, Enum):
    """Types of learning data for training."""
    CONVERSATION = "conversation"
    USER_FEEDBACK = "user_feedback"
    INTENT_CORRECTION = "intent_correction"
    PERSONA_PREFERENCE = "persona_preference"
    ENTITY_ANNOTATION = "entity_annotation"
    SENTIMENT_CORRECTION = "sentiment_correction"


class TrainingStatus(str, Enum):
    """Status of training operations."""
    PENDING = "pending"
    COLLECTING_DATA = "collecting_data"
    PREPROCESSING = "preprocessing"
    TRAINING = "training"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class ConversationMetadata:
    """Metadata extracted from user conversations."""
    conversation_id: str
    user_id: str
    session_id: Optional[str]
    timestamp: datetime
    intent_detected: str
    sentiment_detected: str
    persona_selected: str
    user_satisfaction: Optional[float] = None
    response_quality: Optional[float] = None
    entities_extracted: List[Tuple[str, str]] = field(default_factory=list)
    linguistic_features: Dict[str, Any] = field(default_factory=dict)
    context_used: List[str] = field(default_factory=list)
    feedback_provided: bool = False
    correction_needed: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "intent_detected": self.intent_detected,
            "sentiment_detected": self.sentiment_detected,
            "persona_selected": self.persona_selected,
            "user_satisfaction": self.user_satisfaction,
            "response_quality": self.response_quality,
            "entities_extracted": self.entities_extracted,
            "linguistic_features": self.linguistic_features,
            "context_used": self.context_used,
            "feedback_provided": self.feedback_provided,
            "correction_needed": self.correction_needed
        }


@dataclass
class TrainingExample:
    """Training example for spaCy model improvement."""
    text: str
    expected_intent: str
    expected_sentiment: str
    expected_entities: List[Tuple[str, str, int, int]] = field(default_factory=list)  # (text, label, start, end)
    expected_persona: Optional[str] = None
    confidence: float = 1.0
    source: LearningDataType = LearningDataType.CONVERSATION
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_spacy_format(self) -> Tuple[str, Dict[str, Any]]:
        """Convert to spaCy training format."""
        entities = []
        for text, label, start, end in self.expected_entities:
            entities.append((start, end, label))
        
        return (self.text, {
            "entities": entities,
            "cats": {
                f"INTENT_{self.expected_intent.upper()}": 1.0,
                f"SENTIMENT_{self.expected_sentiment.upper()}": 1.0
            }
        })


@dataclass
class ValidationResult:
    """Result of model validation."""
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    intent_accuracy: float
    sentiment_accuracy: float
    entity_accuracy: float
    validation_examples: int
    errors: List[Dict[str, Any]] = field(default_factory=list)
    passed_threshold: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "accuracy": self.accuracy,
            "precision": self.precision,
            "recall": self.recall,
            "f1_score": self.f1_score,
            "intent_accuracy": self.intent_accuracy,
            "sentiment_accuracy": self.sentiment_accuracy,
            "entity_accuracy": self.entity_accuracy,
            "validation_examples": self.validation_examples,
            "errors": self.errors,
            "passed_threshold": self.passed_threshold
        }


@dataclass
class LearningCycleResult:
    """Result of a complete learning cycle."""
    cycle_id: str
    started_at: datetime
    completed_at: Optional[datetime]
    status: TrainingStatus
    data_collected: int
    examples_created: int
    training_time: Optional[float] = None
    validation_result: Optional[ValidationResult] = None
    model_improved: bool = False
    rollback_performed: bool = False
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status.value,
            "data_collected": self.data_collected,
            "examples_created": self.examples_created,
            "training_time": self.training_time,
            "validation_result": self.validation_result.to_dict() if self.validation_result else None,
            "model_improved": self.model_improved,
            "rollback_performed": self.rollback_performed,
            "error_message": self.error_message
        }


class ConversationMetadataCollector:
    """Collects and curates conversation metadata for training."""
    
    def __init__(self, memory_service: WebUIMemoryService, spacy_analyzer: SpacyAnalyzer):
        self.memory_service = memory_service
        self.spacy_analyzer = spacy_analyzer
        self.collected_metadata: List[ConversationMetadata] = []
        
    async def collect_from_conversation(
        self,
        tenant_id: Union[str, uuid.UUID],
        user_text: str,
        assistant_response: str,
        user_id: str,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_feedback: Optional[Dict[str, Any]] = None
    ) -> ConversationMetadata:
        """Collect metadata from a single conversation turn."""
        try:
            # Analyze user input
            intent = await self.spacy_analyzer.detect_intent(user_text)
            sentiment = await self.spacy_analyzer.sentiment(user_text)
            entities_data = await self.spacy_analyzer.entities(user_text)
            entities = [(e["text"], e["label"]) for e in entities_data.get("entities", [])]
            
            # Select persona based on analysis
            persona = self.spacy_analyzer.select_persona(intent, sentiment)
            
            # Extract linguistic features
            linguistic_features = entities_data.get("metadata", {})
            
            # Process user feedback if provided
            user_satisfaction = None
            response_quality = None
            correction_needed = False
            
            if user_feedback:
                user_satisfaction = user_feedback.get("satisfaction_score")
                response_quality = user_feedback.get("response_quality")
                correction_needed = user_feedback.get("needs_correction", False)
            
            # Create metadata object
            metadata = ConversationMetadata(
                conversation_id=conversation_id or str(uuid.uuid4()),
                user_id=user_id,
                session_id=session_id,
                timestamp=datetime.utcnow(),
                intent_detected=intent,
                sentiment_detected=sentiment,
                persona_selected=persona,
                user_satisfaction=user_satisfaction,
                response_quality=response_quality,
                entities_extracted=entities,
                linguistic_features=linguistic_features,
                feedback_provided=user_feedback is not None,
                correction_needed=correction_needed
            )
            
            # Store metadata in memory for future training
            await self._store_metadata(tenant_id, metadata)
            
            self.collected_metadata.append(metadata)
            logger.debug(f"Collected conversation metadata: {metadata.conversation_id}")
            
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to collect conversation metadata: {e}")
            raise
    
    async def _store_metadata(self, tenant_id: Union[str, uuid.UUID], metadata: ConversationMetadata):
        """Store conversation metadata in memory system."""
        try:
            content = f"Conversation metadata: Intent={metadata.intent_detected}, " \
                     f"Sentiment={metadata.sentiment_detected}, Persona={metadata.persona_selected}"
            
            await _commit_learning_memory(
                memory_service=self.memory_service,
                tenant_id=tenant_id,
                user_id="system",
                org_id=None,
                text=content,
                tags=["conversation_metadata", "autonomous_learning"],
                importance=7,
                decay="long",
                metadata={
                    **metadata.to_dict(),
                    "source_user_id": metadata.user_id,
                    "record_type": "conversation_metadata",
                }
            )
            
        except Exception as e:
            logger.warning(f"Failed to store conversation metadata: {e}")
    
    async def curate_training_data(
        self,
        tenant_id: Union[str, uuid.UUID],
        min_confidence: float = 0.7,
        max_examples: int = 1000
    ) -> List[ConversationMetadata]:
        """Curate high-quality conversation metadata for training."""
        try:
            memories = await _query_learning_memories(
                memory_service=self.memory_service,
                tenant_id=tenant_id,
                user_id="system",
                org_id=None,
                query="conversation metadata autonomous learning",
                top_k=max_examples,
            )

            # Extract and filter metadata
            curated_metadata = []
            for memory in memories:
                try:
                    metadata_dict = {}
                    if hasattr(memory, "meta") and isinstance(memory.meta, dict):
                        metadata_dict = memory.meta
                    elif hasattr(memory, "metadata") and isinstance(memory.metadata, dict):
                        metadata_dict = memory.metadata
                    if not metadata_dict:
                        continue
                    
                    # Reconstruct metadata object
                    metadata = ConversationMetadata(
                        conversation_id=metadata_dict.get("conversation_id", ""),
                        user_id=metadata_dict.get("source_user_id") or metadata_dict.get("user_id", ""),
                        session_id=metadata_dict.get("session_id"),
                        timestamp=datetime.fromisoformat(metadata_dict.get("timestamp", datetime.utcnow().isoformat())),
                        intent_detected=metadata_dict.get("intent_detected", "general_assist"),
                        sentiment_detected=metadata_dict.get("sentiment_detected", "neutral"),
                        persona_selected=metadata_dict.get("persona_selected", "support-assistant"),
                        user_satisfaction=metadata_dict.get("user_satisfaction"),
                        response_quality=metadata_dict.get("response_quality"),
                        entities_extracted=metadata_dict.get("entities_extracted", []),
                        linguistic_features=metadata_dict.get("linguistic_features", {}),
                        context_used=metadata_dict.get("context_used", []),
                        feedback_provided=metadata_dict.get("feedback_provided", False),
                        correction_needed=metadata_dict.get("correction_needed", False)
                    )
                    
                    # Apply quality filters
                    if self._passes_quality_filters(metadata, min_confidence):
                        curated_metadata.append(metadata)
                        
                except Exception as e:
                    logger.warning(f"Failed to process metadata from memory {memory.id}: {e}")
                    continue
            
            logger.info(f"Curated {len(curated_metadata)} conversation metadata entries")
            return curated_metadata
            
        except Exception as e:
            logger.error(f"Failed to curate training data: {e}")
            return []
    
    def _passes_quality_filters(self, metadata: ConversationMetadata, min_confidence: float) -> bool:
        """Check if metadata passes quality filters for training."""
        # Filter out low-quality interactions
        if metadata.correction_needed:
            return False
        
        # Prefer interactions with user feedback
        if metadata.feedback_provided:
            if metadata.user_satisfaction is not None and metadata.user_satisfaction < min_confidence:
                return False
            if metadata.response_quality is not None and metadata.response_quality < min_confidence:
                return False
        
        # Filter out very short or empty content
        if not metadata.intent_detected or not metadata.sentiment_detected:
            return False
        
        return True


class IncrementalTrainingPipeline:
    """Manages incremental training of spaCy models."""
    
    def __init__(self, spacy_service: SpacyService, model_backup_dir: Optional[Path] = None):
        self.spacy_service = spacy_service
        self.model_backup_dir = model_backup_dir or Path("./model_backups")
        self.model_backup_dir.mkdir(exist_ok=True)
        
        # Training configuration
        self.training_config = {
            "n_iter": 10,
            "batch_size": 32,
            "dropout": 0.2,
            "learn_rate": 0.001,
            "validation_split": 0.2
        }
        
    async def create_training_examples(
        self, 
        metadata_list: List[ConversationMetadata],
        include_corrections: bool = True
    ) -> List[TrainingExample]:
        """Create training examples from conversation metadata."""
        training_examples = []
        
        for metadata in metadata_list:
            try:
                # Create example from conversation metadata
                # Note: We would need the original user text, which should be stored in metadata
                user_text = metadata.linguistic_features.get("original_text", "")
                if not user_text:
                    continue
                
                # Convert entities to spaCy format with positions
                entities_with_positions = []
                for entity_text, entity_label in metadata.entities_extracted:
                    # Find entity positions in text (simple approach)
                    start = user_text.lower().find(entity_text.lower())
                    if start != -1:
                        end = start + len(entity_text)
                        entities_with_positions.append((entity_text, entity_label, start, end))
                
                example = TrainingExample(
                    text=user_text,
                    expected_intent=metadata.intent_detected,
                    expected_sentiment=metadata.sentiment_detected,
                    expected_entities=entities_with_positions,
                    expected_persona=metadata.persona_selected,
                    confidence=metadata.user_satisfaction or 1.0,
                    source=LearningDataType.CONVERSATION,
                    metadata={
                        "conversation_id": metadata.conversation_id,
                        "user_id": metadata.user_id,
                        "timestamp": metadata.timestamp.isoformat()
                    }
                )
                
                training_examples.append(example)
                
            except Exception as e:
                logger.warning(f"Failed to create training example from metadata: {e}")
                continue
        
        logger.info(f"Created {len(training_examples)} training examples")
        return training_examples
    
    async def backup_current_model(self) -> str:
        """Backup current spaCy model."""
        try:
            if not self.spacy_service.nlp:
                raise RuntimeError("No model loaded to backup")
            
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_path = self.model_backup_dir / f"model_backup_{timestamp}"
            backup_path.mkdir(exist_ok=True)
            
            # Save model
            self.spacy_service.nlp.to_disk(backup_path)
            
            # Save metadata
            metadata = {
                "backup_time": timestamp,
                "model_name": self.spacy_service.config.model_name,
                "backup_path": str(backup_path)
            }
            
            with open(backup_path / "backup_metadata.json", "w") as f:
                json.dump(metadata, f, indent=2)
            
            logger.info(f"Model backed up to: {backup_path}")
            return str(backup_path)
            
        except Exception as e:
            logger.error(f"Failed to backup model: {e}")
            raise
    
    async def train_incremental(
        self, 
        training_examples: List[TrainingExample],
        validation_examples: Optional[List[TrainingExample]] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """Perform incremental training on spaCy model."""
        try:
            if not self.spacy_service.nlp:
                raise RuntimeError("No model loaded for training")
            
            # Backup current model
            backup_path = await self.backup_current_model()
            
            # Prepare training data
            train_data = [example.to_spacy_format() for example in training_examples]
            
            # Split data if no validation set provided
            if validation_examples is None:
                split_idx = int(len(train_data) * (1 - self.training_config["validation_split"]))
                train_data, val_data = train_data[:split_idx], train_data[split_idx:]
            else:
                val_data = [example.to_spacy_format() for example in validation_examples]
            
            # Perform training (simplified approach)
            nlp = self.spacy_service.nlp
            
            # Update model with new examples
            # Note: This is a simplified training approach
            # In production, you'd want more sophisticated incremental learning
            
            training_losses = {}
            for i in range(self.training_config["n_iter"]):
                losses = {}
                
                # Batch training
                for batch_start in range(0, len(train_data), self.training_config["batch_size"]):
                    batch = train_data[batch_start:batch_start + self.training_config["batch_size"]]
                    
                    texts, annotations = zip(*batch)
                    nlp.update(texts, annotations, losses=losses, drop=self.training_config["dropout"])
                
                training_losses[f"iter_{i}"] = losses
                logger.debug(f"Training iteration {i}: losses = {losses}")
            
            # Update the service's model
            self.spacy_service.nlp = nlp
            
            training_result = {
                "training_examples": len(training_examples),
                "validation_examples": len(val_data) if val_data else 0,
                "iterations": self.training_config["n_iter"],
                "losses": training_losses,
                "backup_path": backup_path
            }
            
            logger.info("Incremental training completed successfully")
            return True, training_result
            
        except Exception as e:
            logger.error(f"Incremental training failed: {e}")
            return False, {"error": str(e)}
    
    async def rollback_model(self, backup_path: str) -> bool:
        """Rollback to a previous model backup."""
        try:
            backup_dir = Path(backup_path)
            if not backup_dir.exists():
                raise FileNotFoundError(f"Backup path not found: {backup_path}")
            
            # Load backed up model
            try:
                import spacy
                nlp = spacy.load(backup_dir)
            except ImportError:
                logger.error("spaCy not available for model rollback")
                return False
            
            # Update service
            self.spacy_service.nlp = nlp
            self.spacy_service.clear_cache()  # Clear cache to force reprocessing
            
            logger.info(f"Model rolled back from: {backup_path}")
            return True
            
        except Exception as e:
            logger.error(f"Model rollback failed: {e}")
            return False


class ModelValidator:
    """Validates trained models against test data."""
    
    def __init__(self, spacy_analyzer: SpacyAnalyzer):
        self.spacy_analyzer = spacy_analyzer
        
        # Validation thresholds
        self.thresholds = {
            "accuracy": 0.85,
            "intent_accuracy": 0.80,
            "sentiment_accuracy": 0.75,
            "entity_accuracy": 0.70
        }
    
    async def validate_model(
        self, 
        validation_examples: List[TrainingExample],
        detailed_errors: bool = True
    ) -> ValidationResult:
        """Validate model performance against validation examples."""
        try:
            if not validation_examples:
                raise ValueError("No validation examples provided")
            
            total_examples = len(validation_examples)
            correct_predictions = 0
            intent_correct = 0
            sentiment_correct = 0
            entity_correct = 0
            errors = []
            
            for example in validation_examples:
                try:
                    # Get model predictions
                    predicted_intent = await self.spacy_analyzer.detect_intent(example.text)
                    predicted_sentiment = await self.spacy_analyzer.sentiment(example.text)
                    predicted_entities = await self.spacy_analyzer.entities(example.text)
                    
                    # Check intent accuracy
                    intent_match = predicted_intent == example.expected_intent
                    if intent_match:
                        intent_correct += 1
                    
                    # Check sentiment accuracy
                    sentiment_match = predicted_sentiment == example.expected_sentiment
                    if sentiment_match:
                        sentiment_correct += 1
                    
                    # Check entity accuracy (simplified)
                    predicted_entity_texts = {e["text"] for e in predicted_entities.get("entities", [])}
                    expected_entity_texts = {e[0] for e in example.expected_entities}
                    entity_match = predicted_entity_texts == expected_entity_texts
                    if entity_match:
                        entity_correct += 1
                    
                    # Overall correctness
                    if intent_match and sentiment_match and entity_match:
                        correct_predictions += 1
                    elif detailed_errors:
                        errors.append({
                            "text": example.text,
                            "expected_intent": example.expected_intent,
                            "predicted_intent": predicted_intent,
                            "expected_sentiment": example.expected_sentiment,
                            "predicted_sentiment": predicted_sentiment,
                            "expected_entities": expected_entity_texts,
                            "predicted_entities": predicted_entity_texts,
                            "intent_match": intent_match,
                            "sentiment_match": sentiment_match,
                            "entity_match": entity_match
                        })
                
                except Exception as e:
                    logger.warning(f"Validation error for example: {e}")
                    if detailed_errors:
                        errors.append({
                            "text": example.text,
                            "error": str(e)
                        })
            
            # Calculate metrics
            accuracy = correct_predictions / total_examples
            intent_accuracy = intent_correct / total_examples
            sentiment_accuracy = sentiment_correct / total_examples
            entity_accuracy = entity_correct / total_examples
            
            # Simple precision/recall calculation (would need more sophisticated implementation)
            precision = accuracy  # Simplified
            recall = accuracy     # Simplified
            f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
            
            # Check if validation passed
            passed_threshold = (
                accuracy >= self.thresholds["accuracy"] and
                intent_accuracy >= self.thresholds["intent_accuracy"] and
                sentiment_accuracy >= self.thresholds["sentiment_accuracy"] and
                entity_accuracy >= self.thresholds["entity_accuracy"]
            )
            
            result = ValidationResult(
                accuracy=accuracy,
                precision=precision,
                recall=recall,
                f1_score=f1_score,
                intent_accuracy=intent_accuracy,
                sentiment_accuracy=sentiment_accuracy,
                entity_accuracy=entity_accuracy,
                validation_examples=total_examples,
                errors=errors,
                passed_threshold=passed_threshold
            )
            
            logger.info(f"Model validation completed: accuracy={accuracy:.3f}, passed={passed_threshold}")
            return result
            
        except Exception as e:
            logger.error(f"Model validation failed: {e}")
            raise


class AutonomousLearner:
    """
    Main autonomous learning engine that integrates with existing spaCy analyzer.
    
    This class orchestrates the entire learning pipeline:
    1. Collect conversation metadata
    2. Curate training data
    3. Perform incremental training
    4. Validate model improvements
    5. Deploy or rollback based on validation results
    """
    
    def __init__(
        self,
        spacy_analyzer: SpacyAnalyzer,
        memory_service: WebUIMemoryService,
        spacy_service: Optional[SpacyService] = None,
        model_backup_dir: Optional[Path] = None
    ):
        self.spacy_analyzer = spacy_analyzer
        self.memory_service = memory_service
        self.spacy_service = spacy_service or spacy_analyzer.spacy_service
        
        # Initialize components
        self.metadata_collector = ConversationMetadataCollector(memory_service, spacy_analyzer)
        self.training_pipeline = IncrementalTrainingPipeline(self.spacy_service, model_backup_dir)
        self.validator = ModelValidator(spacy_analyzer)
        
        # Learning configuration
        self.learning_config = {
            "min_data_threshold": 50,      # Minimum conversations before training
            "quality_threshold": 0.7,      # Minimum quality score for training data
            "validation_threshold": 0.85,  # Minimum validation score for deployment
            "max_training_examples": 1000, # Maximum examples per training cycle
            "backup_retention_days": 30    # How long to keep model backups
        }
        
        # Learning history
        self.learning_history: List[LearningCycleResult] = []
        
    async def collect_conversation_metadata(
        self,
        tenant_id: Union[str, uuid.UUID],
        user_text: str,
        assistant_response: str,
        user_id: str,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_feedback: Optional[Dict[str, Any]] = None
    ) -> ConversationMetadata:
        """Collect metadata from a conversation for future training."""
        return await self.metadata_collector.collect_from_conversation(
            tenant_id=tenant_id,
            user_text=user_text,
            assistant_response=assistant_response,
            user_id=user_id,
            session_id=session_id,
            conversation_id=conversation_id,
            user_feedback=user_feedback
        )
    
    async def trigger_learning_cycle(
        self, 
        tenant_id: Union[str, uuid.UUID],
        force_training: bool = False
    ) -> LearningCycleResult:
        """Trigger a complete autonomous learning cycle."""
        if not get_feature_flags().is_enabled("autonomous_learning_enabled", tenant_id=tenant_id):
            result = LearningCycleResult(
                cycle_id=str(uuid.uuid4()),
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                status=TrainingStatus.FAILED,
                data_collected=0,
                examples_created=0,
                error_message="autonomous_learning_enabled feature flag is disabled",
            )
            return result
        
        cycle_id = str(uuid.uuid4())
        started_at = datetime.utcnow()
        
        result = LearningCycleResult(
            cycle_id=cycle_id,
            started_at=started_at,
            completed_at=None,
            status=TrainingStatus.PENDING,
            data_collected=0,
            examples_created=0
        )
        
        try:
            logger.info(f"Starting learning cycle: {cycle_id}")
            
            # Step 1: Collect and curate training data
            result.status = TrainingStatus.COLLECTING_DATA
            curated_metadata = await self.metadata_collector.curate_training_data(
                tenant_id=tenant_id,
                min_confidence=self.learning_config["quality_threshold"],
                max_examples=self.learning_config["max_training_examples"]
            )
            
            result.data_collected = len(curated_metadata)
            
            # Check if we have enough data
            if not force_training and len(curated_metadata) < self.learning_config["min_data_threshold"]:
                result.status = TrainingStatus.COMPLETED
                result.completed_at = datetime.utcnow()
                result.error_message = f"Insufficient data for training: {len(curated_metadata)} < {self.learning_config['min_data_threshold']}"
                logger.info(f"Learning cycle {cycle_id} completed: insufficient data")
                return result
            
            # Step 2: Create training examples
            result.status = TrainingStatus.PREPROCESSING
            training_examples = await self.training_pipeline.create_training_examples(curated_metadata)
            result.examples_created = len(training_examples)
            
            if not training_examples:
                result.status = TrainingStatus.FAILED
                result.completed_at = datetime.utcnow()
                result.error_message = "No valid training examples created"
                logger.error(f"Learning cycle {cycle_id} failed: no training examples")
                return result
            
            # Step 3: Split data for training and validation
            split_idx = int(len(training_examples) * 0.8)
            train_examples = training_examples[:split_idx]
            val_examples = training_examples[split_idx:]
            
            # Step 4: Perform incremental training
            result.status = TrainingStatus.TRAINING
            training_start = datetime.utcnow()
            
            training_success, training_result = await self.training_pipeline.train_incremental(
                training_examples=train_examples,
                validation_examples=val_examples
            )
            
            result.training_time = (datetime.utcnow() - training_start).total_seconds()
            
            if not training_success:
                result.status = TrainingStatus.FAILED
                result.completed_at = datetime.utcnow()
                result.error_message = training_result.get("error", "Training failed")
                logger.error(f"Learning cycle {cycle_id} failed: training error")
                return result
            
            # Step 5: Validate model
            result.status = TrainingStatus.VALIDATING
            validation_result = await self.validator.validate_model(val_examples)
            result.validation_result = validation_result
            
            # Step 6: Decide whether to deploy or rollback
            if validation_result.passed_threshold:
                result.model_improved = True
                result.status = TrainingStatus.COMPLETED
                logger.info(f"Learning cycle {cycle_id} completed successfully: model improved")
            else:
                # Rollback to previous model
                backup_path = training_result.get("backup_path")
                if backup_path:
                    rollback_success = await self.training_pipeline.rollback_model(backup_path)
                    result.rollback_performed = rollback_success
                    if rollback_success:
                        logger.info(f"Learning cycle {cycle_id}: model rolled back due to poor validation")
                    else:
                        logger.error(f"Learning cycle {cycle_id}: rollback failed")
                
                result.status = TrainingStatus.ROLLED_BACK
                result.error_message = f"Validation failed: accuracy={validation_result.accuracy:.3f} < {self.learning_config['validation_threshold']}"
            
            result.completed_at = datetime.utcnow()
            
        except Exception as e:
            result.status = TrainingStatus.FAILED
            result.completed_at = datetime.utcnow()
            result.error_message = str(e)
            logger.error(f"Learning cycle {cycle_id} failed with exception: {e}")
        
        # Store result in history
        self.learning_history.append(result)
        
        # Store result in memory system for tracking
        await self._store_learning_result(tenant_id, result)
        
        return result
    
    async def get_learning_metrics(self) -> Dict[str, Any]:
        """Get comprehensive learning metrics and history."""
        if not self.learning_history:
            return {
                "total_cycles": 0,
                "successful_cycles": 0,
                "failed_cycles": 0,
                "average_training_time": 0,
                "last_cycle": None,
                "model_improvements": 0
            }
        
        successful_cycles = [r for r in self.learning_history if r.status == TrainingStatus.COMPLETED and r.model_improved]
        failed_cycles = [r for r in self.learning_history if r.status == TrainingStatus.FAILED]
        
        training_times = [r.training_time for r in self.learning_history if r.training_time is not None]
        avg_training_time = sum(training_times) / len(training_times) if training_times else 0
        
        return {
            "total_cycles": len(self.learning_history),
            "successful_cycles": len(successful_cycles),
            "failed_cycles": len(failed_cycles),
            "average_training_time": avg_training_time,
            "last_cycle": self.learning_history[-1].to_dict() if self.learning_history else None,
            "model_improvements": len(successful_cycles),
            "recent_cycles": [r.to_dict() for r in self.learning_history[-5:]],  # Last 5 cycles
            "learning_config": self.learning_config.copy()
        }
    
    async def _store_learning_result(self, tenant_id: Union[str, uuid.UUID], result: LearningCycleResult):
        """Store learning cycle result in memory system."""
        try:
            content = f"Autonomous learning cycle {result.cycle_id}: {result.status.value}"
            if result.model_improved:
                content += " - Model improved"
            
            await _commit_learning_memory(
                memory_service=self.memory_service,
                tenant_id=tenant_id,
                user_id="system",
                org_id=None,
                text=content,
                tags=["autonomous_learning", "model_training", result.status.value],
                importance=8 if result.model_improved else 6,
                decay="long",
                metadata=result.to_dict()
            )
            
        except Exception as e:
            logger.warning(f"Failed to store learning result: {e}")


def create_autonomous_learner(
    spacy_analyzer: SpacyAnalyzer,
    memory_service: WebUIMemoryService,
    spacy_service: Optional[SpacyService] = None,
    model_backup_dir: Optional[Path] = None
) -> AutonomousLearner:
    """
    Factory function to create an AutonomousLearner instance.
    
    Args:
        spacy_analyzer: SpacyAnalyzer instance for integration
        memory_service: WebUIMemoryService for data storage and retrieval
        spacy_service: Optional SpacyService instance
        model_backup_dir: Optional directory for model backups
        
    Returns:
        Configured AutonomousLearner instance
    """
    return AutonomousLearner(
        spacy_analyzer=spacy_analyzer,
        memory_service=memory_service,
        spacy_service=spacy_service,
        model_backup_dir=model_backup_dir
    )
