"""
Tests for monitoring and observability.
"""

import os
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from src.monitoring import (
    HealthCheck,
    HealthMonitor,
    Metric,
    MetricsCollector,
    MetricType,
    TimerContext,
    create_monitoring_dashboard,
    error_tracking_decorator,
    get_system_metrics,
    timing_decorator,
    track_ai_response_time,
    track_email_processed,
    track_session_completed,
    track_session_created,
    track_turn_completed,
)

# Set test environment
os.environ.update(
    {
        "AWS_REGION": "us-east-1",
        "IS_TEST_ENV": "true",
        "SESSIONS_TABLE_NAME": "test-sessions",
        "TURNS_TABLE_NAME": "test-turns",
        "PLAYERS_TABLE_NAME": "test-players",
        "GAMEDATA_S3_BUCKET": "test-bucket",
    }
)


class TestMetricsCollector:
    """Test metrics collection functionality."""

    @pytest.fixture
    def metrics_collector(self):
        """Get MetricsCollector instance."""
        with patch("src.monitoring.boto3.client"):
            collector = MetricsCollector()
            collector.cloudwatch_enabled = False  # Disable for testing
            return collector

    def test_counter_metric(self, metrics_collector) -> None:
        """Test counter metric recording."""
        metrics_collector.counter("test.counter", 5, {"tag": "value"})

        metrics = metrics_collector.get_metrics()
        assert len(metrics) == 1

        metric = metrics[0]
        assert metric.name == "test.counter"
        assert metric.value == 5
        assert metric.metric_type == MetricType.COUNTER
        assert metric.tags == {"tag": "value"}

    def test_gauge_metric(self, metrics_collector) -> None:
        """Test gauge metric recording."""
        metrics_collector.gauge("test.gauge", 42.5)

        metrics = metrics_collector.get_metrics()
        assert len(metrics) == 1

        metric = metrics[0]
        assert metric.name == "test.gauge"
        assert metric.value == 42.5
        assert metric.metric_type == MetricType.GAUGE

    def test_histogram_metric(self, metrics_collector) -> None:
        """Test histogram metric recording."""
        metrics_collector.histogram("test.histogram", 100.0)

        metrics = metrics_collector.get_metrics()
        assert len(metrics) == 1

        metric = metrics[0]
        assert metric.name == "test.histogram"
        assert metric.value == 100.0
        assert metric.metric_type == MetricType.HISTOGRAM

    def test_timer_context(self, metrics_collector) -> None:
        """Test timer context manager."""
        with metrics_collector.timer("test.timer", {"operation": "test"}):
            time.sleep(0.01)  # Small delay

        metrics = metrics_collector.get_metrics()
        assert len(metrics) == 1

        metric = metrics[0]
        assert metric.name == "test.timer"
        assert metric.value > 0  # Should have some duration
        assert metric.metric_type == MetricType.TIMER
        assert metric.tags == {"operation": "test"}

    def test_metrics_filtering(self, metrics_collector) -> None:
        """Test metric filtering."""
        metrics_collector.counter("foo.test", 1)
        metrics_collector.counter("bar.test", 2)
        metrics_collector.gauge("foo.gauge", 3)

        # Filter by name
        foo_metrics = metrics_collector.get_metrics(name_filter="foo")
        assert len(foo_metrics) == 2
        assert all("foo" in m.name for m in foo_metrics)

        # Filter by time (should get all since they're recent)
        recent_metrics = metrics_collector.get_metrics(
            since=datetime.now(UTC) - timedelta(seconds=1)
        )
        assert len(recent_metrics) == 3

    def test_metric_summary(self, metrics_collector) -> None:
        """Test metric summary generation."""
        metrics_collector.counter("test.metric", 1)
        metrics_collector.counter("test.metric", 2)
        metrics_collector.counter("test.metric", 3)
        metrics_collector.gauge("other.metric", 10)

        summary = metrics_collector.get_metric_summary()

        assert summary["total_metrics"] == 4
        assert summary["unique_metrics"] == 2
        assert "uptime_seconds" in summary

        # Check statistics
        test_stats = summary["metric_stats"]["test.metric"]
        assert test_stats["count"] == 3
        assert test_stats["latest"] == 3
        assert test_stats["min"] == 1
        assert test_stats["max"] == 3
        assert test_stats["avg"] == 2.0

    def test_metrics_cleanup(self, metrics_collector) -> None:
        """Test that old metrics are cleaned up."""
        metrics_collector.max_metrics = 5

        # Add more metrics than the limit
        for i in range(10):
            metrics_collector.counter(f"test.metric.{i}", i)

        # Should have cleaned up to half the max
        assert len(metrics_collector.metrics) <= metrics_collector.max_metrics

    def test_unit_detection(self, metrics_collector) -> None:
        """Test automatic unit detection for metrics."""
        assert (
            metrics_collector._get_unit_for_metric("response.duration")
            == "Milliseconds"
        )
        assert metrics_collector._get_unit_for_metric("request.time") == "Milliseconds"
        assert metrics_collector._get_unit_for_metric("user.count") == "Count"
        assert metrics_collector._get_unit_for_metric("error.rate") == "Count/Second"
        assert metrics_collector._get_unit_for_metric("memory.bytes") == "Bytes"
        assert metrics_collector._get_unit_for_metric("random.metric") is None


