"""Telemetry collection engine"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import json

import httpx
import psutil

from .models import (
    NodeInfo, NodeTelemetry, NodeStatus, HealthStatus,
    NodeHealth, NodeMetrics, NodeCapabilities, NodeRelationships,
    ServiceType
)
from .database import Database

logger = logging.getLogger(__name__)


class TelemetryCollector:
    """Collects telemetry from registered nodes"""
    
    def __init__(self, db: Database, interval: int = 10):
        self.db = db
        self.interval = interval
        self.running = False
        self.tasks = {}
        
    async def start(self):
        """Start telemetry collection"""
        self.running = True
        logger.info(f"Starting telemetry collection (interval: {self.interval}s)")
        
        while self.running:
            try:
                # Get all registered nodes
                nodes = await self.db.list_nodes()
                
                # Collect telemetry from each node
                tasks = []
                for node in nodes:
                    tasks.append(self._collect_node_telemetry(node))
                
                # Run collections in parallel
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                # Sleep before next collection
                await asyncio.sleep(self.interval)
                
            except Exception as e:
                logger.error(f"Error in telemetry collection loop: {e}")
                await asyncio.sleep(5)
    
    async def stop(self):
        """Stop telemetry collection"""
        self.running = False
        logger.info("Stopping telemetry collection")
    
    async def _collect_node_telemetry(self, node: NodeInfo) -> Optional[NodeTelemetry]:
        """Collect telemetry from a single node"""
        try:
            telemetry = NodeTelemetry(
                node_id=node.node_id,
                timestamp=datetime.utcnow(),
                status=NodeStatus.UNKNOWN
            )
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Set up headers if auth required
                headers = {}
                if node.auth_required and node.token:
                    headers["Authorization"] = f"Bearer {node.token}"
                
                # Try to get health status
                try:
                    resp = await client.get(f"{node.base_url}/health", headers=headers)
                    if resp.status_code == 200:
                        health_data = resp.json()
                        telemetry.status = NodeStatus.ONLINE
                        ok_flag = health_data.get("ok")
                        raw_status = str(health_data.get("status") or "").lower().strip()
                        is_healthy = bool(ok_flag) if isinstance(ok_flag, bool) else raw_status in {"healthy", "ok", "pass", "passing"}
                        telemetry.health = NodeHealth(
                            status=HealthStatus.HEALTHY if is_healthy else HealthStatus.UNHEALTHY,
                            message=health_data.get("message")
                        )
                    else:
                        telemetry.status = NodeStatus.DEGRADED
                except httpx.RequestError:
                    telemetry.status = NodeStatus.OFFLINE
                    await self.db.mark_node_offline(node.node_id)
                    return telemetry
                
                # Try to get capabilities
                try:
                    for caps_path in ("/v1/capabilities", "/capabilities"):
                        try:
                            resp = await client.get(
                                f"{node.base_url}{caps_path}",
                                headers=headers
                            )
                            if resp.status_code == 200:
                                caps_data = resp.json()
                                telemetry.capabilities = self._parse_capabilities(caps_data)
                                break
                        except Exception:
                            continue
                except:
                    pass
                
                # Try to get telemetry endpoint
                try:
                    resp = await client.get(
                        f"{node.base_url}/v1/telemetry",
                        headers=headers
                    )
                    if resp.status_code == 200:
                        telem_data = resp.json()
                        telemetry.metrics = self._parse_metrics(telem_data.get("metrics", {}))
                        telemetry.relationships = self._parse_relationships(telem_data.get("relationships", {}))
                    else:
                        # If no telemetry endpoint (or auth denied), try common alternatives
                        telemetry.metrics = await self._collect_alternative_metrics(node, client, headers)
                except:
                    # If request errors or parse errors, try common alternatives
                    telemetry.metrics = await self._collect_alternative_metrics(node, client, headers)
                
                # Record telemetry
                await self.db.record_telemetry(telemetry)
                return telemetry
                
        except Exception as e:
            logger.error(f"Failed to collect telemetry from {node.node_id}: {e}")
            return None
    
    def _parse_capabilities(self, data: Dict[str, Any]) -> NodeCapabilities:
        """Parse capabilities from response"""
        caps = NodeCapabilities()
        
        # Detect service type
        if "service" in data:
            service = data["service"].lower()
            if "media" in service:
                caps.service_type = ServiceType.MEDIA
            elif "llm" in service or "llada" in service:
                caps.service_type = ServiceType.LLM
            elif "hub" in service:
                caps.service_type = ServiceType.HUB
            elif "telemetry" in service:
                caps.service_type = ServiceType.TELEMETRY
        
        caps.api_version = data.get("api_version", data.get("version"))
        caps.modalities = data.get("modalities", {})
        caps.metadata = data
        
        return caps
    
    def _parse_metrics(self, data: Dict[str, Any]) -> NodeMetrics:
        """Parse metrics from response"""
        metrics = NodeMetrics()
        
        metrics.cpu_percent = data.get("cpu_percent")
        metrics.memory_mb = data.get("memory_mb")
        metrics.disk_usage_mb = data.get("disk_usage_mb")
        metrics.active_connections = data.get("active_connections")
        metrics.queue_depth = data.get("queue_depth")
        metrics.tasks_completed = data.get("tasks_completed")
        metrics.tasks_failed = data.get("tasks_failed")
        metrics.custom = data
        
        return metrics
    
    def _parse_relationships(self, data: Dict[str, Any]) -> NodeRelationships:
        """Parse relationships from response"""
        rels = NodeRelationships()
        
        rels.depends_on = data.get("depends_on", [])
        rels.provides_to = data.get("provides_to", [])
        rels.peers = data.get("peers", [])
        rels.manages = data.get("manages", [])
        rels.monitors = data.get("monitors", [])
        
        return rels
    
    async def _collect_alternative_metrics(self, node: NodeInfo, client: httpx.AsyncClient, headers: Dict[str, str]) -> NodeMetrics:
        """Collect metrics from alternative endpoints"""
        metrics = NodeMetrics()
        
        # Collect system metrics using psutil
        try:
            import psutil
            metrics.cpu_percent = psutil.cpu_percent(interval=0.1)
            
            mem = psutil.virtual_memory()
            metrics.memory_mb = int(mem.used / (1024 * 1024))
            metrics.memory_percent = mem.percent
            
            disk = psutil.disk_usage('/')
            metrics.disk_gb = round(disk.used / (1024 * 1024 * 1024), 1)
            metrics.disk_percent = disk.percent
            
            # Get network stats
            net = psutil.net_io_counters()
            metrics.network_bytes_sent = net.bytes_sent
            metrics.network_bytes_recv = net.bytes_recv
        except Exception as e:
            logger.debug(f"Could not collect system metrics: {e}")
        
        # Try common endpoints for service-specific metrics
        endpoints = [
            "/v1/queue",
            "/v1/stats", 
            "/v1/status",
            "/v1/system"
        ]
        
        for endpoint in endpoints:
            try:
                resp = await client.get(f"{node.base_url}{endpoint}", headers=headers, timeout=2.0)
                if resp.status_code == 200:
                    data = resp.json()
                    
                    # Queue metrics for media/LLM nodes
                    if "queue" in data:
                        queue = data.get("queue", {})
                        if isinstance(queue, dict):
                            metrics.queue_depth = queue.get("pending", 0)
                            metrics.queue_running = queue.get("running", 0)
                            metrics.queue_completed = queue.get("completed", 0)
                        elif isinstance(queue, list):
                            metrics.queue_depth = len(queue)
                    
                    # Parse any other metrics we find
                    if "requests_per_minute" in data:
                        metrics.requests_per_minute = data["requests_per_minute"]
                    if "throughput" in data:
                        metrics.throughput = data["throughput"]
                    if "uptime" in data:
                        metrics.uptime_seconds = data["uptime"]
                        
            except:
                continue
                
        return metrics
    
    async def collect_local_telemetry(self) -> NodeTelemetry:
        """Collect telemetry for this telemetry node itself"""
        try:
            # Get system metrics
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            
            # Count nodes being monitored
            nodes = await self.db.list_nodes(active_only=True)
            
            telemetry = NodeTelemetry(
                node_id="telemetry-node",
                timestamp=datetime.utcnow(),
                status=NodeStatus.ONLINE,
                health=NodeHealth(
                    status=HealthStatus.HEALTHY,
                    uptime_seconds=int((datetime.utcnow() - datetime(2024, 1, 1)).total_seconds())
                ),
                metrics=NodeMetrics(
                    cpu_percent=cpu_percent,
                    memory_mb=int(memory.used / (1024 * 1024)),
                    memory_percent=memory.percent,
                    disk_gb=round(disk.used / (1024 * 1024 * 1024), 1),
                    disk_percent=disk.percent,
                    active_connections=len(nodes),
                    custom={
                        "monitored_nodes": len(nodes),
                        "collection_interval": self.interval
                    }
                ),
                capabilities=NodeCapabilities(
                    service_type=ServiceType.TELEMETRY,
                    api_version="1.0.0",
                    supported_operations=["discover", "monitor", "graph"]
                ),
                relationships=NodeRelationships(
                    monitors=[n.node_id for n in nodes]
                )
            )
            
            await self.db.record_telemetry(telemetry)
            return telemetry
            
        except Exception as e:
            logger.error(f"Failed to collect local telemetry: {e}")
            return None
