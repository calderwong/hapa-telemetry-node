"""Node registry and launcher system"""

import os
import json
import asyncio
import subprocess
import signal
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

from .models import NodeStatus


class NodeState(str, Enum):
    """Node lifecycle states"""
    REGISTERED = "registered"
    STARTING = "starting"
    RUNNING = "running"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    RESTARTING = "restarting"


class NodeDefinition:
    """Registered node type definition"""
    
    def __init__(self, data: Dict[str, Any]):
        self.node_type = data["node_type"]
        self.display_name = data["display_name"]
        self.description = data.get("description", "")
        self.launch_config = data["launch_config"]
        self.default_port = data.get("default_port", 8000)
        self.auth_type = data.get("auth_type", "bearer")
        self.capabilities = data.get("capabilities", [])
        self.auto_start = data.get("auto_start", False)
        self.requirements = data.get("requirements", {})
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": self.node_type,
            "display_name": self.display_name,
            "description": self.description,
            "launch_config": self.launch_config,
            "default_port": self.default_port,
            "auth_type": self.auth_type,
            "capabilities": self.capabilities,
            "auto_start": self.auto_start,
            "requirements": self.requirements
        }


class NodeInstance:
    """Running node instance"""
    
    def __init__(self, node_type: str, instance_id: str, port: int, pid: int):
        self.node_type = node_type
        self.instance_id = instance_id
        self.port = port
        self.pid = pid
        self.status = NodeState.STARTING
        self.started_at = datetime.utcnow()
        self.process: Optional[subprocess.Popen] = None
        self.logs_path = f"/tmp/hapa-nodes/{instance_id}.log"
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": self.node_type,
            "instance_id": self.instance_id,
            "port": self.port,
            "pid": self.pid,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "logs_path": self.logs_path
        }