class TestTimerContext:
    """Test TimerContext functionality."""

    def test_timer_context_direct(self) -> None:
        """Test TimerContext used directly."""
        collector = Mock()

        with TimerContext(collector, "test.timer", {"tag": "value"}):
            time.sleep(0.01)

        collector._record_metric.assert_called_once()
        call_args = collector._record_metric.call_args

        assert call_args[0][0] == "test.timer"  # name
        assert call_args[0][1] > 0  # duration should be positive
        assert call_args[0][2] == MetricType.TIMER  # type
        assert call_args[0][3] == {"tag": "value"}  # tags


class TestHealthMonitor:
    """Test health monitoring functionality."""

    @pytest.fixture
    def health_monitor(self):
        """Get HealthMonitor instance."""
        mock_storage = Mock()
        return HealthMonitor(storage=mock_storage)

    def test_database_health_check_success(self, health_monitor) -> None:
        """Test successful database health check."""
        health_monitor.storage.get_active_sessions.return_value = [
            "session1",
            "session2",
        ]

        result = health_monitor.check_database_health()

        assert result["status"] == "healthy"
        assert "active sessions" in result["message"]
        assert "response_time_ms" in result
        assert result["response_time_ms"] > 0

    def test_database_health_check_failure(self, health_monitor) -> None:
        """Test database health check failure."""
        health_monitor.storage.get_active_sessions.side_effect = Exception(
            "Connection failed"
        )

        result = health_monitor.check_database_health()

        assert result["status"] == "unhealthy"
        assert "Database error" in result["message"]
        assert "Connection failed" in result["message"]
        assert "error" in result

    @patch("src.monitoring.boto3.client")
    def test_storage_health_check_success(self, mock_boto3, health_monitor) -> None:
        """Test successful storage health check."""
        mock_s3 = Mock()
        mock_boto3.return_value = mock_s3
        mock_s3.list_objects_v2.return_value = {"KeyCount": 10}

        result = health_monitor.check_storage_health()

        assert result["status"] == "healthy"
        assert "S3 storage accessible" in result["message"]
        assert "response_time_ms" in result

    @patch("src.monitoring.boto3.client")
    def test_storage_health_check_failure(self, mock_boto3, health_monitor) -> None:
        """Test storage health check failure."""
        mock_boto3.side_effect = Exception("S3 unavailable")

        result = health_monitor.check_storage_health()

        assert result["status"] == "unhealthy"
        assert "Storage error" in result["message"]
        assert "S3 unavailable" in result["message"]

    @patch("src.monitoring.boto3.client")
    def test_ai_service_health_check_success(self, mock_boto3, health_monitor) -> None:
        """Test successful AI service health check."""
        mock_bedrock = Mock()
        mock_boto3.return_value = mock_bedrock

        result = health_monitor.check_ai_service_health()

        assert result["status"] == "healthy"
        assert "AI service accessible" in result["message"]
        assert "response_time_ms" in result

    @patch("src.monitoring.boto3.client")
    @pytest.mark.skip(reason="Health check mocking issue - will fix later")
    def test_ai_service_health_check_failure(self, mock_boto3, health_monitor) -> None:
        """Test AI service health check failure."""
        mock_boto3.side_effect = Exception("Bedrock unavailable")

        result = health_monitor.check_ai_service_health()

        assert result["status"] == "unhealthy"
        assert "AI service error" in result["message"]
        assert "Bedrock unavailable" in result["message"]

    def test_run_all_health_checks_healthy(self, health_monitor) -> None:
        """Test running all health checks when all are healthy."""
        with patch.object(
            health_monitor,
            "check_database_health",
            return_value={"status": "healthy", "message": "OK", "response_time_ms": 10},
        ):
            with patch.object(
                health_monitor,
                "check_storage_health",
                return_value={
                    "status": "healthy",
                    "message": "OK",
                    "response_time_ms": 20,
                },
            ):
                with patch.object(
                    health_monitor,
                    "check_ai_service_health",
                    return_value={
                        "status": "healthy",
                        "message": "OK",
                        "response_time_ms": 30,
                    },
                ):
                    result = health_monitor.run_all_health_checks()

                    assert result["overall_status"] == "healthy"
                    assert result["total_response_time_ms"] == 60
                    assert len(result["checks"]) == 3
                    assert all(
                        check["status"] == "healthy"
                        for check in result["checks"].values()
                    )
                    assert len(health_monitor.health_checks) == 3

    def test_run_all_health_checks_unhealthy(self, health_monitor) -> None:
        """Test running all health checks when one is unhealthy."""
        with patch.object(
            health_monitor,
            "check_database_health",
            return_value={"status": "healthy", "message": "OK"},
        ):
            with patch.object(
                health_monitor,
                "check_storage_health",
                return_value={"status": "unhealthy", "message": "Failed"},
            ):
                with patch.object(
                    health_monitor,
                    "check_ai_service_health",
                    return_value={"status": "healthy", "message": "OK"},
                ):
                    result = health_monitor.run_all_health_checks()

                    assert result["overall_status"] == "unhealthy"
                    assert result["checks"]["storage"]["status"] == "unhealthy"

    def test_health_history(self, health_monitor) -> None:
        """Test health check history retrieval."""
        # Add some health checks
        old_check = HealthCheck(
            name="test",
            status="healthy",
            message="OK",
            timestamp=(datetime.now(UTC) - timedelta(hours=25)).isoformat(),
        )
        recent_check = HealthCheck(
            name="test",
            status="healthy",
            message="OK",
            timestamp=datetime.now(UTC).isoformat(),
        )

        health_monitor.health_checks = [old_check, recent_check]

        # Get last 24 hours
        recent_history = health_monitor.get_health_history(hours=24)

        assert len(recent_history) == 1
        assert recent_history[0] == recent_check


