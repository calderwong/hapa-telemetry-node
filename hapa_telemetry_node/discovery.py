"""Node discovery engine for telemetry node"""

import asyncio
import json
import socket
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

import httpx
from zeroconf import ServiceBrowser, Zeroconf, ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from .models import NodeInfo, ServiceType, NodeStatus
from .database import Database

logger = logging.getLogger(__name__)


class NodeDiscovery:
    """Multi-method node discovery engine"""
    
    def __init__(self, db: Database):
        self.db = db
        self.known_ports = {
            8080: ("media", ServiceType.MEDIA),
            8081: ("media", ServiceType.MEDIA),
            8082: ("media", ServiceType.MEDIA),
            8083: ("media", ServiceType.MEDIA),
            8084: ("media", ServiceType.MEDIA),
            8085: ("llada", ServiceType.LLM),
            8723: ("media", ServiceType.MEDIA),
            8726: ("media-hub", ServiceType.HUB),
            8730: ("telemetry", ServiceType.TELEMETRY),
            8731: ("consul", ServiceType.API),
            8732: ("luminastem", ServiceType.UI),
            8741: ("janus-world", ServiceType.API),
            8787: ("cultivation", ServiceType.API),
            5173: ("vite-dev", ServiceType.UI),
        }
        self.registry_file = Path.home() / ".hapa_nodes.json"
        self.zeroconf = None
        self.browser = None
        
    async def start(self):
        """Start discovery services"""
        # Start mDNS listener
        await self._start_mdns()
        
    async def stop(self):
        """Stop discovery services"""
        if self.zeroconf:
            await self.zeroconf.async_close()
    
    async def _start_mdns(self):
        """Start mDNS discovery"""
        try:
            self.zeroconf = AsyncZeroconf()
            # Listen for _hapa-node._tcp services
            self.browser = ServiceBrowser(
                self.zeroconf.zeroconf,
                "_hapa-node._tcp.local.",
                handlers=[self._on_service_state_change]
            )
            logger.info("mDNS discovery started")
        except Exception as e:
            logger.error(f"Failed to start mDNS: {e}")
    
    def _on_service_state_change(self, zeroconf: Zeroconf, service_type: str, 
                                 name: str, state_change):
        """Handle mDNS service discovery"""
        try:
            info = zeroconf.get_service_info(service_type, name)
            if info:
                # Extract node info from mDNS service
                addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
                if addresses:
                    host = addresses[0]
                    port = info.port
                    
                    # Extract properties
                    props = info.properties
                    node_id = props.get(b'node_id', name.encode()).decode()
                    service = props.get(b'service_type', b'unknown').decode()
                    
                    # Register discovered node
                    asyncio.create_task(self._register_discovered_node(
                        node_id=node_id,
                        base_url=f"http://{host}:{port}",
                        service_type=service
                    ))
        except Exception as e:
            logger.error(f"Error processing mDNS service: {e}")
    
    async def scan_ports(self, host: str = "127.0.0.1", 
                        port_range: tuple = (8000, 9000)) -> List[NodeInfo]:
        """Scan ports for known services"""
        discovered = []
        
        # Check known ports first
        for port, (name, service_type) in self.known_ports.items():
            if await self._check_port(host, port):
                node_info = await self._probe_node(f"http://{host}:{port}")
                if node_info:
                    discovered.append(node_info)
                    await self.db.register_node(node_info)
        
        # Scan additional range (selective)
        if len(discovered) < 3:  # Only scan if we haven't found much
            for port in range(port_range[0], min(port_range[0] + 100, port_range[1])):
                if port not in self.known_ports:
                    if await self._check_port(host, port):
                        node_info = await self._probe_node(f"http://{host}:{port}")
                        if node_info:
                            discovered.append(node_info)
                            await self.db.register_node(node_info)
        
        return discovered
    
    async def _check_port(self, host: str, port: int) -> bool:
        """Check if a port is open"""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=0.5
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return False
    
    async def _probe_node(self, base_url: str) -> Optional[NodeInfo]:
        """Probe a URL to identify node type"""
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                # Try health endpoint
                resp = await client.get(f"{base_url}/health")
                if resp.status_code == 200:
                    health_data = resp.json()
                    
                    # Try to get capabilities
                    caps = None
                    node_id = base_url.replace("http://", "").replace(":", "_")
                    service_type = ServiceType.UNKNOWN
                    
                    try:
                        cap_resp = await client.get(f"{base_url}/capabilities")
                        if cap_resp.status_code == 200:
                            caps = cap_resp.json()
                            node_id = caps.get("node_id", node_id)
                            service_type = self._detect_service_type(caps)
                    except:
                        pass
                    
                    # Detect service type from health/capabilities
                    if "media" in base_url or "8723" in base_url:
                        service_type = ServiceType.MEDIA
                    elif "llada" in base_url or "8085" in base_url:
                        service_type = ServiceType.LLM
                    elif "hub" in base_url or "8726" in base_url:
                        service_type = ServiceType.HUB
                    elif "telemetry" in base_url or "8730" in base_url:
                        service_type = ServiceType.TELEMETRY
                    elif "consul" in base_url or "8731" in base_url:
                        service_type = ServiceType.API
                    elif "luminastem" in base_url or "8732" in base_url:
                        service_type = ServiceType.UI
                    elif "janus" in base_url or "8741" in base_url:
                        service_type = ServiceType.API
                    
                    return NodeInfo(
                        node_id=node_id,
                        service_type=service_type,
                        base_url=base_url,
                        display_name=caps.get("service", node_id) if caps else node_id,
                        auth_required=cap_resp.status_code == 401 if caps else True,
                        metadata={"health": health_data, "capabilities": caps}
                    )
            except Exception as e:
                logger.debug(f"Failed to probe {base_url}: {e}")
        
        return None
    
    def _detect_service_type(self, capabilities: Dict[str, Any]) -> ServiceType:
        """Detect service type from capabilities"""
        if "modalities" in capabilities:
            if "image" in capabilities["modalities"]:
                return ServiceType.MEDIA
        
        if "model" in capabilities or "llm" in str(capabilities).lower():
            return ServiceType.LLM
        
        if "hub" in str(capabilities).lower():
            return ServiceType.HUB
        
        service = capabilities.get("service", "").lower()
        if "media" in service:
            return ServiceType.MEDIA
        elif "llm" in service or "llada" in service:
            return ServiceType.LLM
        elif "hub" in service:
            return ServiceType.HUB
        elif "telemetry" in service:
            return ServiceType.TELEMETRY
        
        return ServiceType.UNKNOWN
    
    async def read_registry(self) -> List[NodeInfo]:
        """Read nodes from shared registry file"""
        discovered = []
        
        if self.registry_file.exists():
            try:
                data = json.loads(self.registry_file.read_text())
                for node_data in data.get("nodes", []):
                    node_info = NodeInfo(
                        node_id=node_data["node_id"],
                        service_type=ServiceType(node_data.get("service_type", "unknown")),
                        base_url=node_data["base_url"],
                        display_name=node_data.get("display_name"),
                        description=node_data.get("description"),
                        auth_required=node_data.get("auth_required", True),
                        token=node_data.get("token"),
                        metadata=node_data.get("metadata", {})
                    )
                    discovered.append(node_info)
                    await self.db.register_node(node_info)
            except Exception as e:
                logger.error(f"Failed to read registry: {e}")
        
        return discovered
    
    async def write_registry(self, nodes: List[NodeInfo]):
        """Write nodes to shared registry file"""
        try:
            data = {
                "updated_at": datetime.utcnow().isoformat(),
                "nodes": [
                    {
                        "node_id": node.node_id,
                        "service_type": node.service_type.value,
                        "base_url": node.base_url,
                        "display_name": node.display_name,
                        "description": node.description,
                        "auth_required": node.auth_required,
                        "metadata": node.metadata
                    }
                    for node in nodes
                ]
            }
            self.registry_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to write registry: {e}")
    
    async def discover_all(self) -> List[NodeInfo]:
        """Run all discovery methods"""
        all_nodes = []
        
        # Read registry
        registry_nodes = await self.read_registry()
        all_nodes.extend(registry_nodes)
        
        # Scan ports
        scanned_nodes = await self.scan_ports()
        
        # Merge discoveries (avoid duplicates)
        seen_ids = {n.node_id for n in all_nodes}
        for node in scanned_nodes:
            if node.node_id not in seen_ids:
                all_nodes.append(node)
                seen_ids.add(node.node_id)
        
        # Update registry with discoveries
        if all_nodes:
            await self.write_registry(all_nodes)
        
        return all_nodes
    
    async def _register_discovered_node(self, node_id: str, base_url: str, 
                                       service_type: str):
        """Register a discovered node"""
        try:
            # Probe for more details
            node_info = await self._probe_node(base_url)
            if not node_info:
                node_info = NodeInfo(
                    node_id=node_id,
                    service_type=ServiceType(service_type),
                    base_url=base_url
                )
            
            await self.db.register_node(node_info)
            logger.info(f"Registered node: {node_id} at {base_url}")
        except Exception as e:
            logger.error(f"Failed to register node {node_id}: {e}")