class NodeRegistry:
    """Central registry for node types and instances"""
    
    def __init__(self):
        self.registry_path = Path(os.environ.get(
            "HAPA_REGISTRY_PATH", 
            Path.home() / ".hapa_node_registry.json"
        ))
        self.log_dir = Path(os.environ.get(
            "HAPA_LAUNCHER_LOG_DIR",
            "/tmp/hapa-nodes"
        ))
        self.max_instances = int(os.environ.get(
            "HAPA_LAUNCHER_MAX_INSTANCES", 5
        ))
        self.auto_restart = os.environ.get(
            "HAPA_LAUNCHER_AUTO_RESTART", "false"
        ).lower() == "true"
        
        self.definitions: Dict[str, NodeDefinition] = {}
        self.instances: Dict[str, NodeInstance] = {}
        
        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Load registry
        self._load_registry()
        self._register_default_nodes()
    
    def _load_registry(self):
        """Load registry from disk"""
        if self.registry_path.exists():
            try:
                with open(self.registry_path) as f:
                    data = json.load(f)
                    for node_type, node_data in data.get("nodes", {}).items():
                        self.definitions[node_type] = NodeDefinition(node_data)
            except Exception as e:
                print(f"Failed to load registry: {e}")
    
    def _save_registry(self):
        """Save registry to disk"""
        data = {
            "version": "1.0.0",
            "updated_at": datetime.utcnow().isoformat(),
            "nodes": {
                node_type: defn.to_dict()
                for node_type, defn in self.definitions.items()
            }
        }
        
        with open(self.registry_path, "w") as f:
            json.dump(data, f, indent=2)
    
    def _register_default_nodes(self):
        """Register standard Hapa nodes"""
        defaults = [
            {
                "node_type": "media-node",
                "display_name": "Hapa Media Node",
                "description": "Image generation with mflux",
                "launch_config": {
                    "command": "python -m hapa_media_node",
                    "cwd": "/Users/calderwong/hapa-mlx-station",
                    "env": {"HAPA_MEDIA_NODE_PORT": "8723"}
                },
                "default_port": 8723,
                "auth_type": "bearer",
                "capabilities": ["image-generation", "media-assets"]
            },
            {
                "node_type": "media-hub",
                "display_name": "Hapa Media Hub",
                "description": "Router for multiple media nodes",
                "launch_config": {
                    "command": "python -m hapa_media_node hub",
                    "cwd": "/Users/calderwong/hapa-mlx-station",
                    "env": {"HAPA_MEDIA_HUB_PORT": "8726"}
                },
                "default_port": 8726,
                "auth_type": "bearer",
                "capabilities": ["routing", "load-balancing"]
            },
            {
                "node_type": "llada-node",
                "display_name": "Hapa LLaDA Node",
                "description": "Sovereign local LLM service",
                "launch_config": {
                    "command": "python -m uvicorn src.server:app --host 127.0.0.1 --port $PORT",
                    "cwd": "/Users/calderwong/Desktop/hapa-llada-node",
                    "env": {"PORT": "8085"}
                },
                "default_port": 8085,
                "auth_type": "bearer",
                "capabilities": ["llm", "text-generation"]
            },
            {
                "node_type": "consul-node",
                "display_name": "Consul Node Proto",
                "description": "Local API+UI+CLI scaffold",
                "launch_config": {
                    "command": "python -m consul_node",
                    "cwd": "/Users/calderwong/Desktop/Consul Node Proto",
                    "env": {"CONSUL_NODE_PORT": "8731"}
                },
                "default_port": 8731,
                "auth_type": "bearer",
                "capabilities": ["api", "ui", "cli"]
            },
            {
                "node_type": "luminastem-node",
                "display_name": "LuminaStem Station",
                "description": "3D audio stem visualizer",
                "launch_config": {
                    "command": "python -m hapa_luminastem_node",
                    "cwd": "/Users/calderwong/Desktop/hapa-luminastem-station",
                    "env": {"HAPA_LUMINASTEM_PORT": "8732"}
                },
                "default_port": 8732,
                "auth_type": "bearer",
                "capabilities": ["audio-visualization", "3d-rendering"]
            },
            {
                "node_type": "cultivation-api",
                "display_name": "Cultivation Suite API",
                "description": "Parity API for CLI/library",
                "launch_config": {
                    "command": "npm run dev:parity-api",
                    "cwd": "/Users/calderwong/Desktop/pulse-node-proto-dev/hapa-cultivation-suite",
                    "env": {"PORT": "8787"}
                },
                "default_port": 8787,
                "auth_type": "none",
                "capabilities": ["cli-parity", "capsules"]
            },
            {
                "node_type": "lore-node",
                "display_name": "Hapa Lore Node",
                "description": "Recording Lore and Canon (.bardClass)",
                "launch_config": {
                    "command": "python -m hapa_lore_node",
                    "cwd": "/Users/calderwong/Desktop/hapa-lore-node",
                    "env": {"HAPA_LORE_NODE_PORT": "8734"}
                },
                "default_port": 8734,
                "auth_type": "bearer",
                "capabilities": ["record-lore", "query-canon", "daily-progress"]
            },
            {
                "node_type": "open-tasks-node",
                "display_name": "Hapa Open Tasks Node",
                "description": "Centralized task management",
                "launch_config": {
                    "command": "npm start",
                    "cwd": "/Users/calderwong/Desktop/hapa-open-tasks-node",
                    "env": {"HAPA_OPEN_TASKS_PORT": "8735"}
                },
                "default_port": 8735,
                "auth_type": "bearer",
                "capabilities": ["task-management", "kanban"]
            },
            {
                "node_type": "crypto-node",
                "display_name": "Hapa Crypto Node",
                "description": "Swift-native cryptography service",
                "launch_config": {
                    "command": "./.build/debug/hapa-crypto-node serve --port $PORT",
                    "cwd": "/Users/calderwong/Desktop/hapa-crypto-node",
                    "env": {"PORT": "8736"}
                },
                "default_port": 8736,
                "auth_type": "bearer",
                "capabilities": ["encryption", "signatures", "identity", "hashing"]
            },
            {
                "node_type": "janus-world-node",
                "display_name": "Hapa Janus World Node",
                "description": "Local world truth kernel (event-sourced SQLite)",
                "launch_config": {
                    "command": "python -m hapa_janus_world_node start",
                    "cwd": "/Users/calderwong/Desktop/hapa-janus-world-node",
                    "env": {"HAPA_JANUS_WORLD_NODE_PORT": "8741"}
                },
                "default_port": 8741,
                "auth_type": "bearer",
                "capabilities": ["world-truth", "event-log", "world-state"]
            }
        ]
        
        for node_data in defaults:
            if node_data["node_type"] not in self.definitions:
                self.definitions[node_data["node_type"]] = NodeDefinition(node_data)
        
        self._save_registry()
    
    def register_node(self, node_data: Dict[str, Any]) -> NodeDefinition:
        """Register a new node type"""
        node_type = node_data["node_type"]
        
        if node_type in self.definitions:
            # Update existing
            self.definitions[node_type] = NodeDefinition(node_data)
        else:
            # Create new
            self.definitions[node_type] = NodeDefinition(node_data)
        
        self._save_registry()
        return self.definitions[node_type]
    
    def get_node_definition(self, node_type: str) -> Optional[NodeDefinition]:
        """Get node definition by type"""
        return self.definitions.get(node_type)
    
    def list_definitions(self) -> List[NodeDefinition]:
        """List all registered node types"""
        return list(self.definitions.values())
    
    async def launch_node(
        self, 
        node_type: str,
        instance_id: Optional[str] = None,
        port: Optional[int] = None,
        env_overrides: Optional[Dict[str, str]] = None
    ) -> NodeInstance:
        """Launch a node instance"""
        
        # Get definition
        defn = self.definitions.get(node_type)
        if not defn:
            raise ValueError(f"Node type '{node_type}' not registered")
        
        # Check instance limit
        type_instances = [i for i in self.instances.values() if i.node_type == node_type]
        if len(type_instances) >= self.max_instances:
            raise ValueError(f"Max instances ({self.max_instances}) reached for {node_type}")
        
        # Generate instance ID
        if not instance_id:
            instance_id = f"{node_type}-{len(self.instances):03d}"
        
        # Use default port if not specified
        if not port:
            port = defn.default_port
        
        # Check port availability
        for inst in self.instances.values():
            if inst.port == port and inst.status in [NodeState.RUNNING, NodeState.HEALTHY]:
                raise ValueError(f"Port {port} already in use")
        
        # Prepare environment
        env = os.environ.copy()
        env.update(defn.launch_config.get("env", {}))
        if env_overrides:
            env.update(env_overrides)
        
        # Set port in environment
        if "PORT" in env:
            env["PORT"] = str(port)
        for key in env:
            if "PORT" in key:
                env[key] = str(port)
        
        # Prepare command
        command = defn.launch_config["command"]
        cwd = defn.launch_config.get("cwd", ".")
        
        # Create log file
        log_path = self.log_dir / f"{instance_id}.log"
        log_file = open(log_path, "w")
        
        try:
            # Start process
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid  # Create new process group
            )
            
            # Create instance
            instance = NodeInstance(node_type, instance_id, port, process.pid)
            instance.process = process
            instance.logs_path = str(log_path)
            
            # Track instance
            self.instances[instance_id] = instance
            
            # Start health monitoring
            asyncio.create_task(self._monitor_health(instance_id))
            
            return instance
            
        except Exception as e:
            log_file.close()
            raise ValueError(f"Failed to launch node: {e}")
    
    async def stop_node(self, instance_id: str, timeout: int = 10):
        """Stop a node instance"""
        
        instance = self.instances.get(instance_id)
        if not instance:
            raise ValueError(f"Instance '{instance_id}' not found")
        
        instance.status = NodeState.STOPPING
        
        if instance.process:
            try:
                # Send SIGTERM
                os.killpg(os.getpgid(instance.process.pid), signal.SIGTERM)
                
                # Wait for graceful shutdown
                try:
                    instance.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Force kill
                    os.killpg(os.getpgid(instance.process.pid), signal.SIGKILL)
                    instance.process.wait(timeout=5)
                
            except ProcessLookupError:
                pass  # Process already dead
        
        instance.status = NodeState.STOPPED
        del self.instances[instance_id]
    
    async def _monitor_health(self, instance_id: str):
        """Monitor node health"""
        
        instance = self.instances.get(instance_id)
        if not instance:
            return
        
        defn = self.definitions.get(instance.node_type)
        if not defn:
            return
        
        health_config = defn.launch_config.get("health_check", {})
        endpoint = health_config.get("endpoint", "/health")
        timeout = health_config.get("timeout", 30)
        interval = health_config.get("interval", 5)
        
        # Wait for startup
        await asyncio.sleep(5)
        
        import httpx
        
        start_time = asyncio.get_event_loop().time()
        
        while instance_id in self.instances:
            instance = self.instances[instance_id]
            
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    url = f"http://127.0.0.1:{instance.port}{endpoint}"
                    response = await client.get(url)
                    
                    if response.status_code == 200:
                        if instance.status == NodeState.STARTING:
                            instance.status = NodeState.HEALTHY
                        elif instance.status == NodeState.UNHEALTHY:
                            instance.status = NodeState.HEALTHY
                    else:
                        instance.status = NodeState.UNHEALTHY
                        
            except Exception:
                if instance.status == NodeState.STARTING:
                    # Still starting
                    if asyncio.get_event_loop().time() - start_time > timeout:
                        instance.status = NodeState.FAILED
                        if self.auto_restart:
                            await self._restart_node(instance_id)
                        break
                else:
                    instance.status = NodeState.UNHEALTHY
            
            # Check if process died
            if instance.process and instance.process.poll() is not None:
                instance.status = NodeState.FAILED
                if self.auto_restart:
                    await self._restart_node(instance_id)
                break
            
            await asyncio.sleep(interval)
    
    async def _restart_node(self, instance_id: str):
        """Restart a failed node"""
        
        instance = self.instances.get(instance_id)
        if not instance:
            return
        
        instance.status = NodeState.RESTARTING
        
        # Stop the node
        try:
            await self.stop_node(instance_id)
        except:
            pass
        
        # Relaunch
        try:
            await self.launch_node(
                instance.node_type,
                instance_id,
                instance.port
            )
        except Exception as e:
            print(f"Failed to restart {instance_id}: {e}")
    
    def list_instances(self) -> List[NodeInstance]:
        """List all running instances"""
        return list(self.instances.values())
    
    def get_instance(self, instance_id: str) -> Optional[NodeInstance]:
        """Get instance by ID"""
        return self.instances.get(instance_id)
