"""
Unit Tests for Comprehensive Health Monitoring System

This module provides comprehensive unit tests for the comprehensive health monitoring
system, including testing of health checks, alerting, decision making,
and integration with existing components.
"""

import asyncio
import pytest
import time
import unittest.mock as mock
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, List, Optional, Set

from .comprehensive_health_monitor import (
    HealthStatus, HealthCheckType, AlertLevel, HealthCheckResult,
    HealthThresholds, HealthAlert, HealthTrend, HealthMonitorConfig,
    ComprehensiveHealthMonitor, get_comprehensive_health_monitor
)
from ..integrations.intelligent_provider_registry import ProviderType, ProviderPriority
from ..integrations.capability_aware_selector import SelectionStrategy, RequestContext


class TestComprehensiveHealthMonitor(unittest.TestCase):
    """Test cases for ComprehensiveHealthMonitor."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = HealthMonitorConfig(
            check_interval=1.0,
            trend_analysis_window=300,
            alert_cooldown=5.0,
            max_history_size=50,
            enable_predictive_analysis=True,
            enable_auto_recovery=True,
            thresholds=HealthThresholds(
                healthy_min=0.8,
                degraded_min=0.5,
                critical_response_time=5.0,
                degraded_response_time=2.0,
                cpu_warning=0.7,
                cpu_critical=0.9,
                memory_warning=0.7,
                memory_critical=0.9,
                disk_warning=0.8,
                disk_critical=0.9
            )
        )
        
        # Mock dependencies
        self.mock_network_monitor = MagicMock()
        self.mock_provider_registry = MagicMock()
        self.mock_model_cache = MagicMock()
        self.mock_capability_selector = MagicMock()
        
        # Create monitor with mocked dependencies
        with mock.patch('src.ai_karen_engine.monitoring.comprehensive_health_monitor.get_network_monitor') as mock_get_network:
            with mock.patch('src.ai_karen_engine.monitoring.comprehensive_health_monitor.get_intelligent_provider_registry') as mock_get_registry:
                with mock.patch('src.ai_karen_engine.monitoring.comprehensive_health_monitor.get_model_cache_service') as mock_get_cache:
                    with mock.patch('src.ai_karen_engine.monitoring.comprehensive_health_monitor.get_capability_selector') as mock_get_selector:
                        mock_get_network.return_value = self.mock_network_monitor
                        mock_get_registry.return_value = self.mock_provider_registry
                        mock_get_cache.return_value = self.mock_model_cache
                        mock_get_selector.return_value = self.mock_capability_selector
                        
                        self.monitor = ComprehensiveHealthMonitor(self.config)
    
    def tearDown(self):
        """Clean up after tests."""
        if hasattr(self, 'monitor'):
            asyncio.create_task(self.monitor.stop_monitoring())
    
    def test_initialization(self):
        """Test monitor initialization."""
        self.assertIsNotNone(self.monitor)
        self.assertEqual(self.monitor.config, self.config)
        self.assertIsNotNone(self.monitor._health_monitor)
        self.assertIsNotNone(self.monitor._provider_registry)
        self.assertIsNotNone(self.monitor._capability_selector)
        self.assertIsNotNone(self.monitor._network_monitor)
    
    def test_health_status_enum(self):
        """Test HealthStatus enum values."""
        self.assertEqual(HealthStatus.HEALTHY.value, "healthy")
        self.assertEqual(HealthStatus.DEGRADED.value, "degraded")
        self.assertEqual(HealthStatus.UNHEALTHY.value, "unhealthy")
        self.assertEqual(HealthStatus.UNKNOWN.value, "unknown")
    
    def test_health_check_type_enum(self):
        """Test HealthCheckType enum values."""
        self.assertTrue(hasattr(HealthCheckType, 'NETWORK'))
        self.assertTrue(hasattr(HealthCheckType, 'PROVIDER'))
        self.assertTrue(hasattr(HealthCheckType, 'MODEL'))
        self.assertTrue(hasattr(HealthCheckType, 'SYSTEM'))
        self.assertTrue(hasattr(HealthCheckType, 'RESOURCE'))
    
    def test_alert_level_enum(self):
        """Test AlertLevel enum values."""
        self.assertEqual(AlertLevel.INFO.value, "info")
        self.assertEqual(AlertLevel.WARNING.value, "warning")
        self.assertEqual(AlertLevel.CRITICAL.value, "critical")
    
    def test_health_check_result_creation(self):
        """Test HealthCheckResult creation."""
        result = HealthCheckResult(
            check_type=HealthCheckType.NETWORK,
            component="test",
            status=HealthStatus.HEALTHY,
            score=0.9,
            message="Test result"
        )
        
        self.assertEqual(result.check_type, HealthCheckType.NETWORK)
        self.assertEqual(result.component, "test")
        self.assertEqual(result.status, HealthStatus.HEALTHY)
        self.assertEqual(result.score, 0.9)
        self.assertEqual(result.message, "Test result")
        self.assertIsInstance(result.timestamp, float)
        self.assertIsInstance(result.metrics, dict)
        self.assertIsInstance(result.dependencies, list)
    
    def test_health_thresholds_creation(self):
        """Test HealthThresholds creation."""
        thresholds = HealthThresholds()
        
        self.assertEqual(thresholds.healthy_min, 0.8)
        self.assertEqual(thresholds.degraded_min, 0.5)
        self.assertEqual(thresholds.critical_response_time, 10.0)
        self.assertEqual(thresholds.degraded_response_time, 5.0)
        self.assertEqual(thresholds.cpu_warning, 0.8)
        self.assertEqual(thresholds.cpu_critical, 0.95)
    
    def test_health_alert_creation(self):
        """Test HealthAlert creation."""
        alert = HealthAlert(
            alert_id="test_alert",
            level=AlertLevel.WARNING,
            component="test_component",
            message="Test alert"
        )
        
        self.assertEqual(alert.alert_id, "test_alert")
        self.assertEqual(alert.level, AlertLevel.WARNING)
        self.assertEqual(alert.component, "test_component")
        self.assertEqual(alert.message, "Test alert")
        self.assertIsInstance(alert.timestamp, float)
        self.assertFalse(alert.resolved)
        self.assertIsNone(alert.resolved_timestamp)
        self.assertIsInstance(alert.metadata, dict)
        self.assertIsInstance(alert.triggered_by, list)
    
    async def test_network_health_check(self):
        """Test network health check."""
        # Mock network monitor responses
        self.mock_network_monitor.get_current_status.return_value = HealthStatus.ONLINE
        self.mock_network_monitor.get_network_metrics.return_value = {
            'uptime_percentage': 95.0,
            'average_response_time': 1.5
        }
        
        # Perform network health check
        result = await self.monitor._check_network_health()
        
        # Verify result
        self.assertEqual(result.check_type, HealthCheckType.NETWORK)
        self.assertEqual(result.component, "network")
        self.assertEqual(result.status, HealthStatus.HEALTHY)
        self.assertGreater(result.score, 0.8)
        self.assertIn("optimal", result.message.lower())
        self.assertIsInstance(result.metrics, dict)
        self.assertGreater(result.response_time, 0)
        
        # Verify mock calls
        self.mock_network_monitor.get_current_status.assert_called_once()
        self.mock_network_monitor.get_network_metrics.assert_called_once()
    
    async def test_provider_health_check(self):
        """Test provider health check."""
        # Mock provider registry responses
        mock_metrics = {
            'test_provider': MagicMock(
                success_rate=0.9,
                average_latency=2.0,
                consecutive_failures=0,
                total_requests=100,
                failure_count=10
            )
        }
        self.mock_provider_registry.get_all_provider_metrics.return_value = mock_metrics
        
        # Perform provider health check
        result = await self.monitor._check_provider_health()
        
        # Verify result
        self.assertEqual(result.check_type, HealthCheckType.PROVIDER)
        self.assertEqual(result.component, "providers")
        self.assertEqual(result.status, HealthStatus.HEALTHY)
        self.assertGreater(result.score, 0.8)
        self.assertIn("healthy", result.message.lower())
        self.assertIsInstance(result.metrics, dict)
        
        # Verify mock calls
        self.mock_provider_registry.get_all_provider_metrics.assert_called_once()
    
    async def test_model_health_check(self):
        """Test model health check."""
        # Mock model cache responses
        self.mock_model_cache.get_cache_statistics.return_value = {
            'total_entries': 10,
            'cache_hit_rate': 0.85,
            'preload_success_rate': 0.9,
            'eviction_count': 2,
            'active_downloads': 0
        }
        
        # Perform model health check
        result = await self.monitor._check_model_health()
        
        # Verify result
        self.assertEqual(result.check_type, HealthCheckType.MODEL)
        self.assertEqual(result.component, "models")
        self.assertEqual(result.status, HealthStatus.HEALTHY)
        self.assertGreater(result.score, 0.7)
        self.assertIn("healthy", result.message.lower())
        self.assertIsInstance(result.metrics, dict)
        
        # Verify mock calls
        self.mock_model_cache.get_cache_statistics.assert_called_once()
    
    async def test_system_health_check(self):
        """Test system health check."""
        # Perform system health check
        result = await self.monitor._check_system_health()
        
        # Verify result
        self.assertEqual(result.check_type, HealthCheckType.SYSTEM)
        self.assertEqual(result.component, "system")
        self.assertEqual(result.status, HealthStatus.HEALTHY)
        self.assertGreater(result.score, 0.7)
        self.assertIn("normal", result.message.lower())
        self.assertIsInstance(result.metrics, dict)
        
        # Verify metrics structure
        metrics = result.metrics
        self.assertIn('time_sync_score', metrics)
        self.assertIn('disk_io_score', metrics)
        self.assertIn('process_score', metrics)
    
    async def test_resource_health_check(self):
        """Test resource health check."""
        # Perform resource health check
        result = await self.monitor._check_resource_health()
        
        # Verify result
        self.assertEqual(result.check_type, HealthCheckType.RESOURCE)
        self.assertEqual(result.component, "resources")
        self.assertEqual(result.status, HealthStatus.HEALTHY)
        self.assertGreater(result.score, 0.5)
        self.assertIn("adequate", result.message.lower())
        self.assertIsInstance(result.metrics, dict)
        
        # Verify metrics structure
        metrics = result.metrics
        self.assertIn('cpu_percent', metrics)
        self.assertIn('cpu_score', metrics)
        self.assertIn('memory_percent', metrics)
        self.assertIn('memory_score', metrics)
        self.assertIn('disk_percent', metrics)
        self.assertIn('disk_score', metrics)
        self.assertIn('memory_available_gb', metrics)
        self.assertIn('disk_free_gb', metrics)
    
    async def test_health_score_aggregation(self):
        """Test overall health score aggregation."""
        # Mock component health scores
        self.monitor._health_scores = {
            'NETWORK': 0.9,
            'PROVIDER': 0.8,
            'MODEL': 0.7,
            'SYSTEM': 0.85,
            'RESOURCE': 0.6
        }
        
        # Get overall health
        status, score = self.monitor.get_overall_health()
        
        # Verify weighted calculation (using default weights)
        expected_score = (
            0.9 * 0.25 +  # NETWORK
            0.8 * 0.25 +  # PROVIDER
            0.7 * 0.20 +  # MODEL
            0.85 * 0.15 +  # SYSTEM
            0.6 * 0.15    # RESOURCE
        )
        
        self.assertAlmostEqual(score, expected_score, places=2)
        self.assertEqual(status, HealthStatus.HEALTHY)
    
    def test_alert_triggering(self):
        """Test alert triggering mechanism."""
        # Register test callback
        alerts_received = []
        
        def test_callback(alert: HealthAlert):
            alerts_received.append(alert)
        
        self.monitor.register_alert_callback(test_callback)
        
        # Create a test result that should trigger alert
        test_result = HealthCheckResult(
            check_type=HealthCheckType.NETWORK,
            component="test",
            status=HealthStatus.UNHEALTHY,
            score=0.2,
            message="Critical test failure"
        )
        
        # Trigger alert check
        self.monitor._check_for_alerts({'NETWORK': test_result})
        
        # Verify alert was triggered
        self.assertEqual(len(alerts_received), 1)
        alert = alerts_received[0]
        self.assertEqual(alert.level, AlertLevel.CRITICAL)
        self.assertEqual(alert.component, "test")
        self.assertIn("critical", alert.message.lower())
    
    def test_decision_cooldown(self):
        """Test decision cooldown mechanism."""
        # Set last decision time
        self.monitor._last_decisions['provider_test'] = time.time() - 10  # 10 seconds ago
        
        # Try to make decision (should be in cooldown)
        decision = await self.monitor.make_provider_decision(
            context="test",
            required_capabilities={"test_capability"}
        )
        
        # Decision should be None due to cooldown
        self.assertIsNone(decision)
    
    def test_health_summary(self):
        """Test health summary generation."""
        # Set some health scores
        self.monitor._health_scores = {
            'NETWORK': 0.9,
            'PROVIDER': 0.7,
            'MODEL': 0.8,
            'SYSTEM': 0.85,
            'RESOURCE': 0.6
        }
        
        # Get health summary
        summary = self.monitor.get_health_summary()
        
        # Verify summary structure
        self.assertIn('overall_status', summary)
        self.assertIn('overall_score', summary)
        self.assertIn('last_check', summary)
        self.assertIn('components', summary)
        self.assertIn('active_alerts', summary)
        self.assertIn('trends', summary)
        self.assertIn('monitoring_active', summary)
        
        # Verify component breakdown
        components = summary['components']
        for check_type in HealthCheckType:
            self.assertIn(check_type.name, components)
            component_data = components[check_type.name]
            self.assertIn('status', component_data)
            self.assertIn('score', component_data)
    
    def test_trend_analysis(self):
        """Test trend analysis functionality."""
        # Add some trend data
        self.monitor._trend_data['NETWORK_test'] = [0.8, 0.7, 0.6]
        
        # Check trend analysis
        trends = {}
        for component, trend_deque in self.monitor._trend_data.items():
            if len(trend_deque) >= 3:
                recent_values = list(trend_deque)[-3:]
                if recent_values[-1] > recent_values[-2] > recent_values[-3]:
                    direction = "improving"
                elif recent_values[-1] < recent_values[-2] < recent_values[-3]:
                    direction = "degrading"
                else:
                    direction = "stable"
                
                trends[component] = {
                    'direction': direction,
                    'current': recent_values[-1],
                    'trend': recent_values
                }
        
        self.assertIn('NETWORK_test', trends)
        self.assertEqual(trends['NETWORK_test']['direction'], 'improving')
    
    def test_configuration_from_environment(self):
        """Test configuration loading from environment variables."""
        # This would test actual environment variable loading
        # In a real test environment, you would set environment variables
        # and verify they are loaded correctly
        pass  # Implementation would depend on test environment setup
    
    def test_error_handling(self):
        """Test error handling in health checks."""
        # Mock network monitor to raise exception
        self.mock_network_monitor.get_network_metrics.side_effect = Exception("Network error")
        
        # Perform network health check
        result = await self.monitor._check_network_health()
        
        # Verify error handling
        self.assertEqual(result.check_type, HealthCheckType.NETWORK)
        self.assertEqual(result.component, "network")
        self.assertEqual(result.status, HealthStatus.UNHEALTHY)
        self.assertEqual(result.score, 0.0)
        self.assertIn("error", result.message.lower())
        self.assertEqual(result.error_details, "Network error")
    
    def test_webhook_alert_sending(self):
        """Test webhook alert sending."""
        # This would test actual webhook functionality
        # In a real test, you would mock aiohttp and verify the payload
        pass  # Implementation would depend on test webhook setup


class TestHealthBasedDecisionMaker(unittest.TestCase):
    """Test cases for HealthBasedDecisionMaker."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = DecisionConfig(
            enable_automatic_switching=True,
            enable_predictive_decisions=True,
            enable_graceful_degradation=True,
            max_consecutive_failures=3,
            decision_history_size=10
        )
        
        # Mock dependencies
        self.mock_health_monitor = MagicMock()
        self.mock_provider_registry = MagicMock()
        self.mock_capability_selector = MagicMock()
        self.mock_network_monitor = MagicMock()
        
        # Create decision maker with mocked dependencies
        with mock.patch('src.ai_karen_engine.monitoring.health_based_decision_maker.get_comprehensive_health_monitor') as mock_get_health:
            with mock.patch('src.ai_karen_engine.monitoring.health_based_decision_maker.get_intelligent_provider_registry') as mock_get_registry:
                with mock.patch('src.ai_karen_engine.monitoring.health_based_decision_maker.get_capability_selector') as mock_get_selector:
                    with mock.patch('src.ai_karen_engine.monitoring.health_based_decision_maker.get_network_monitor') as mock_get_network:
                        mock_get_health.return_value = self.mock_health_monitor
                        mock_get_registry.return_value = self.mock_provider_registry
                        mock_get_selector.return_value = self.mock_capability_selector
                        mock_get_network.return_value = self.mock_network_monitor
                        
                        from .health_based_decision_maker import HealthBasedDecisionMaker
                        self.decision_maker = HealthBasedDecisionMaker(self.config)
    
    def tearDown(self):
        """Clean up after tests."""
        if hasattr(self, 'decision_maker'):
            # Clean up any background tasks
            pass
    
    def test_decision_strategy_enum(self):
        """Test DecisionStrategy enum values."""
        self.assertTrue(hasattr(DecisionStrategy, 'HEALTH_FIRST'))
        self.assertTrue(hasattr(DecisionStrategy, 'PERFORMANCE_FIRST'))
        self.assertTrue(hasattr(DecisionStrategy, 'RELIABILITY_FIRST'))
        self.assertTrue(hasattr(DecisionStrategy, 'COST_FIRST'))
        self.assertTrue(hasattr(DecisionStrategy, 'ADAPTIVE'))
    
    def test_decision_trigger_enum(self):
        """Test DecisionTrigger enum values."""
        self.assertTrue(hasattr(DecisionTrigger, 'HEALTH_DEGRADATION'))
        self.assertTrue(hasattr(DecisionTrigger, 'PERFORMANCE_DEGRADATION'))
        self.assertTrue(hasattr(DecisionTrigger, 'PROVIDER_FAILURE'))
        self.assertTrue(hasattr(DecisionTrigger, 'NETWORK_CHANGE'))
        self.assertTrue(hasattr(DecisionTrigger, 'RESOURCE_PRESSURE'))
        self.assertTrue(hasattr(DecisionTrigger, 'PREDICTIVE_FAILURE'))
    
    def test_health_decision_creation(self):
        """Test HealthDecision creation."""
        decision = HealthDecision(
            decision_id="test_decision",
            trigger=DecisionTrigger.HEALTH_DEGRADATION,
            strategy=DecisionStrategy.HEALTH_FIRST,
            action="Test action",
            component="test_component",
            old_provider="old_provider",
            new_provider="new_provider",
            reason="Test reason",
            confidence=0.8,
            metadata={"test": "data"}
        )
        
        self.assertEqual(decision.decision_id, "test_decision")
        self.assertEqual(decision.trigger, DecisionTrigger.HEALTH_DEGRADATION)
        self.assertEqual(decision.strategy, DecisionStrategy.HEALTH_FIRST)
        self.assertEqual(decision.action, "Test action")
        self.assertEqual(decision.component, "test_component")
        self.assertEqual(decision.old_provider, "old_provider")
        self.assertEqual(decision.new_provider, "new_provider")
        self.assertEqual(decision.reason, "Test reason")
        self.assertEqual(decision.confidence, 0.8)
        self.assertIsInstance(decision.timestamp, float)
        self.assertEqual(decision.metadata, {"test": "data"})
        self.assertEqual(decision.expected_impact, "neutral")
        self.assertTrue(decision.rollback_available)
    
    def test_provider_decision_healthy(self):
        """Test provider decision when system is healthy."""
        # Mock healthy system status
        self.mock_health_monitor.get_health_summary.return_value = {
            'overall_status': HealthStatus.HEALTHY.value,
            'overall_score': 0.9,
            'components': {
                'NETWORK': {'status': HealthStatus.HEALTHY.value, 'score': 0.9},
                'PROVIDER': {'status': HealthStatus.HEALTHY.value, 'score': 0.8}
            }
        }
        
        # Mock capability selector to return provider
        mock_provider_score = MagicMock()
        mock_provider_score.total_score = 0.85
        self.mock_capability_selector.select_provider.return_value = ("new_provider", mock_provider_score)
        
        # Make decision
        decision = await self.decision_maker.make_provider_decision(
            context="test",
            required_capabilities={"test_capability"}
        )
        
        # Verify decision
        self.assertIsNotNone(decision)
        self.assertEqual(decision.trigger, DecisionTrigger.HEALTH_DEGRADATION)
        self.assertEqual(decision.strategy, DecisionStrategy.HEALTH_FIRST)
        self.assertIn("Switch", decision.action)
        self.assertEqual(decision.new_provider, "new_provider")
        self.assertGreater(decision.confidence, 0.7)
        self.assertEqual(decision.expected_impact, "positive")
        
        # Verify mock calls
        self.mock_health_monitor.get_health_summary.assert_called_once()
        self.mock_capability_selector.select_provider.assert_called_once()
    
    def test_provider_decision_degraded(self):
        """Test provider decision when system is degraded."""
        # Mock degraded system status
        self.mock_health_monitor.get_health_summary.return_value = {
            'overall_status': HealthStatus.DEGRADED.value,
            'overall_score': 0.6,
            'components': {
                'NETWORK': {'status': HealthStatus.DEGRADED.value, 'score': 0.5},
                'PROVIDER': {'status': HealthStatus.HEALTHY.value, 'score': 0.8}
            }
        }
        
        # Mock capability selector to return provider
        mock_provider_score = MagicMock()
        mock_provider_score.total_score = 0.75
        self.mock_capability_selector.select_provider.return_value = ("reliable_provider", mock_provider_score)
        
        # Make decision
        decision = await self.decision_maker.make_provider_decision(
            context="test",
            required_capabilities={"test_capability"}
        )
        
        # Verify decision
        self.assertIsNotNone(decision)
        self.assertEqual(decision.trigger, DecisionTrigger.HEALTH_DEGRADATION)
        self.assertEqual(decision.strategy, DecisionStrategy.RELIABILITY_FIRST)
        self.assertIn("Switch", decision.action)
        self.assertEqual(decision.new_provider, "reliable_provider")
        self.assertGreater(decision.confidence, 0.5)
        
        # Verify mock calls
        self.mock_health_monitor.get_health_summary.assert_called_once()
        self.mock_capability_selector.select_provider.assert_called_once()
    
    def test_provider_decision_unhealthy(self):
        """Test provider decision when system is unhealthy."""
        # Mock unhealthy system status
        self.mock_health_monitor.get_health_summary.return_value = {
            'overall_status': HealthStatus.UNHEALTHY.value,
            'overall_score': 0.3,
            'components': {
                'NETWORK': {'status': HealthStatus.UNHEALTHY.value, 'score': 0.2},
                'PROVIDER': {'status': HealthStatus.UNHEALTHY.value, 'score': 0.1}
            }
        }
        
        # Mock capability selector to return provider
        mock_provider_score = MagicMock()
        mock_provider_score.total_score = 0.4
        self.mock_capability_selector.select_provider.return_value = ("fallback_provider", mock_provider_score)
        
        # Make decision
        decision = await self.decision_maker.make_provider_decision(
            context="test",
            required_capabilities={"test_capability"}
        )
        
        # Verify decision
        self.assertIsNotNone(decision)
        self.assertEqual(decision.trigger, DecisionTrigger.HEALTH_DEGRADATION)
        self.assertEqual(decision.strategy, DecisionStrategy.HEALTH_FIRST)
        self.assertIn("Switch", decision.action)
        self.assertEqual(decision.new_provider, "fallback_provider")
        self.assertLess(decision.confidence, 0.6)
        
        # Verify mock calls
        self.mock_health_monitor.get_health_summary.assert_called_once()
        self.mock_capability_selector.select_provider.assert_called_once()
    
    def test_fallback_chain_management(self):
        """Test fallback chain management."""
        # Set fallback chain
        fallback_chain = ["primary", "secondary", "tertiary"]
        self.decision_maker.set_fallback_chain("test", fallback_chain)
        
        # Verify fallback chain
        retrieved_chain = self.decision_maker.get_fallback_chain("test")
        self.assertEqual(retrieved_chain, fallback_chain)
        
        # Test fallback chain in decision
        self.mock_health_monitor.get_health_summary.return_value = {
            'overall_status': HealthStatus.UNHEALTHY.value,
            'overall_score': 0.2
        }
        
        # Mock capability selector to return None (no suitable provider)
        self.mock_capability_selector.select_provider.return_value = (None, None)
        
        # Make decision
        decision = await self.decision_maker.make_provider_decision(
            context="test",
            required_capabilities={"test_capability"}
        )
        
        # Verify decision uses fallback chain
        self.assertIsNotNone(decision)
        self.assertEqual(decision.new_provider, "secondary")  # First fallback
        self.assertIn("fallback", decision.action.lower())
    
    def test_decision_history(self):
        """Test decision history tracking."""
        # Make multiple decisions
        decisions = []
        for i in range(5):
            decision = HealthDecision(
                decision_id=f"decision_{i}",
                trigger=DecisionTrigger.HEALTH_DEGRADATION,
                strategy=DecisionStrategy.HEALTH_FIRST,
                action=f"Action {i}",
                component="test",
                confidence=0.8 - (i * 0.1)
            )
            decisions.append(decision)
            self.decision_maker._record_decision(decision)
        
        # Verify history
        history = self.decision_maker.get_decision_history()
        self.assertEqual(len(history), 5)
        
        # Verify analytics
        analytics = self.decision_maker.get_decision_analytics()
        self.assertIn('total_decisions', analytics)
        self.assertIn('trigger_distribution', analytics)
        self.assertIn('strategy_distribution', analytics)
        self.assertIn('impact_distribution', analytics)
        self.assertIn('average_confidence', analytics)
        self.assertIn('recent_decisions', analytics)
    
    def test_graceful_degradation(self):
        """Test graceful degradation execution."""
        # Mock current provider
        self.decision_maker._current_providers["test"] = "current_provider"
        
        # Execute graceful degradation
        decision = await self.decision_maker.execute_graceful_degradation(
            context="test",
            degradation_level=0.5  # Moderate degradation
        )
        
        # Verify decision
        self.assertIsNotNone(decision)
        self.assertEqual(decision.trigger, DecisionTrigger.HEALTH_DEGRADATION)
        self.assertEqual(decision.strategy, DecisionStrategy.RELIABILITY_FIRST)
        self.assertEqual(decision.component, "graceful_degradation")
        self.assertIn("reduce", decision.action.lower())
        self.assertEqual(decision.old_provider, "current_provider")
        self.assertGreater(decision.confidence, 0.4)  # 1.0 - 0.5 = 0.5
        
        # Verify metadata
        self.assertIn('degradation_level', decision.metadata)
        self.assertEqual(decision.metadata['degradation_level'], 0.5)
    
    def test_health_aware_recommendations(self):
        """Test health-aware recommendations generation."""
        # Mock unhealthy system
        self.mock_health_monitor.get_health_summary.return_value = {
            'overall_status': HealthStatus.UNHEALTHY.value,
            'overall_score': 0.3,
            'components': {
                'NETWORK': {'status': HealthStatus.UNHEALTHY.value, 'score': 0.2},
                'RESOURCES': {'status': HealthStatus.UNHEALTHY.value, 'score': 0.1}
            }
        }
        
        # Get recommendations
        recommendations = self.decision_maker.get_health_aware_recommendations()
        
        # Verify recommendations
        self.assertIsInstance(recommendations, dict)
        self.assertIn('overall_status', recommendations)
        self.assertIn('overall_score', recommendations)
        self.assertIn('recommendations', recommendations)
        
        # Check for critical recommendations
        rec_list = recommendations['recommendations']
        critical_recs = [r for r in rec_list if r.get('priority') == 'critical']
        self.assertGreater(len(critical_recs), 0)
        
        # Verify network-specific recommendations
        network_recs = [r for r in rec_list if r.get('category') == 'network']
        self.assertGreater(len(network_recs), 0)


if __name__ == '__main__':
    unittest.main()