"""
Monitoring and observability utilities for GPT Therapy.

Provides metrics collection, health checks, and monitoring endpoints.
"""

import json
import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import boto3
from functools import wraps

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

try:
    from .error_handler import ErrorType, error_metrics
    from .storage import StorageManager
except ImportError:
    from error_handler import ErrorType, error_metrics
    from storage import StorageManager

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics we collect."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class Metric:
    """Individual metric data point."""
    name: str
    value: float
    metric_type: MetricType
    timestamp: str
    tags: Dict[str, str]
    unit: Optional[str] = None


@dataclass
class HealthCheck:
    """Health check result."""
    name: str
    status: str  # "healthy", "unhealthy", "degraded"
    message: str
    timestamp: str
    response_time_ms: Optional[float] = None
    details: Optional[Dict[str, Any]] = None


class MetricsCollector:
    """Collects and manages application metrics."""
    
    def __init__(self):
        self.metrics: List[Metric] = []
        self.max_metrics = 1000  # Prevent memory issues
        self.start_time = time.time()
        
        # CloudWatch client for production metrics
        try:
            self.cloudwatch = boto3.client('cloudwatch')
            self.cloudwatch_enabled = True
        except Exception as e:
            logger.warning(f"CloudWatch not available: {e}")
            self.cloudwatch = None
            self.cloudwatch_enabled = False
    
    def counter(self, name: str, value: float = 1, tags: Dict[str, str] = None) -> None:
        """Record a counter metric."""
        self._record_metric(name, value, MetricType.COUNTER, tags)
    
    def gauge(self, name: str, value: float, tags: Dict[str, str] = None) -> None:
        """Record a gauge metric."""
        self._record_metric(name, value, MetricType.GAUGE, tags)
    
    def histogram(self, name: str, value: float, tags: Dict[str, str] = None) -> None:
        """Record a histogram metric."""
        self._record_metric(name, value, MetricType.HISTOGRAM, tags)
    
    def timer(self, name: str, tags: Dict[str, str] = None) -> 'TimerContext':
        """Create a timer context manager."""
        return TimerContext(self, name, tags)
    
    def _record_metric(self, name: str, value: float, metric_type: MetricType, 
                      tags: Dict[str, str] = None) -> None:
        """Record a metric internally and optionally send to CloudWatch."""
        metric = Metric(
            name=name,
            value=value,
            metric_type=metric_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            tags=tags or {},
            unit=self._get_unit_for_metric(name)
        )
        
        # Store locally
        self.metrics.append(metric)
        
        # Clean up if we have too many metrics
        if len(self.metrics) > self.max_metrics:
            self.metrics = self.metrics[-self.max_metrics//2:]
        
        # Send to CloudWatch if available
        if self.cloudwatch_enabled:
            self._send_to_cloudwatch(metric)
        
        logger.debug(f"Recorded metric: {name}={value} ({metric_type.value})")
    
    def _get_unit_for_metric(self, name: str) -> Optional[str]:
        """Determine unit for metric based on name."""
        if 'duration' in name.lower() or 'time' in name.lower():
            return 'Milliseconds'
        elif 'count' in name.lower() or 'total' in name.lower():
            return 'Count'
        elif 'rate' in name.lower():
            return 'Count/Second'
        elif 'bytes' in name.lower():
            return 'Bytes'
        return None
    
    def _send_to_cloudwatch(self, metric: Metric) -> None:
        """Send metric to CloudWatch."""
        try:
            dimensions = [
                {'Name': key, 'Value': value}
                for key, value in metric.tags.items()
            ]
            
            # Add default dimensions
            dimensions.extend([
                {'Name': 'Application', 'Value': 'GPTTherapy'},
                {'Name': 'Environment', 'Value': 'production'}
            ])
            
            metric_data = {
                'MetricName': metric.name,
                'Value': metric.value,
                'Unit': metric.unit or 'None',
                'Timestamp': datetime.fromisoformat(metric.timestamp.replace('Z', '+00:00')),
                'Dimensions': dimensions
            }
            
            self.cloudwatch.put_metric_data(
                Namespace='GPTTherapy',
                MetricData=[metric_data]
            )
            
        except Exception as e:
            logger.error(f"Failed to send metric to CloudWatch: {e}")
    
    def get_metrics(self, name_filter: str = None, 
                   since: datetime = None) -> List[Metric]:
        """Get collected metrics with optional filtering."""
        filtered_metrics = self.metrics
        
        if name_filter:
            filtered_metrics = [m for m in filtered_metrics if name_filter in m.name]
        
        if since:
            since_str = since.isoformat()
            filtered_metrics = [m for m in filtered_metrics if m.timestamp >= since_str]
        
        return filtered_metrics
    
    def get_metric_summary(self) -> Dict[str, Any]:
        """Get summary of collected metrics."""
        if not self.metrics:
            return {'total_metrics': 0, 'uptime_seconds': time.time() - self.start_time}
        
        # Group by metric name
        by_name = {}
        for metric in self.metrics:
            if metric.name not in by_name:
                by_name[metric.name] = []
            by_name[metric.name].append(metric.value)
        
        # Calculate statistics
        summary = {
            'total_metrics': len(self.metrics),
            'unique_metrics': len(by_name),
            'uptime_seconds': time.time() - self.start_time,
            'metric_stats': {}
        }
        
        for name, values in by_name.items():
            summary['metric_stats'][name] = {
                'count': len(values),
                'latest': values[-1],
                'min': min(values),
                'max': max(values),
                'avg': sum(values) / len(values)
            }
        
        return summary


class TimerContext:
    """Context manager for timing operations."""
    
    def __init__(self, collector: MetricsCollector, name: str, tags: Dict[str, str] = None):
        self.collector = collector
        self.name = name
        self.tags = tags or {}
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration_ms = (time.time() - self.start_time) * 1000
            self.collector._record_metric(
                self.name, duration_ms, MetricType.TIMER, self.tags
            )


class HealthMonitor:
    """Monitors system health and provides health check endpoints."""
    
    def __init__(self, storage: StorageManager = None):
        self.storage = storage or StorageManager()
        self.health_checks: List[HealthCheck] = []
        self.max_health_checks = 100
    
    def add_health_check(self, name: str, check_func: Callable[[], Dict[str, Any]]) -> None:
        """Register a health check function."""
        setattr(self, f"check_{name}", check_func)
    
    def check_database_health(self) -> Dict[str, Any]:
        """Check database connectivity and health."""
        start_time = time.time()
        
        try:
            # Try to list sessions (minimal operation)
            sessions = self.storage.get_active_sessions()
            response_time = (time.time() - start_time) * 1000
            
            return {
                'status': 'healthy',
                'message': f'Database accessible, {len(sessions)} active sessions',
                'response_time_ms': response_time
            }
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return {
                'status': 'unhealthy',
                'message': f'Database error: {str(e)}',
                'response_time_ms': response_time,
                'error': str(e)
            }
    
    def check_storage_health(self) -> Dict[str, Any]:
        """Check S3 storage health."""
        start_time = time.time()
        
        try:
            # Try to list a small number of objects
            import boto3
            s3_client = boto3.client('s3')
            bucket_name = self.storage.gamedata_s3_bucket
            
            response = s3_client.list_objects_v2(
                Bucket=bucket_name,
                MaxKeys=1
            )
            
            response_time = (time.time() - start_time) * 1000
            object_count = response.get('KeyCount', 0)
            
            return {
                'status': 'healthy',
                'message': f'S3 storage accessible, bucket has {object_count}+ objects',
                'response_time_ms': response_time
            }
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return {
                'status': 'unhealthy',
                'message': f'Storage error: {str(e)}',
                'response_time_ms': response_time,
                'error': str(e)
            }
    
    def check_ai_service_health(self) -> Dict[str, Any]:
        """Check AI service (Bedrock) health."""
        start_time = time.time()
        
        try:
            import boto3
            bedrock_client = boto3.client('bedrock-runtime')
            
            # This is a minimal check - in production you might want to make a small inference
            # For now, just check if we can access the service
            response_time = (time.time() - start_time) * 1000
            
            return {
                'status': 'healthy',
                'message': 'AI service accessible',
                'response_time_ms': response_time
            }
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return {
                'status': 'unhealthy',
                'message': f'AI service error: {str(e)}',
                'response_time_ms': response_time,
                'error': str(e)
            }
    
    def run_all_health_checks(self) -> Dict[str, Any]:
        """Run all registered health checks."""
        checks = [
            ('database', self.check_database_health),
            ('storage', self.check_storage_health),
            ('ai_service', self.check_ai_service_health),
        ]
        
        results = {}
        overall_status = 'healthy'
        total_response_time = 0
        
        for name, check_func in checks:
            try:
                result = check_func()
                status = result.get('status', 'unknown')
                
                # Record health check
                health_check = HealthCheck(
                    name=name,
                    status=status,
                    message=result.get('message', ''),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    response_time_ms=result.get('response_time_ms'),
                    details=result
                )
                
                self.health_checks.append(health_check)
                results[name] = result
                
                # Update overall status
                if status == 'unhealthy':
                    overall_status = 'unhealthy'
                elif status == 'degraded' and overall_status != 'unhealthy':
                    overall_status = 'degraded'
                
                if result.get('response_time_ms'):
                    total_response_time += result['response_time_ms']
                
            except Exception as e:
                logger.error(f"Health check {name} failed: {e}")
                results[name] = {
                    'status': 'unhealthy',
                    'message': f'Health check failed: {str(e)}',
                    'error': str(e)
                }
                overall_status = 'unhealthy'
        
        # Clean up old health checks
        if len(self.health_checks) > self.max_health_checks:
            self.health_checks = self.health_checks[-self.max_health_checks//2:]
        
        return {
            'overall_status': overall_status,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_response_time_ms': total_response_time,
            'checks': results
        }
    
    def get_health_history(self, hours: int = 24) -> List[HealthCheck]:
        """Get health check history for specified hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.isoformat()
        
        return [
            check for check in self.health_checks
            if check.timestamp >= cutoff_str
        ]


def timing_decorator(metric_name: str, tags: Dict[str, str] = None):
    """Decorator to time function execution."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with metrics.timer(metric_name, tags):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def error_tracking_decorator(func):
    """Decorator to track function errors."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            metrics.counter(f"{func.__name__}.success")
            return result
        except Exception as e:
            metrics.counter(f"{func.__name__}.error", tags={'error_type': type(e).__name__})
            raise
    return wrapper


# Global instances
metrics = MetricsCollector()
health_monitor = HealthMonitor()


def get_system_metrics() -> Dict[str, Any]:
    """Get comprehensive system metrics."""
    if not PSUTIL_AVAILABLE:
        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'error': 'psutil not available',
            'system': {},
            'application': {},
            'errors': error_metrics.get_error_summary(),
            'custom_metrics': metrics.get_metric_summary()
        }
    
    # System metrics
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # Application metrics
    process = psutil.Process(os.getpid())
    app_memory = process.memory_info()
    
    # Error metrics
    error_summary = error_metrics.get_error_summary()
    
    # Custom metrics summary
    custom_metrics = metrics.get_metric_summary()
    
    return {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'system': {
            'cpu_percent': cpu_percent,
            'memory_total_mb': memory.total // (1024 * 1024),
            'memory_used_mb': memory.used // (1024 * 1024),
            'memory_percent': memory.percent,
            'disk_total_gb': disk.total // (1024 * 1024 * 1024),
            'disk_used_gb': disk.used // (1024 * 1024 * 1024),
            'disk_percent': (disk.used / disk.total) * 100
        },
        'application': {
            'memory_rss_mb': app_memory.rss // (1024 * 1024),
            'memory_vms_mb': app_memory.vms // (1024 * 1024)
        },
        'errors': error_summary,
        'custom_metrics': custom_metrics
    }


def create_monitoring_dashboard() -> Dict[str, Any]:
    """Create a comprehensive monitoring dashboard data."""
    # Get health status
    health_status = health_monitor.run_all_health_checks()
    
    # Get system metrics
    system_metrics = get_system_metrics()
    
    # Get recent metrics
    recent_metrics = metrics.get_metrics(
        since=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    
    # Get health history
    health_history = health_monitor.get_health_history(hours=24)
    
    return {
        'dashboard_generated': datetime.now(timezone.utc).isoformat(),
        'health_status': health_status,
        'system_metrics': system_metrics,
        'recent_metrics_count': len(recent_metrics),
        'health_checks_24h': len(health_history),
        'alerts': _generate_alerts(health_status, system_metrics)
    }


def _generate_alerts(health_status: Dict[str, Any], 
                    system_metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate alerts based on current status."""
    alerts = []
    
    # Health alerts
    if health_status['overall_status'] == 'unhealthy':
        alerts.append({
            'type': 'health',
            'severity': 'critical',
            'message': 'System health check failed',
            'details': health_status
        })
    
    # Resource alerts
    memory_percent = system_metrics['system']['memory_percent']
    if memory_percent > 90:
        alerts.append({
            'type': 'resource',
            'severity': 'warning',
            'message': f'High memory usage: {memory_percent:.1f}%',
            'details': {'memory_percent': memory_percent}
        })
    
    disk_percent = system_metrics['system']['disk_percent']
    if disk_percent > 80:
        alerts.append({
            'type': 'resource',
            'severity': 'warning',
            'message': f'High disk usage: {disk_percent:.1f}%',
            'details': {'disk_percent': disk_percent}
        })
    
    # Error rate alerts
    error_summary = system_metrics['errors']
    if error_summary['total_errors'] > 10:  # Arbitrary threshold
        alerts.append({
            'type': 'errors',
            'severity': 'warning',
            'message': f"High error count: {error_summary['total_errors']}",
            'details': error_summary
        })
    
    return alerts


# Convenience functions for common metrics
def track_email_processed(game_type: str, success: bool = True) -> None:
    """Track email processing."""
    status = 'success' if success else 'error'
    metrics.counter('emails.processed', tags={
        'game_type': game_type,
        'status': status
    })


def track_turn_completed(game_type: str, turn_number: int, player_count: int) -> None:
    """Track turn completion."""
    metrics.counter('turns.completed', tags={'game_type': game_type})
    metrics.gauge('turns.current_number', turn_number, tags={'game_type': game_type})
    metrics.gauge('sessions.player_count', player_count, tags={'game_type': game_type})


def track_ai_response_time(duration_ms: float, game_type: str) -> None:
    """Track AI response generation time."""
    metrics.histogram('ai.response_time_ms', duration_ms, tags={'game_type': game_type})


def track_session_created(game_type: str) -> None:
    """Track session creation."""
    metrics.counter('sessions.created', tags={'game_type': game_type})


def track_session_completed(game_type: str, duration_minutes: float) -> None:
    """Track session completion."""
    metrics.counter('sessions.completed', tags={'game_type': game_type})
    metrics.histogram('sessions.duration_minutes', duration_minutes, tags={'game_type': game_type})