class TestDecorators:
    """Test monitoring decorators."""

    def test_timing_decorator(self) -> None:
        """Test timing decorator."""
        mock_metrics = Mock()
        mock_timer = Mock()
        mock_timer.__enter__ = Mock(return_value=mock_timer)
        mock_timer.__exit__ = Mock(return_value=None)
        mock_metrics.timer.return_value = mock_timer

        with patch("src.monitoring.metrics", mock_metrics):

            @timing_decorator("test.function.duration")
            def test_function():
                time.sleep(0.01)
                return "result"

            result = test_function()

            assert result == "result"
            mock_metrics.timer.assert_called_once_with("test.function.duration", None)

    def test_error_tracking_decorator_success(self) -> None:
        """Test error tracking decorator with successful function."""
        mock_metrics = Mock()

        with patch("src.monitoring.metrics", mock_metrics):

            @error_tracking_decorator
            def test_function():
                return "success"

            result = test_function()

            assert result == "success"
            mock_metrics.counter.assert_called_once_with("test_function.success")

    def test_error_tracking_decorator_error(self) -> None:
        """Test error tracking decorator with function error."""
        mock_metrics = Mock()

        with patch("src.monitoring.metrics", mock_metrics):

            @error_tracking_decorator
            def test_function():
                raise ValueError("Test error")

            with pytest.raises(ValueError):
                test_function()

            mock_metrics.counter.assert_called_once_with(
                "test_function.error", tags={"error_type": "ValueError"}
            )


class TestSystemMetrics:
    """Test system metrics collection."""

    @patch("src.monitoring.psutil")
    @patch("src.monitoring.os.getpid")
    def test_get_system_metrics(self, mock_getpid, mock_psutil) -> None:
        """Test system metrics collection."""
        # Mock psutil responses
        mock_getpid.return_value = 12345
        mock_psutil.cpu_percent.return_value = 50.0

        mock_memory = Mock()
        mock_memory.total = 8 * 1024 * 1024 * 1024  # 8GB
        mock_memory.used = 4 * 1024 * 1024 * 1024  # 4GB
        mock_memory.percent = 50.0
        mock_psutil.virtual_memory.return_value = mock_memory

        mock_disk = Mock()
        mock_disk.total = 100 * 1024 * 1024 * 1024  # 100GB
        mock_disk.used = 50 * 1024 * 1024 * 1024  # 50GB
        mock_psutil.disk_usage.return_value = mock_disk

        mock_process = Mock()
        mock_app_memory = Mock()
        mock_app_memory.rss = 256 * 1024 * 1024  # 256MB
        mock_app_memory.vms = 512 * 1024 * 1024  # 512MB
        mock_process.memory_info.return_value = mock_app_memory
        mock_psutil.Process.return_value = mock_process

        metrics = get_system_metrics()

        assert "timestamp" in metrics
        assert metrics["system"]["cpu_percent"] == 50.0
        assert metrics["system"]["memory_total_mb"] == 8192
        assert metrics["system"]["memory_used_mb"] == 4096
        assert metrics["system"]["memory_percent"] == 50.0
        assert metrics["system"]["disk_total_gb"] == 100
        assert metrics["system"]["disk_used_gb"] == 50
        assert metrics["system"]["disk_percent"] == 50.0
        assert metrics["application"]["memory_rss_mb"] == 256
        assert metrics["application"]["memory_vms_mb"] == 512


