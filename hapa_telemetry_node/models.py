"""Data models for telemetry node"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
from pydantic import BaseModel, Field


class NodeStatus(str, Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ServiceType(str, Enum):
    MEDIA = "media"
    LLM = "llm"
    STORAGE = "storage"
    UI = "ui"
    API = "api"
    HUB = "hub"
    TELEMETRY = "telemetry"
    UNKNOWN = "unknown"


class RelationshipType(str, Enum):
    DEPENDS_ON = "depends_on"
    PROVIDES_TO = "provides_to"
    PEERS = "peers"
    MANAGES = "manages"
    MONITORS = "monitors"


class NodeHealth(BaseModel):
    status: HealthStatus = HealthStatus.UNKNOWN
    uptime_seconds: Optional[int] = None
    last_activity: Optional[datetime] = None
    message: Optional[str] = None


class NodeMetrics(BaseModel):
    # System resources
    cpu_percent: Optional[float] = None
    memory_mb: Optional[int] = None
    memory_percent: Optional[float] = None
    disk_gb: Optional[float] = None
    disk_percent: Optional[float] = None
    
    # Network
    network_bytes_sent: Optional[int] = None
    network_bytes_recv: Optional[int] = None
    active_connections: Optional[int] = None
    requests_per_minute: Optional[float] = None
    response_time_ms: Optional[float] = None
    
    # Queue metrics (media/LLM nodes)
    queue_depth: Optional[int] = None
    queue_running: Optional[int] = None
    queue_completed: Optional[int] = None
    
    # Service metrics
    throughput: Optional[float] = None
    uptime_seconds: Optional[int] = None
    custom: Dict[str, Any] = Field(default_factory=dict)


class NodeCapabilities(BaseModel):
    service_type: ServiceType = ServiceType.UNKNOWN
    api_version: Optional[str] = None
    supported_operations: List[str] = Field(default_factory=list)
    modalities: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NodeRelationships(BaseModel):
    depends_on: List[str] = Field(default_factory=list)
    provides_to: List[str] = Field(default_factory=list)
    peers: List[str] = Field(default_factory=list)
    manages: List[str] = Field(default_factory=list)
    monitors: List[str] = Field(default_factory=list)


class NodeTelemetry(BaseModel):
    node_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: NodeStatus = NodeStatus.UNKNOWN
    health: NodeHealth = Field(default_factory=NodeHealth)
    metrics: NodeMetrics = Field(default_factory=NodeMetrics)
    capabilities: NodeCapabilities = Field(default_factory=NodeCapabilities)
    relationships: NodeRelationships = Field(default_factory=NodeRelationships)


class NodeInfo(BaseModel):
    node_id: str
    service_type: ServiceType = ServiceType.UNKNOWN
    base_url: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    auth_required: bool = True
    token: Optional[str] = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NodeRegistration(BaseModel):
    node_id: str
    service_type: ServiceType
    base_url: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    auth_required: bool = True
    token: Optional[str] = None
    capabilities: Optional[NodeCapabilities] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GraphNode(BaseModel):
    id: str
    label: str
    service_type: ServiceType
    status: NodeStatus
    x: Optional[float] = None
    y: Optional[float] = None


class GraphEdge(BaseModel):
    source: str
    target: str
    relationship: RelationshipType
    label: Optional[str] = None


class NodeGraph(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    metadata: Dict[str, Any] = Field(default_factory=dict)