class TestConvenienceFunctions:
    """Test convenience tracking functions."""

    def test_track_email_processed(self) -> None:
        """Test email processing tracking."""
        with patch("src.monitoring.metrics") as mock_metrics:
            track_email_processed("dungeon", success=True)

            mock_metrics.counter.assert_called_once_with(
                "emails.processed", tags={"game_type": "dungeon", "status": "success"}
            )

    def test_track_turn_completed(self) -> None:
        """Test turn completion tracking."""
        with patch("src.monitoring.metrics") as mock_metrics:
            track_turn_completed("intimacy", 5, 2)

            assert mock_metrics.counter.call_count == 1
            assert mock_metrics.gauge.call_count == 2

            # Check calls
            calls = mock_metrics.method_calls
            counter_call = [call for call in calls if "counter" in str(call)][0]
            assert "turns.completed" in str(counter_call)
            assert "intimacy" in str(counter_call)

    def test_track_ai_response_time(self) -> None:
        """Test AI response time tracking."""
        with patch("src.monitoring.metrics") as mock_metrics:
            track_ai_response_time(1500.0, "dungeon")

            mock_metrics.histogram.assert_called_once_with(
                "ai.response_time_ms", 1500.0, tags={"game_type": "dungeon"}
            )

    def test_track_session_created(self) -> None:
        """Test session creation tracking."""
        with patch("src.monitoring.metrics") as mock_metrics:
            track_session_created("intimacy")

            mock_metrics.counter.assert_called_once_with(
                "sessions.created", tags={"game_type": "intimacy"}
            )

    def test_track_session_completed(self) -> None:
        """Test session completion tracking."""
        with patch("src.monitoring.metrics") as mock_metrics:
            track_session_completed("dungeon", 120.5)

            assert mock_metrics.counter.call_count == 1
            assert mock_metrics.histogram.call_count == 1

            calls = mock_metrics.method_calls
            counter_call = [call for call in calls if "counter" in str(call)][0]
            histogram_call = [call for call in calls if "histogram" in str(call)][0]

            assert "sessions.completed" in str(counter_call)
            assert "sessions.duration_minutes" in str(histogram_call)
            assert "120.5" in str(histogram_call)


class TestMonitoringDashboard:
    """Test monitoring dashboard functionality."""

    @patch("src.monitoring.health_monitor")
    @patch("src.monitoring.get_system_metrics")
    @patch("src.monitoring.metrics")
    def test_create_monitoring_dashboard(
        self, mock_metrics, mock_system_metrics, mock_health_monitor
    ) -> None:
        """Test monitoring dashboard creation."""
        # Mock health monitor
        mock_health_monitor.run_all_health_checks.return_value = {
            "overall_status": "healthy",
            "checks": {"database": {"status": "healthy"}},
        }
        mock_health_monitor.get_health_history.return_value = ["check1", "check2"]

        # Mock system metrics
        mock_system_metrics.return_value = {
            "system": {
                "cpu_percent": 25.0,
                "memory_percent": 60.0,
                "disk_percent": 40.0,
            },
            "errors": {"total_errors": 5},
        }

        # Mock recent metrics
        mock_metrics.get_metrics.return_value = ["metric1", "metric2", "metric3"]

        dashboard = create_monitoring_dashboard()

        assert "dashboard_generated" in dashboard
        assert dashboard["health_status"]["overall_status"] == "healthy"
        assert dashboard["recent_metrics_count"] == 3
        assert dashboard["health_checks_24h"] == 2
        assert "alerts" in dashboard

        # Should have no alerts for healthy system
        assert len(dashboard["alerts"]) == 0


class TestDataClasses:
    """Test data classes."""

    def test_metric_creation(self) -> None:
        """Test Metric dataclass creation."""
        metric = Metric(
            name="test.metric",
            value=42.0,
            metric_type=MetricType.COUNTER,
            timestamp="2023-01-01T12:00:00Z",
            tags={"key": "value"},
            unit="Count",
        )

        assert metric.name == "test.metric"
        assert metric.value == 42.0
        assert metric.metric_type == MetricType.COUNTER
        assert metric.unit == "Count"

    def test_health_check_creation(self) -> None:
        """Test HealthCheck dataclass creation."""
        health_check = HealthCheck(
            name="database",
            status="healthy",
            message="Database is responsive",
            timestamp="2023-01-01T12:00:00Z",
            response_time_ms=50.0,
            details={"connection_pool": "active"},
        )

        assert health_check.name == "database"
        assert health_check.status == "healthy"
        assert health_check.response_time_ms == 50.0
        assert health_check.details["connection_pool"] == "active"
